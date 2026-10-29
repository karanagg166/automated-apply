"""Optional explicit Mail account allowlist, separate reads/drafts, no database scraping."""

import asyncio
import base64
import hashlib
import json
import sys
from datetime import datetime, timedelta
from email.utils import parseaddr
from pathlib import Path
from uuid import UUID

from pydantic import EmailStr, Field, StrictBool

from backend.app.ai.schemas import Contract
from backend.app.dashboard.models import OwnerPreference
from backend.app.integrations.gmail.read_client import content_evidence
from backend.app.integrations.token_store import ConnectionError
from backend.app.models.discovery import now


class AccountPolicy(Contract):
    address: EmailStr
    inbox_mailbox: str = Field(min_length=1, max_length=128)
    drafts_mailbox: str = Field(min_length=1, max_length=128)
    sent_mailbox: str | None = Field(default=None, min_length=1, max_length=128)
    read_authorized: StrictBool = False
    draft_authorized: StrictBool = False
    senders: list[EmailStr] = Field(default_factory=list, max_length=10)
    maximum_age_days: int = Field(default=7, ge=1, le=30)


class Draft(Contract):
    request_id: UUID
    recipient: EmailStr
    subject: str = Field(min_length=1, max_length=180, pattern=r"^[^\x00-\x1f\x7f]+$")
    body: str = Field(min_length=1, max_length=10000)
    owner_reviewed: StrictBool


async def scripting(request):
    if sys.platform != "darwin":
        raise ConnectionError("apple_mail_macos_required")
    child = await asyncio.create_subprocess_exec("/usr/bin/osascript", "-l", "JavaScript",
        str(Path(__file__).with_suffix(".js")), json.dumps(request),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        output, _ = await asyncio.wait_for(child.communicate(), 35)
    except TimeoutError:
        child.kill()
        await child.communicate()
        raise ConnectionError("apple_mail_operation_unconfirmed") from None
    if child.returncode or len(output) > 1048576:
        raise ConnectionError("apple_mail_scripting_unavailable")
    try:
        result = json.loads(output)
    except ValueError:
        raise ConnectionError("apple_mail_invalid_response") from None
    if not isinstance(result, dict):
        raise ConnectionError("apple_mail_invalid_response")
    if result.get("error"):
        if result.get("apple_event_code") == -1743:
            raise ConnectionError("apple_mail_automation_permission_required")
        raise ConnectionError("apple_mail_not_ready")
    return result


class AppleMail:
    def __init__(self, session, settings, runner=scripting):
        self.session, self.settings, self.runner = session, settings, runner

    def policy(self, account_id, *, read=False, draft=False):
        if not self.settings.APPLE_MAIL_ENABLED:
            raise ConnectionError("apple_mail_disabled")
        data = self.settings.APPLE_MAIL_ACCOUNT_POLICIES.get(account_id)
        if not data:
            raise ConnectionError("apple_mail_account_not_allowed")
        policy = AccountPolicy.model_validate(data)
        if read and (not policy.read_authorized or not policy.senders):
            raise ConnectionError("apple_mail_read_authorization_required")
        if draft and not policy.draft_authorized:
            raise ConnectionError("apple_mail_draft_authorization_required")
        return policy

    async def accounts(self):
        if not self.settings.APPLE_MAIL_ENABLED:
            return {"enabled": False, "accounts": [], "sending_enabled": False}
        result = await self.runner({"action": "accounts", "allowed_ids": list(self.settings.APPLE_MAIL_ACCOUNT_POLICIES)})
        approved = []
        for account in result.get("accounts", []):
            if account.get("id") not in self.settings.APPLE_MAIL_ACCOUNT_POLICIES:
                continue
            policy = self.policy(account["id"])
            if str(policy.address).casefold() in {a.casefold() for a in account.get("addresses", [])}:
                approved.append({"id": account["id"], "name": account["name"], "address": str(policy.address),
                    "read_authorized": policy.read_authorized, "draft_authorized": policy.draft_authorized})
        return {"enabled": True, "accounts": approved, "sending_enabled": False}

    def request(self, account_id, policy, action, **extra):
        return {"action": action, "account_id": account_id, "address": str(policy.address),
            "mailbox": policy.inbox_mailbox, "senders": [str(s) for s in policy.senders],
            "since": (now() - timedelta(days=policy.maximum_age_days)).isoformat(), **extra}

    def selected_key(self, account_id, message_id):
        return "mail_selected:" + hashlib.sha256((account_id + ":" + str(message_id)).encode()).hexdigest()[:32]

    async def search(self, account_id):
        policy = self.policy(account_id, read=True)
        data = await self.runner(self.request(account_id, policy, "search", limit=5))
        output = []
        for message in data.get("messages", [])[:5]:
            if type(message.get("id")) is not int or message["id"] < 0:
                raise ConnectionError("apple_mail_invalid_message")
            sender = parseaddr(message.get("sender", ""))[1].casefold()
            if sender not in {str(s).casefold() for s in policy.senders}:
                continue
            key = self.selected_key(account_id, message["id"])
            value = {"expires_at": (now() + timedelta(minutes=15)).isoformat(), "policy_digest": hashlib.sha256(policy.model_dump_json().encode()).hexdigest()}
            row = await self.session.get(OwnerPreference, key)
            if row:
                row.value = value
            else:
                self.session.add(OwnerPreference(key=key, value=value))
            output.append(message)
        await self.session.commit()
        return {"messages": output, "bounded": True, "bodies_read": False, "monitoring": False}

    async def read(self, account_id, message_id):
        policy = self.policy(account_id, read=True)
        row = await self.session.get(OwnerPreference, self.selected_key(account_id, message_id))
        if not row or row.value["expires_at"] <= now().isoformat() or row.value["policy_digest"] != hashlib.sha256(policy.model_dump_json().encode()).hexdigest():
            raise ConnectionError("apple_mail_recent_selection_required")
        await self.session.commit()
        result = await self.runner(self.request(account_id, policy, "read", message_id=message_id))
        sender = parseaddr(result.get("sender", ""))[1].casefold()
        if (result.get("id") != message_id or sender not in {str(s).casefold() for s in policy.senders}
                or datetime.fromisoformat(result["received_at"].replace("Z", "+00:00")) < now() - timedelta(days=policy.maximum_age_days)):
            raise ConnectionError("apple_mail_message_outside_scope")
        body = result.pop("body", "")
        if not isinstance(body, str) or len(body.encode()) > 262144:
            raise ConnectionError("apple_mail_body_limit")
        parsed = content_evidence({"mimeType": "text/plain", "body": {"data": base64.urlsafe_b64encode(body.encode()).decode()}})
        from backend.app.execution.naukri import normalized_url
        candidates = []
        for link in parsed["links"]:
            try:
                canonical = normalized_url(link)
                if canonical not in candidates:
                    candidates.append(canonical)
            except ValueError:
                continue
        return {**result, "parsing": parsed, "naukri_candidates": candidates,
            "origin_authenticated": False, "body_stored": False, "links_opened": False, "submission_confirmed": False}

    async def draft(self, account_id, data):
        policy = self.policy(account_id, draft=True)
        if not data.owner_reviewed:
            raise ConnectionError("apple_mail_draft_review_required")
        key = "mail_draft:" + data.request_id.hex
        content_hash = hashlib.sha256((account_id + data.model_dump_json()).encode()).hexdigest()
        row = await self.session.get(OwnerPreference, key, with_for_update=True, populate_existing=True)
        if row and row.value["content_hash"] != content_hash:
            raise ConnectionError("apple_mail_draft_request_conflict")
        subject = data.subject + " [AA:" + data.request_id.hex[:12] + "]"
        request = self.request(account_id, policy, "verify_draft" if row else "draft", mailbox=policy.drafts_mailbox,
            subject=subject, body=data.body, recipient=str(data.recipient), sent_mailbox=policy.sent_mailbox)
        if not row:
            row = OwnerPreference(key=key, value={"state": "dispatching", "content_hash": content_hash, "account_id": account_id})
            self.session.add(row)
        # A crash/timeout never causes another make/save operation on retry.
        await self.session.commit()
        result = await self.runner(request)
        if not result.get("draft_verified"):
            result = await self.runner({**request, "action": "verify_draft"})
        if (result.get("draft_verified") is not True or result.get("sent") is not False
                or result.get("subject") != subject or result.get("recipients") != [str(data.recipient)]
                or parseaddr(result.get("sender", ""))[1].casefold() != str(policy.address).casefold()
                or (policy.sent_mailbox and result.get("sent_search_empty") is not True)):
            raise ConnectionError("apple_mail_draft_unconfirmed")
        row = await self.session.get(OwnerPreference, key, with_for_update=True, populate_existing=True)
        row.value = {**row.value, "state": "verified", "draft_id": result["id"], "verified_at": now().isoformat()}
        await self.session.commit()
        return {"draft_id": result["id"], "draft_verified": True, "sent_search_empty": result.get("sent_search_empty"), "sending_enabled": False, "account_id": account_id}
