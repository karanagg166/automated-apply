"""MailDraftService: one idempotent Gmail draft per application, IMAP first with an
automatic silent Mail.app fallback. STRICTLY READ + DRAFT ONLY.

Idempotency (public.email_drafts UNIQUE(application_id)):
  1. reserve a PENDING row atomically before touching IMAP/Mail.app; an existing
     PENDING or CREATED row means "already drafted" -> skip;
  2. on success the row becomes CREATED and applications.draft_created_at is set in the
     same transaction;
  3. a definite failure (unconfigured, login refused, APPEND rejected) marks it FAILED so
     a later quota hit may try again; an ambiguous one (connection lost mid-APPEND) stays
     PENDING and is never retried or sent to the fallback channel, so no duplicate draft.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from backend.app.browser_v2.store import ApplicationRecord, EmailDraftRecord, Store
from backend.app.mail_v2.config import MailConfig
from backend.app.mail_v2.imap_drafts import ImapDraftClient, ImapDraftError
from backend.app.mail_v2.mail_app_drafts import MailAppDraftClient, MailAppDraftError
from backend.app.mail_v2.message import (
    TEST_SUBJECT_PREFIX,
    DraftContent,
    DraftValidationError,
    build_draft_message,
    resume_attachment,
    valid_recipient,
)

logger = logging.getLogger(__name__)


@dataclass
class DraftOutcome:
    created: bool
    already_drafted: bool = False
    channel: str | None = None
    fell_back: bool = False
    error: str | None = None
    ambiguous: bool = False
    attachment: str | None = None  # attached | skipped:<reason> | None
    draft: EmailDraftRecord | None = None
    external_draft_id: str | None = None

    def public(self) -> dict[str, Any]:
        return {"created": self.created, "already_drafted": self.already_drafted, "channel": self.channel,
                "fell_back": self.fell_back, "error": self.error, "ambiguous": self.ambiguous,
                "attachment": self.attachment, "draft": self.draft.public() if self.draft else None}


class MailDraftService:
    def __init__(self, store: Store, config: MailConfig, *, imap: ImapDraftClient | None = None,
                 mail_app: MailAppDraftClient | None = None) -> None:
        self.store = store
        self.config = config
        self.imap = imap or ImapDraftClient(config)
        self.mail_app = mail_app or MailAppDraftClient(config)

    @property
    def enabled(self) -> bool:
        return not self.config.disabled and self.config.active_channel() != "unconfigured"

    def status(self) -> dict[str, Any]:
        return self.config.public()

    async def already_drafted(self, record: ApplicationRecord) -> bool:
        if record.draft_created_at is not None:
            return True
        draft = await self.store.get_email_draft(record.id)
        return draft is not None and draft.status in ("CREATED", "PENDING")

    async def create_application_draft(self, record: ApplicationRecord, recipient: str, content: DraftContent, *,
                                       sender_name: str | None = None,
                                       enrichment_source: str | None = None,
                                       attachment_path: str | None = None) -> DraftOutcome:
        try:
            to = valid_recipient(recipient)
        except DraftValidationError as exc:
            return DraftOutcome(created=False, error=str(exc))
        if record.draft_created_at is not None:
            return DraftOutcome(created=False, already_drafted=True,
                                draft=await self.store.get_email_draft(record.id))
        if not self.enabled:
            return DraftOutcome(created=False, error="mail_unconfigured")
        reservation = await self.store.reserve_email_draft(record.id, record.platform, to)
        if not reservation.reserved:
            return DraftOutcome(created=False, already_drafted=True, draft=reservation.draft)
        assert reservation.draft is not None
        draft_id = reservation.draft.id
        outcome = await self._deliver(content, to, sender_name=sender_name, application_id=record.id,
                                      attachment_path=attachment_path)
        if outcome.created and outcome.channel:
            outcome.draft = await self.store.complete_email_draft(
                draft_id, channel=outcome.channel, subject=content.subject, body_preview=content.body,
                composer=content.composer, enrichment_source=enrichment_source,
                external_draft_id=outcome.external_draft_id)
        else:
            await self.store.fail_email_draft(draft_id, outcome.error or "draft_failed", ambiguous=outcome.ambiguous)
            outcome.draft = await self.store.get_email_draft(record.id)
        return outcome

    async def save_test_draft(self, recipient: str, content: DraftContent, *,
                              sender_name: str | None = None) -> DraftOutcome:
        """`test-draft` CLI: one clearly marked draft, not linked to any application."""
        try:
            to = valid_recipient(recipient)
        except DraftValidationError as exc:
            return DraftOutcome(created=False, error=str(exc))
        if not self.enabled:
            return DraftOutcome(created=False, error="mail_unconfigured")
        subject = content.subject if content.subject.startswith(TEST_SUBJECT_PREFIX) \
            else TEST_SUBJECT_PREFIX + content.subject
        marked = DraftContent(subject, content.body, content.composer, content.provider)
        return await self._deliver(marked, to, sender_name=sender_name, application_id=None)

    async def _deliver(self, content: DraftContent, to: str, *, sender_name: str | None,
                       application_id: str | None, attachment_path: str | None = None) -> DraftOutcome:
        attachment, skipped = resume_attachment(attachment_path or self.config.resume_path)
        note = "attached" if attachment else (f"skipped:{skipped}" if skipped else None)
        mode = self.config.channel
        imap_error: str | None = None
        if mode in ("auto", "imap") and self.imap.configured:
            try:
                message = build_draft_message(content, recipient=to, sender_email=self.config.imap_email,
                                              sender_name=sender_name, application_id=application_id,
                                              attachment=attachment)
                receipt = await self.imap.append_draft(message)
                return DraftOutcome(created=True, channel="imap", attachment=note,
                                    external_draft_id=receipt.message_id)
            except DraftValidationError as exc:
                return DraftOutcome(created=False, error=str(exc))
            except ImapDraftError as exc:
                logger.warning("imap draft failed: %s (ambiguous=%s)", exc.code, exc.ambiguous)
                if exc.ambiguous:  # APPEND may have landed: never retry or fall back (no duplicates)
                    return DraftOutcome(created=False, channel="imap", error=exc.code, ambiguous=True)
                imap_error = exc.code
        elif mode == "imap":
            return DraftOutcome(created=False, error="imap_unconfigured")
        if mode in ("auto", "mail_app") and self.mail_app.available:
            try:
                saved = await self.mail_app.save_draft(recipient=to, subject=content.subject, body=content.body,
                                                       attachment=attachment)
            except MailAppDraftError as exc:
                return DraftOutcome(created=False, channel="mail_app", error=exc.code, ambiguous=exc.ambiguous,
                                    fell_back=imap_error is not None)
            if attachment is not None and not saved.attached:
                note = "skipped:mail_app_attachment_failed"
            return DraftOutcome(created=True, channel="mail_app", fell_back=imap_error is not None,
                                attachment=note, external_draft_id=saved.draft_id)
        return DraftOutcome(created=False, error=imap_error or "mail_unconfigured")

    # --- read-only diagnostics -------------------------------------------------------------
    async def probe(self, *, mail_app: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {"config": self.status()}
        if self.imap.configured:
            result["imap"] = await self.imap.check_connection()
        if mail_app:
            result["mail_app"] = await self.mail_app.probe()
        return result
