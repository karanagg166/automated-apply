"""Independent outreach account. Only explicitly reviewed Gmail draft creation exists."""

import asyncio
import base64
import json
import re
import secrets
from datetime import timedelta
from email.message import EmailMessage
from uuid import uuid4

import httpx
from pydantic import EmailStr, Field, StrictBool, ValidationError
from sqlalchemy import select, text

from backend.app.ai.schemas import Contract
from backend.app.dashboard.models import OwnerPreference
from backend.app.integrations.connection_service import digest
from backend.app.integrations.google_oauth import (
    COMPOSE_SCOPES,
    GoogleOAuth,
    TokenResponse,
    normalized_scopes,
)
from backend.app.integrations.token_store import ConnectionError, TokenStore
from backend.app.models.connected_account import GmailReadAccount
from backend.app.models.discovery import now

ACCOUNT = "gmail_drafts:account"
INTENT = "gmail_draft_oauth:"
DRAFT = "gmail_draft:"


class DraftInput(Contract):
    expected_version: int = Field(0, ge=0)
    recipient: EmailStr
    company: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=200)
    context: str = Field(min_length=10, max_length=2000)
    subject: str | None = Field(None, min_length=1, max_length=200)
    body: str | None = Field(None, min_length=1, max_length=10000)


class DraftApproval(Contract):
    expected_version: int = Field(ge=1)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    owner_reviewed: StrictBool
    expected_account_generation: int = Field(ge=1)


class GmailDraftClient:
    def __init__(self, client=None):
        self.client = client

    async def create(self, token, sender, draft):
        message = EmailMessage()
        # EmailMessage rejects header injection; no arbitrary headers, attachments or recipients.
        message["From"], message["To"], message["Subject"] = sender, draft["recipient"], draft["subject"]
        message.set_content(draft["body"])
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        async def request(client):
            async with client.stream("POST", "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
                    json={"message": {"raw": raw}}, headers={"Authorization": "Bearer " + token},
                    timeout=15, follow_redirects=False) as response:
                if response.status_code not in {200, 201}:
                    # A server failure may follow acceptance. Never retry this dispatch automatically.
                    raise ConnectionError("gmail_draft_creation_unconfirmed")
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > 65536:
                        raise ConnectionError("gmail_draft_creation_unconfirmed")
                value = json.loads(content)
                if not isinstance(value.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", value["id"]):
                    raise ConnectionError("gmail_draft_creation_unconfirmed")
                return value["id"]

        try:
            async with asyncio.timeout(20):
                if self.client:
                    return await request(self.client)
                async with httpx.AsyncClient(trust_env=False) as client:
                    return await request(client)
        except (httpx.HTTPError, ValueError, TimeoutError):
            raise ConnectionError("gmail_draft_creation_unconfirmed") from None


class DraftAccountService:
    def __init__(self, session, settings, google=None, client=None):
        self.session, self.settings = session, settings
        self.google, self.client = google or GoogleOAuth(settings), client

    async def lock(self):
        if self.session.get_bind().dialect.name == "postgresql":
            await self.session.execute(text("SELECT pg_advisory_xact_lock(407006, 1)"))

    async def row(self):
        return await self.session.get(OwnerPreference, ACCOUNT, with_for_update=True, populate_existing=True)

    async def status(self):
        row = await self.row()
        value = row.value if row else {}
        return {k: value.get(k) for k in ("status", "account_email", "google_subject", "generation")} | {
            "workflow": "drafts_only", "drafts_enabled": self.settings.GMAIL_DRAFTS_ENABLED,
            "sending_enabled": False, "permissions": {"drafts": True, "send": False, "read_mail": False}}

    async def start(self, browser):
        if not self.google.configured():
            raise ConnectionError("google_oauth_not_configured")
        store = TokenStore(self.settings)
        await self.lock()
        row = await self.row()
        if row and row.value.get("status") == "connected":
            raise ConnectionError("disconnect_before_reconnecting")
        generation = (row.value.get("generation", 0) if row else 0) + 1
        value = {"status": "disconnected", "generation": generation}
        if row:
            row.value = value
        else:
            self.session.add(OwnerPreference(key=ACCOUNT, value=value))
        state, verifier = "draft." + secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        self.session.add(OwnerPreference(key=INTENT + digest(state)[:32], value={
            "state_hash": digest(state),
            "browser_hash": digest(browser), "generation": generation, "consumed": False,
            "verifier": store.encrypt(verifier, digest(state)),
            "expires_at": (now() + timedelta(seconds=self.settings.OAUTH_STATE_TTL_SECONDS)).isoformat(),
        }))
        await self.session.commit()
        return {"authorization_url": self.google.authorization_url(state, verifier, None, compose=True),
                "expires_in": self.settings.OAUTH_STATE_TTL_SECONDS}

    async def callback(self, state, browser, callback_uri, code=None, error=None):
        if not browser or callback_uri != self.settings.GMAIL_REDIRECT_URI:
            raise ConnectionError("invalid_oauth_state_or_redirect")
        await self.lock()
        row = await self.session.get(OwnerPreference, INTENT + digest(state)[:32], with_for_update=True, populate_existing=True)
        account = await self.row()
        value = dict(row.value) if row else {}
        if (not row or value.get("state_hash") != digest(state) or value.get("consumed") or value.get("browser_hash") != digest(browser)
                or value.get("expires_at", "") <= now().isoformat() or not account
                or account.value.get("generation") != value.get("generation")):
            raise ConnectionError("invalid_expired_or_replayed_state")
        store = TokenStore(self.settings)
        verifier = store.decrypt(value.pop("verifier"), digest(state))
        row.value = {**value, "consumed": True}
        await self.session.commit()
        if error or not code:
            raise ConnectionError("consent_denied")
        try:
            tokens = TokenResponse.model_validate(await self.google.exchange(code, verifier))
        except ValidationError:
            raise ConnectionError("invalid_token_response") from None
        if not tokens.refresh_token or normalized_scopes(tokens.scope) != COMPOSE_SCOPES:
            raise ConnectionError("unexpected_or_insufficient_scopes")
        subject, email = await self.google.identity(tokens.access_token)
        from backend.app.integrations.token_store import require_approved_mailbox
        require_approved_mailbox(self.settings, email)
        await self.lock()
        account = await self.row()
        if account.value.get("generation") != value["generation"]:
            raise ConnectionError("connection_intent_superseded")
        read = await self.session.scalar(select(GmailReadAccount).where(
            (GmailReadAccount.google_subject == subject) | (GmailReadAccount.account_email == email)))
        if read:
            raise ConnectionError("gmail_separate_outreach_account_required")
        account.value = {"status": "connected", "generation": value["generation"] + 1,
            "account_email": email, "google_subject": subject, "scopes": sorted(COMPOSE_SCOPES),
            "access": store.encrypt(tokens.access_token, ACCOUNT + ":access"),
            "refresh": store.encrypt(tokens.refresh_token, ACCOUNT + ":refresh"),
            "expires_at": (now() + timedelta(seconds=tokens.expires_in)).isoformat()}
        await self.session.commit()
        return await self.status()

    async def access(self):
        await self.lock()
        row = await self.row()
        if not row or row.value.get("status") != "connected" or set(row.value.get("scopes", [])) != COMPOSE_SCOPES:
            raise ConnectionError("gmail_drafts_account_not_connected")
        value = dict(row.value)
        from backend.app.integrations.token_store import require_approved_mailbox
        require_approved_mailbox(self.settings, value.get("account_email"))
        store = TokenStore(self.settings)
        if value["expires_at"] <= (now() + timedelta(seconds=60)).isoformat():
            try:
                refresh = store.decrypt(value["refresh"], ACCOUNT + ":refresh")
                tokens = TokenResponse.model_validate(await self.google.refresh(refresh))
                scopes = normalized_scopes(tokens.scope) if tokens.scope else set(value["scopes"])
                if scopes != COMPOSE_SCOPES or await self.google.identity(tokens.access_token) != (value["google_subject"], value["account_email"]):
                    raise ConnectionError("gmail_drafts_reauthorization_required")
                value.update(access=store.encrypt(tokens.access_token, ACCOUNT + ":access"),
                    refresh=store.encrypt(tokens.refresh_token or refresh, ACCOUNT + ":refresh"),
                    expires_at=(now() + timedelta(seconds=tokens.expires_in)).isoformat())
                row.value = value
            except (ConnectionError, ValidationError):
                row.value = {**value, "status": "reauthorization_required", "access": None}
                await self.session.commit()
                raise ConnectionError("gmail_drafts_reauthorization_required") from None
        token = store.decrypt(value["access"], ACCOUNT + ":access")
        await self.session.commit()
        return token, value

    async def disconnect(self):
        await self.lock()
        row = await self.row()
        # Disconnect locally without any mailbox operation. Google revocation is manual.
        if row:
            row.value = {"status": "disconnected", "generation": row.value.get("generation", 0) + 1}
        await self.session.commit()
        return {"status": "disconnected", "revoke_in_google_settings": True}

    async def drafts(self):
        rows = (await self.session.scalars(select(OwnerPreference).where(
            OwnerPreference.key.startswith(DRAFT)).order_by(OwnerPreference.created_at.desc()).limit(100))).all()
        if not rows:
            return []
        store = TokenStore(self.settings)
        return [{**r.value, "content": json.loads(store.decrypt(r.value["content"], r.key))} for r in rows]

    async def save(self, data, draft_id=None):
        from backend.app.local_agent.knowledge import reviewed_profile
        profile = await reviewed_profile(self.session)
        if not profile:
            raise ConnectionError("current_approved_profile_required")
        await self.lock()
        key = DRAFT + (draft_id or uuid4().hex)
        row = await self.session.get(OwnerPreference, key, with_for_update=True, populate_existing=True)
        old = row.value if row else {}
        if old.get("version", 0) != data.expected_version or old.get("status") in {"dispatching", "unknown", "saved_in_gmail"}:
            raise ConnectionError("gmail_draft_version_or_state_conflict")
        content = {"recipient": str(data.recipient),
            "subject": data.subject or f"{data.role} opportunities at {data.company}",
            "body": data.body or f"Hello,\n\nI’m {profile.full_name}. I’m interested in {data.role} opportunities at {data.company}. {data.context}\n\nMy verified skills include {', '.join(profile.verified_skills[:4])}. I would welcome a conversation.\n\nThank you,\n{profile.full_name}"}
        if any("\n" in content[k] or "\r" in content[k] for k in ("recipient", "subject")):
            raise ConnectionError("gmail_draft_header_invalid")
        value = {"id": key[len(DRAFT):], "version": old.get("version", 0) + 1,
                 "status": "local_draft", "profile_version": profile.version,
                 "company": data.company, "role": data.role,
                 "content_hash": digest(json.dumps(content, sort_keys=True)),
                 "content": TokenStore(self.settings).encrypt(json.dumps(content), key)}
        if row:
            row.value = value
        else:
            self.session.add(OwnerPreference(key=key, value=value))
        await self.session.commit()
        return {**value, "content": content}

    async def create_in_gmail(self, draft_id, approval):
        if not self.settings.GMAIL_DRAFTS_ENABLED:
            raise ConnectionError("gmail_draft_creation_disabled")
        if not approval.owner_reviewed:
            raise ConnectionError("gmail_exact_draft_review_required")
        token, account = await self.access()
        if account["generation"] != approval.expected_account_generation:
            raise ConnectionError("gmail_drafts_account_changed")
        await self.lock()
        row = await self.session.get(OwnerPreference, DRAFT + draft_id, with_for_update=True, populate_existing=True)
        if not row or row.value.get("version") != approval.expected_version or row.value.get("content_hash") != approval.content_hash:
            raise ConnectionError("gmail_draft_version_or_state_conflict")
        value = dict(row.value)
        if value["status"] == "saved_in_gmail":
            return {"status": value["status"], "gmail_draft_id": value["gmail_draft_id"]}
        if value["status"] != "local_draft":
            raise ConnectionError("gmail_draft_dispatch_requires_manual_reconciliation")
        from backend.app.local_agent.knowledge import reviewed_profile
        profile = await reviewed_profile(self.session)
        if not profile or profile.version != value["profile_version"]:
            raise ConnectionError("gmail_draft_profile_changed_review_again")
        current = await self.row()
        if current.value.get("generation") != account["generation"] or current.value.get("status") != "connected":
            raise ConnectionError("gmail_drafts_account_changed")
        content = json.loads(TokenStore(self.settings).decrypt(value["content"], row.key))
        value.update(status="dispatching", account_subject=account["google_subject"])
        row.value = value
        await self.session.commit()  # durable fence before the one mailbox write
        try:
            gmail_id = await GmailDraftClient(self.client).create(token, account["account_email"], content)
        except ConnectionError:
            row = await self.session.get(OwnerPreference, DRAFT + draft_id, with_for_update=True, populate_existing=True)
            row.value = {**row.value, "status": "unknown"}
            await self.session.commit()
            raise
        row = await self.session.get(OwnerPreference, DRAFT + draft_id, with_for_update=True, populate_existing=True)
        row.value = {**row.value, "status": "saved_in_gmail", "gmail_draft_id": gmail_id}
        await self.session.commit()
        return {"status": "saved_in_gmail", "gmail_draft_id": gmail_id, "sent": False}
