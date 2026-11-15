"""Two explicit read/draft grants. No poller, sending or mailbox mutation proxy."""

import base64
import hashlib
import json
import re
import secrets
from datetime import timedelta
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr
from typing import Literal
from uuid import UUID, uuid4

from pydantic import EmailStr, Field, StrictBool
from sqlalchemy import text

from backend.app.ai.schemas import Contract
from backend.app.dashboard.models import OwnerPreference
from backend.app.integrations.gmail.read_client import (
    IDENTIFIER,
    GmailReadClient,
    content_evidence,
)
from backend.app.integrations.google_oauth import (
    READ_DRAFT_SCOPES,
    GoogleOAuth,
    TokenResponse,
    normalized_scopes,
)
from backend.app.integrations.token_store import ConnectionError, TokenStore
from backend.app.models.discovery import now

Slot = Literal["1", "2"]
ACCOUNT = "gm54_account:"
INTENT = "gm54_oauth:"
SELECTION = "gm54_selected:"
TEST = "gm54_test:"
TEST_SUBJECT = "Automated Apply TEST - UNSENT read/draft acceptance"
TEST_BODY = "This is an owner-authorized Automated Apply connectivity test draft. It has not been sent. No application or candidate claims are included."


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Consent(Contract):
    account_consent: StrictBool
    read_and_draft_consent: StrictBool


class Search(Contract):
    query: str = Field(default="Naukri newer_than:30d", min_length=1, max_length=500)
    limit: int = Field(default=3, ge=1, le=5)


class Generation(Contract):
    expected_generation: int = Field(ge=1)


def draft_hash(recipient, subject, body):
    canonical = json.dumps([str(recipient).casefold(), subject, body.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"], ensure_ascii=False, separators=(",", ":"))
    return digest(canonical)


class ReviewedDraft(Generation):
    request_id: UUID
    recipient: EmailStr
    subject: str = Field(min_length=1, max_length=180, pattern=r"^[^\x00-\x1f\x7f]+$")
    body: str = Field(min_length=1, max_length=10000)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    owner_reviewed: StrictBool


def headers(message):
    values = {}
    for h in message.get("payload", {}).get("headers", [])[:100]:
        if isinstance(h, dict) and isinstance(h.get("name"), str) and isinstance(h.get("value"), str):
            name = h["name"].casefold()
            if name in {"from", "to", "cc", "bcc", "subject", "date", "message-id", "authentication-results"}:
                values.setdefault(name, " ".join(h["value"].split())[:1000])
    return values


def verified_draft_content(message, account_email, recipient, subject, body):
    """Check exact content against the durable draft ID, not a rewritten RFC ID."""
    raw_headers = message.get("payload", {}).get("headers", [])
    names = [str(item.get("name", "")).casefold() for item in raw_headers if isinstance(item, dict)]
    if len(raw_headers) > 100 or any(names.count(name) > 1 for name in ("from", "to", "cc", "bcc", "subject", "message-id")):
        raise ConnectionError("gmail_draft_content_unverified")
    h = headers(message)
    encoded = message.get("payload", {}).get("body", {}).get("data", "")
    try:
        if not isinstance(encoded, str) or len(encoded) > 60000:
            raise ValueError
        actual_body = base64.b64decode(encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True).decode("utf-8")
    except (ValueError, UnicodeError):
        raise ConnectionError("gmail_draft_content_unverified") from None
    recipients = getaddresses([h.get("to", "")])
    if ("DRAFT" not in message.get("labelIds", []) or "SENT" in message.get("labelIds", [])
            or parseaddr(h.get("from", ""))[1].casefold() != account_email
            or len(recipients) != 1 or h.get("cc") or h.get("bcc")
            or draft_hash(recipients[0][1], h.get("subject", ""), actual_body) != draft_hash(recipient, subject, body)):
        raise ConnectionError("gmail_draft_content_unverified")
    return h


class MailboxClient(GmailReadClient):
    """Fixed additional draft operations; inherits the bounded, GET-only reader."""

    async def draft_request(self, method, path, *, params=None, payload=None):
        import asyncio

        import httpx

        allowed = (method == "GET" and (path == "drafts" or re.fullmatch(r"drafts/[A-Za-z0-9_-]{1,200}", path))) or (method == "POST" and path == "drafts")
        if not allowed:
            raise ConnectionError("gmail_mailbox_operation_denied")

        async def request(client):
            async with asyncio.timeout(20):
                async with client.stream(method, "https://gmail.googleapis.com/gmail/v1/users/me/" + path,
                        params=params, json=payload, headers={"Authorization": "Bearer " + self.token},
                        timeout=15, follow_redirects=False) as response:
                    if response.status_code not in {200, 201}:
                        raise ConnectionError("gmail_draft_request_unconfirmed" if method == "POST" else "gmail_draft_read_failed")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > 1048576:
                            raise ConnectionError("gmail_draft_response_limit")
                    data = json.loads(body)
                    if not isinstance(data, dict):
                        raise ConnectionError("gmail_draft_response_invalid")
                    return data
        try:
            if self.client:
                return await request(self.client)
            async with httpx.AsyncClient(trust_env=False) as client:
                return await request(client)
        except (httpx.HTTPError, ValueError, TimeoutError):
            raise ConnectionError("gmail_draft_request_unconfirmed" if method == "POST" else "gmail_draft_read_failed") from None


class Mailboxes:
    def __init__(self, session, settings, google=None, client=None):
        self.session, self.settings = session, settings
        self.google, self.client = google or GoogleOAuth(settings), client

    def enabled(self):
        if not self.settings.GMAIL_LOCAL_ACCOUNTS_ENABLED:
            raise ConnectionError("gmail_local_accounts_disabled")
        if not self.settings.GMAIL_LOCAL_ALLOWED_EMAILS:
            raise ConnectionError("gmail_account_allowlist_required")

    def allowed(self, email):
        return email and email.casefold() in {str(value).casefold() for value in self.settings.GMAIL_LOCAL_ALLOWED_EMAILS}

    async def lock(self):
        if self.session.get_bind().dialect.name == "postgresql":
            await self.session.execute(text("SELECT pg_advisory_xact_lock(407054,1)"))

    async def row(self, slot):
        if slot not in {"1", "2"}:
            raise ConnectionError("gmail_account_slot_invalid")
        return await self.session.get(OwnerPreference, ACCOUNT + slot, with_for_update=True, populate_existing=True)

    async def put(self, key, value):
        row = await self.session.get(OwnerPreference, key, with_for_update=True, populate_existing=True)
        if row:
            row.value = value
        else:
            self.session.add(OwnerPreference(key=key, value=value))

    async def status(self, slot):
        row = await self.row(slot)
        v = row.value if row else {}
        if v.get("account_email") and not self.allowed(v["account_email"]):
            return {"slot": slot, "status": "not_authorized", "enabled": False, "permissions": {"send": False, "read": False, "drafts": False}}
        return {k: v.get(k) for k in ("status", "account_email", "generation", "last_verified_at", "last_refresh_at", "expires_at")} | {
            "slot": slot, "status": v.get("status", "not_connected"),
            "enabled": self.settings.GMAIL_LOCAL_ACCOUNTS_ENABLED,
            "scopes": v.get("scopes", []), "drafts_enabled": self.settings.GMAIL_DRAFTS_ENABLED,
            "body_review_enabled": self.settings.GMAIL_READ_BODY_REVIEWED,
            "permissions": {"read": True, "search": True, "drafts": True, "send": False, "delete": False, "monitoring": False},
            "token_health": "reauthorization_required" if v.get("status") == "reauthorization_required" else "expires_soon" if v.get("expires_at", "z") <= (now() + timedelta(seconds=60)).isoformat() else "saved_not_live_checked",
        }

    async def start(self, slot, consent, browser):
        self.enabled()
        if not consent.account_consent or not consent.read_and_draft_consent:
            raise ConnectionError("gmail_read_draft_consent_required")
        if not self.google.configured():
            raise ConnectionError("google_oauth_not_configured")
        store = TokenStore(self.settings)
        await self.lock()
        row = await self.row(slot)
        old = dict(row.value) if row else {}
        if old.get("status") == "connected":
            raise ConnectionError("disconnect_before_reconnecting")
        generation = old.get("generation", 0) + 1
        # A reauthorization must return to the same identity. A deliberate disconnect permits a new one.
        await self.put(ACCOUNT + slot, {**old, "status": "authorizing", "generation": generation})
        state, verifier = "mailbox." + slot + "." + secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        await self.put(INTENT + digest(state)[:32], {
            "state_hash": digest(state), "browser_hash": digest(browser), "slot": slot,
            "generation": generation, "consumed": False,
            "expected_identity": [old.get("google_subject"), old.get("account_email")] if old.get("status") == "reauthorization_required" else None,
            "verifier": store.encrypt(verifier, digest(state)),
            "expires_at": (now() + timedelta(seconds=self.settings.OAUTH_STATE_TTL_SECONDS)).isoformat(),
        })
        await self.session.commit()
        hint = str(self.settings.GMAIL_LOCAL_ALLOWED_EMAILS[0]) if len(self.settings.GMAIL_LOCAL_ALLOWED_EMAILS) == 1 else None
        return {"authorization_url": self.google.authorization_url(state, verifier, hint, read_draft=True), "expires_in": self.settings.OAUTH_STATE_TTL_SECONDS}

    async def callback(self, state, browser, callback_uri, code=None, error=None):
        self.enabled()
        if not browser or callback_uri != self.settings.GMAIL_REDIRECT_URI:
            raise ConnectionError("invalid_oauth_state_or_redirect")
        await self.lock()
        intent = await self.session.get(OwnerPreference, INTENT + digest(state)[:32], with_for_update=True, populate_existing=True)
        value = dict(intent.value) if intent else {}
        if (not intent or value.get("state_hash") != digest(state) or value.get("consumed")
                or value.get("browser_hash") != digest(browser) or value.get("expires_at", "") <= now().isoformat()):
            raise ConnectionError("invalid_expired_or_replayed_state")
        account = await self.row(value["slot"])
        if not account or account.value.get("generation") != value["generation"]:
            raise ConnectionError("connection_intent_superseded")
        verifier = TokenStore(self.settings).decrypt(value.pop("verifier"), digest(state))
        intent.value = {**value, "consumed": True}
        await self.session.commit()
        if error or not code:
            raise ConnectionError("consent_denied")
        from pydantic import ValidationError
        try:
            tokens = TokenResponse.model_validate(await self.google.exchange(code, verifier))
        except ValidationError:
            raise ConnectionError("invalid_token_response") from None
        if not tokens.refresh_token or normalized_scopes(tokens.scope) != READ_DRAFT_SCOPES:
            raise ConnectionError("unexpected_or_insufficient_scopes")
        subject, email = await self.google.identity(tokens.access_token)
        if not self.allowed(email):
            raise ConnectionError("gmail_account_not_authorized")
        if value.get("expected_identity") and value["expected_identity"] != [subject, email]:
            raise ConnectionError("gmail_identity_mismatch")
        await self.lock()
        account = await self.row(value["slot"])
        if not account or account.value.get("generation") != value["generation"]:
            raise ConnectionError("connection_intent_superseded")
        for other_slot in {"1", "2"} - {value["slot"]}:
            other = await self.row(other_slot)
            if other and other.value.get("status") != "disconnected" and (other.value.get("google_subject") == subject or other.value.get("account_email") == email):
                raise ConnectionError("gmail_account_already_connected")
        key = ACCOUNT + value["slot"]
        store = TokenStore(self.settings)
        account.value = {"status": "connected", "generation": value["generation"], "google_subject": subject,
            "account_email": email, "scopes": sorted(READ_DRAFT_SCOPES),
            "access": store.encrypt(tokens.access_token, key + ":access"),
            "refresh": store.encrypt(tokens.refresh_token, key + ":refresh"),
            "expires_at": (now() + timedelta(seconds=tokens.expires_in)).isoformat(), "last_verified_at": now().isoformat()}
        await self.session.commit()
        return await self.status(value["slot"])

    async def fence(self, slot, generation):
        self.enabled()
        await self.lock()
        row = await self.row(slot)
        if not row or row.value.get("status") != "connected" or row.value.get("generation") != generation:
            raise ConnectionError("gmail_account_changed")
        if not self.allowed(row.value.get("account_email")):
            raise ConnectionError("gmail_account_not_authorized")
        return row

    async def check(self, slot, generation):
        await self.fence(slot, generation)
        await self.session.commit()

    async def access(self, slot):
        self.enabled()
        store = TokenStore(self.settings)
        await self.lock()
        row = await self.row(slot)
        if not row or row.value.get("status") != "connected" or set(row.value.get("scopes", [])) != READ_DRAFT_SCOPES:
            raise ConnectionError("gmail_read_draft_account_not_connected")
        value = dict(row.value)
        if not self.allowed(value.get("account_email")):
            raise ConnectionError("gmail_account_not_authorized")
        key = ACCOUNT + slot
        if value["expires_at"] > (now() + timedelta(seconds=60)).isoformat():
            token = store.decrypt(value["access"], key + ":access")
            await self.session.commit()
            return token, value
        if value.get("refresh_lease_until", "") > now().isoformat():
            raise ConnectionError("gmail_refresh_in_progress")
        # An expired lease is not part of the account baseline. Restoring it after
        # a newer refresh would let the former lease owner overwrite that result.
        value.pop("refresh_lease", None)
        value.pop("refresh_lease_until", None)
        lease = uuid4().hex
        row.value = {**value, "refresh_lease": lease, "refresh_lease_until": (now() + timedelta(seconds=70)).isoformat()}
        refresh = store.decrypt(value["refresh"], key + ":refresh")
        await self.session.commit()
        from pydantic import ValidationError
        try:
            tokens = TokenResponse.model_validate(await self.google.refresh(refresh))
            if (normalized_scopes(tokens.scope) if tokens.scope else set(value["scopes"])) != READ_DRAFT_SCOPES:
                raise ConnectionError("gmail_scope_changed")
            if await self.google.identity(tokens.access_token) != (value["google_subject"], value["account_email"]):
                raise ConnectionError("gmail_identity_mismatch")
        except (ConnectionError, ValidationError) as exc:
            invalid = isinstance(exc, ValidationError) or str(exc) in {"credential_revoked_or_code_invalid", "gmail_scope_changed", "gmail_identity_mismatch", "identity_verification_failed"}
            row = await self.fence(slot, value["generation"])
            if row.value.get("refresh_lease") == lease:
                row.value = {**value, **({"status": "reauthorization_required", "access": None} if invalid else {})}
            await self.session.commit()
            raise ConnectionError("gmail_reauthorization_required" if invalid else "gmail_refresh_unavailable") from None
        row = await self.fence(slot, value["generation"])
        if row.value.get("refresh_lease") != lease:
            raise ConnectionError("gmail_refresh_superseded")
        row.value = {**value, "access": store.encrypt(tokens.access_token, key + ":access"),
            "refresh": store.encrypt(tokens.refresh_token or refresh, key + ":refresh"),
            "last_refresh_at": now().isoformat(), "last_verified_at": now().isoformat(),
            "expires_at": (now() + timedelta(seconds=tokens.expires_in)).isoformat()}
        await self.session.commit()
        return tokens.access_token, dict(row.value)

    async def verify(self, slot):
        token, value = await self.access(slot)
        if await self.google.identity(token) != (value["google_subject"], value["account_email"]):
            row = await self.fence(slot, value["generation"])
            row.value = {**row.value, "status": "reauthorization_required", "access": None}
            await self.session.commit()
            raise ConnectionError("gmail_identity_mismatch")
        row = await self.fence(slot, value["generation"])
        row.value = {**row.value, "last_verified_at": now().isoformat()}
        await self.session.commit()
        return await self.status(slot)

    async def disconnect(self, slot):
        await self.lock()
        row = await self.row(slot)
        old = dict(row.value) if row else {}
        await self.put(ACCOUNT + slot, {"status": "disconnected", "generation": old.get("generation", 0) + 1})
        await self.session.commit()
        revocation = "not_needed"
        if old.get("refresh"):
            try:
                refresh = TokenStore(self.settings).decrypt(old["refresh"], ACCOUNT + slot + ":refresh")
                await self.google.revoke(refresh)
                revocation = "confirmed"
            except ConnectionError:
                revocation = "manual_revocation_required"
        return {"status": "disconnected", "revocation": revocation, "sending_enabled": False}

    async def search(self, slot, data):
        token, account = await self.access(slot)
        client = MailboxClient(token, self.client)
        page = await client.messages(labels=["INBOX"], query=data.query, limit=data.limit)
        await self.check(slot, account["generation"])
        output = []
        for item in page.get("messages", [])[:data.limit]:
            message_id = item.get("id") if isinstance(item, dict) else None
            if not isinstance(message_id, str) or not IDENTIFIER.fullmatch(message_id):
                raise ConnectionError("gmail_message_id_invalid")
            message = await client.message(message_id)
            await self.fence(slot, account["generation"])
            if message.get("id") != message_id or "INBOX" not in message.get("labelIds", []):
                raise ConnectionError("gmail_message_selection_changed")
            key = SELECTION + digest(slot + ":" + str(account["generation"]) + ":" + message_id)[:32]
            await self.put(key, {"slot": slot, "generation": account["generation"], "message_id": message_id,
                "expires_at": (now() + timedelta(minutes=15)).isoformat()})
            await self.session.commit()
            output.append({"id": message_id, **headers(message)})
        return {"slot": slot, "generation": account["generation"], "messages": output, "bounded": True, "monitoring": False}

    async def read(self, slot, message_id):
        if not self.settings.GMAIL_READ_BODY_REVIEWED:
            raise ConnectionError("gmail_body_access_review_required")
        token, account = await self.access(slot)
        if not IDENTIFIER.fullmatch(message_id):
            raise ConnectionError("gmail_message_id_invalid")
        key = SELECTION + digest(slot + ":" + str(account["generation"]) + ":" + message_id)[:32]
        selected = await self.session.get(OwnerPreference, key)
        if not selected or selected.value.get("expires_at", "") <= now().isoformat():
            raise ConnectionError("gmail_recent_inbox_selection_required")
        await self.session.commit()
        message = await MailboxClient(token, self.client).message(message_id, body=True)
        await self.check(slot, account["generation"])
        if message.get("id") != message_id or "INBOX" not in message.get("labelIds", []):
            raise ConnectionError("gmail_message_selection_changed")
        parsed = content_evidence(message.get("payload", {}))
        sender = parseaddr(headers(message).get("from", ""))[1].casefold()
        return {"slot": slot, "id": message_id, "headers": headers(message), "parsing": parsed,
            "origin": {"sender_domain_is_naukri": sender.endswith("@naukri.com"), "authenticated_origin_verified": False},
            "body_stored": False, "links_opened": False, "submission_confirmed": False}

    async def drafts(self, slot):
        token, account = await self.access(slot)
        result = await MailboxClient(token, self.client).draft_request("GET", "drafts", params={"maxResults": 10})
        await self.check(slot, account["generation"])
        return {"drafts": result.get("drafts", [])[:10], "has_more": bool(result.get("nextPageToken")), "sending_enabled": False}

    async def create_draft(self, slot, data):
        if not self.settings.GMAIL_DRAFTS_ENABLED:
            raise ConnectionError("gmail_drafts_disabled")
        if not data.owner_reviewed or data.content_hash != draft_hash(data.recipient, data.subject, data.body):
            raise ConnectionError("gmail_exact_draft_review_required")
        await self.check(slot, data.expected_generation)
        token, account = await self.access(slot)
        await self.fence(slot, data.expected_generation)
        key = "gm54_draft:" + digest(account["google_subject"] + ":" + str(data.request_id))[:32]
        row = await self.session.get(OwnerPreference, key, with_for_update=True, populate_existing=True)
        value = dict(row.value) if row else {}
        if value and value["content_hash"] != data.content_hash:
            raise ConnectionError("gmail_draft_request_conflict")
        client = MailboxClient(token, self.client)
        if value:
            await self.session.commit()
            if not value.get("draft_id"):
                found = await client.draft_request("GET", "drafts", params={"q": "rfc822msgid:" + value["message_id"], "maxResults": 5})
                await self.check(slot, account["generation"])
                if len(found.get("drafts", [])) != 1:
                    raise ConnectionError("gmail_draft_outcome_unknown_inspect_gmail")
                value["draft_id"] = found["drafts"][0].get("id")
        else:
            value = {"content_hash": data.content_hash, "message_id": "phase54." + uuid4().hex + "@automated-apply.invalid", "status": "dispatching"}
            await self.put(key, value)
            await self.session.commit()
            await self.check(slot, account["generation"])
            message = EmailMessage()
            message["From"], message["To"], message["Subject"] = account["account_email"], str(data.recipient), data.subject
            message["Message-ID"] = "<" + value["message_id"] + ">"
            message.set_content(data.body)
            result = await client.draft_request("POST", "drafts", payload={"message": {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}})
            value["draft_id"] = result.get("id")
            await self.fence(slot, account["generation"])
            await self.put(key, value)
            await self.session.commit()
        if not isinstance(value.get("draft_id"), str) or not IDENTIFIER.fullmatch(value["draft_id"]):
            raise ConnectionError("gmail_draft_request_unconfirmed")
        draft = await client.draft_request("GET", "drafts/" + value["draft_id"], params={"format": "full"})
        await self.fence(slot, account["generation"])
        message = draft.get("message", {})
        if draft.get("id") != value["draft_id"]:
            raise ConnectionError("gmail_draft_content_unverified")
        verified_draft_content(message, account["account_email"], data.recipient, data.subject, data.body)
        value.update(status="verified", verified_at=now().isoformat())
        await self.put(key, value)
        await self.session.commit()
        return {"draft_id": value["draft_id"], "draft_exists": True, "content_verified": True, "sending_enabled": False}

    async def self_test_draft(self, slot, expected_generation):
        if not self.settings.GMAIL_DRAFTS_ENABLED:
            raise ConnectionError("gmail_drafts_disabled")
        await self.check(slot, expected_generation)
        token, account = await self.access(slot)
        await self.fence(slot, expected_generation)
        key = TEST + digest(account["google_subject"] + ":draft-acceptance-v1")[:32]
        record = await self.session.get(OwnerPreference, key, with_for_update=True, populate_existing=True)
        value = dict(record.value) if record else {}
        client = MailboxClient(token, self.client)
        if value.get("draft_id"):
            await self.session.commit()
            return await self.confirm_test(slot, token, account, key, value)
        if value:
            await self.session.commit()
            # A prior dispatch could have succeeded. Reconcile only, never POST again.
            found = await client.draft_request("GET", "drafts", params={"q": "rfc822msgid:" + value["message_id"], "maxResults": 5})
            await self.check(slot, account["generation"])
            candidates = found.get("drafts", [])
            if len(candidates) != 1 or not IDENTIFIER.fullmatch(str(candidates[0].get("id", ""))):
                raise ConnectionError("gmail_test_draft_outcome_unknown_inspect_gmail")
            value = {**value, "draft_id": candidates[0]["id"]}
            return await self.confirm_test(slot, token, account, key, value)
        marker = "phase54." + uuid4().hex + "@automated-apply.invalid"
        value = {"slot": slot, "account_subject_hash": digest(account["google_subject"]), "status": "dispatching",
            "message_id": marker, "started_at": now().isoformat()}
        await self.put(key, value)
        # Commit before the one mailbox write; no network request while holding a database lock.
        await self.session.commit()
        await self.check(slot, account["generation"])
        message = EmailMessage()
        message["From"] = message["To"] = account["account_email"]
        message["Subject"] = TEST_SUBJECT
        message["Message-ID"] = "<" + marker + ">"
        message.set_content(TEST_BODY)
        try:
            result = await client.draft_request("POST", "drafts", payload={"message": {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}})
            if not isinstance(result.get("id"), str) or not IDENTIFIER.fullmatch(result["id"]):
                raise ConnectionError("gmail_draft_request_unconfirmed")
            value = {**value, "draft_id": result["id"], "status": "created"}
            await self.fence(slot, account["generation"])
            await self.put(key, value)
            await self.session.commit()
            return await self.confirm_test(slot, token, account, key, value)
        except ConnectionError:
            # Keep the durable fence even if disconnect won the race. Do not erase a receipt.
            await self.session.rollback()
            raise

    async def confirm_test(self, slot, token, account, key, value):
        client = MailboxClient(token, self.client)
        await self.check(slot, account["generation"])
        draft = await client.draft_request("GET", "drafts/" + value["draft_id"], params={"format": "full"})
        await self.check(slot, account["generation"])
        message = draft.get("message", {})
        if draft.get("id") != value["draft_id"]:
            raise ConnectionError("gmail_test_draft_verification_failed")
        h = verified_draft_content(message, account["account_email"], account["account_email"], TEST_SUBJECT, TEST_BODY)
        provider_id = re.fullmatch(r"<([A-Za-z0-9._+=/-]{1,200}@[A-Za-z0-9.-]{1,200})>", h.get("message-id", ""))
        if not provider_id:
            raise ConnectionError("gmail_test_draft_verification_failed")
        for marker in sorted({value["message_id"], provider_id[1]}):
            sent = await client.messages(labels=["SENT"], query="rfc822msgid:" + marker, limit=1)
            await self.check(slot, account["generation"])
            if sent.get("messages"):
                raise ConnectionError("gmail_test_message_found_in_sent")
        await self.fence(slot, account["generation"])
        receipt = {**value, "status": "verified", "verified_at": now().isoformat(), "draft_exists": True,
            "provider_message_id": provider_id[1], "content_verified": True,
            "sent_search_empty": True, "sending_enabled": False}
        await self.put(key, receipt)
        await self.session.commit()
        return {k: receipt[k] for k in ["status", "draft_id", "verified_at", "draft_exists", "sent_search_empty", "sending_enabled"]}
