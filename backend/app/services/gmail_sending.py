"""Owner-confirmed sends only. Durable reservation precedes every external side effect.

One attempt per draft, even for definite failures. No retry or worker dispatch entry point.
PostgreSQL serializes caps/claims; row locks hold eligibility stable during the HTTP call.
"""

import secrets
import uuid
from datetime import timedelta, timezone

from sqlalchemy import exists, func, literal, or_, select, text, update
from sqlalchemy.exc import SQLAlchemyError

from backend.app.core.config import get_settings
from backend.app.integrations.connection_service import ConnectionService, digest
from backend.app.integrations.gmail.mime import message_id, serialize
from backend.app.integrations.gmail.schemas import SendFailure
from backend.app.integrations.gmail.send_client import GmailSendClient
from backend.app.integrations.google_oauth import SEND_SCOPES
from backend.app.integrations.token_store import ConnectionError, TokenStore
from backend.app.models.discovery import now
from backend.app.models.outreach import OutreachLog
from backend.app.models.outreach_send import OutreachSendAttempt, SendConfirmation
from backend.app.services.outreach_drafting import (
    DraftConflict,
    OutreachDraftingService,
    fingerprint,
)


class SendBlocked(DraftConflict):
    def __init__(self, blockers):
        self.blockers = sorted(set(blockers))
        super().__init__("send_blocked:" + ",".join(self.blockers))


def sender_binding(account):
    return fingerprint(
        [
            str(account.id),
            account.google_subject,
            account.account_email,
            account.connected_at.replace(tzinfo=timezone.utc).isoformat(),
        ]
    )


def attempt_output(attempt):
    return {
        key: getattr(attempt, key)
        for key in (
            "id",
            "draft_id",
            "connected_account_id",
            "draft_revision",
            "approval_hash",
            "actor_id",
            "recipient_email",
            "sender_email",
            "subject",
            "body",
            "content_digest",
            "evidence_digest",
            "rfc_message_id",
            "status",
            "gmail_message_id",
            "gmail_thread_id",
            "created_at",
            "attempted_at",
            "accepted_at",
            "failure_category",
            "reconciliation_required",
            "reconciled_at",
            "reconciled_by",
            "reconciliation_note",
        )
    }


class GmailSendingService:
    def __init__(self, session, settings=None, connection=None, client=None):
        self.session, self.settings = session, settings or get_settings()
        self.connection = connection or ConnectionService(session, self.settings)
        self.drafts = OutreachDraftingService(session, self.settings)
        self.client = client or GmailSendClient(
            timeout=self.settings.GMAIL_SEND_TIMEOUT_SECONDS
        )

    def enabled(self):
        if not self.settings.GMAIL_SENDING_ENABLED:
            raise DraftConflict("gmail_sending_disabled")
        if (
            self.session.get_bind().dialect.name != "postgresql"
            and self.settings.ENVIRONMENT != "testing"
        ):
            raise DraftConflict("postgresql_required_for_sending")

    async def lock(self):
        # Same ordering everywhere: OAuth connection lock, then global cap/claim lock.
        await self.connection.lock()
        if self.session.get_bind().dialect.name == "postgresql":
            await self.session.execute(text("SELECT pg_advisory_xact_lock(407007, 1)"))

    async def validate(self, draft_id, actor):
        self.enabled()
        if actor != "owner":
            raise DraftConflict("authenticated_owner_required")
        account = await self.connection.account(lock=True)
        if not account or account.status != "connected":
            raise DraftConflict("gmail_reauthorization_required")
        if set(account.granted_scopes) != SEND_SCOPES:
            raise DraftConflict("gmail_send_authorization_required")
        draft = await self.drafts.get(draft_id, lock=True)
        eligibility = await self.drafts.eligibility(draft, lock=True)
        blockers = list(eligibility["blockers"])
        if not eligibility["email_send_ready"]:
            blockers.append("verified_mailbox_and_current_evidence_required")
        if not eligibility["approval_current"]:
            blockers.append("current_revision_approval_required")
        if draft.connected_account_id and draft.connected_account_id != account.id:
            blockers.append("sender_account_changed")
        if draft.sent_at or draft.gmail_message_id or draft.approval_status == "sent":
            blockers.append("draft_already_sent")
        if blockers:
            raise SendBlocked(blockers)
        return draft, account

    def binding(self, draft, account, actor):
        return dict(
            draft_id=draft.id,
            connected_account_id=account.id,
            actor_id=actor,
            draft_revision=draft.draft_revision,
            approval_hash=draft.approval_hash,
            sender_email=account.account_email,
            sender_binding=sender_binding(account),
            recipient_email=draft.recipient_email,
            content_digest=fingerprint([draft.subject, draft.body]),
            evidence_digest=draft.evidence_hash,
        )

    async def limits(self):
        # Rolling windows in UTC; all reservations (including unknown and failed) count.
        for hours, maximum, code in (
            (1, self.settings.GMAIL_SEND_MAX_PER_HOUR, "hourly_send_limit"),
            (24, self.settings.GMAIL_SEND_MAX_PER_DAY, "daily_send_limit"),
        ):
            count = await self.session.scalar(
                select(func.count())
                .select_from(OutreachSendAttempt)
                .where(OutreachSendAttempt.created_at >= now() - timedelta(hours=hours))
            )
            if count >= maximum:
                raise DraftConflict(code)

    async def preview(self, draft_id, *, actor="owner"):
        await self.lock()
        draft, account = await self.validate(draft_id, actor)
        if await self.session.scalar(
            select(OutreachSendAttempt.id).where(
                OutreachSendAttempt.draft_id == draft_id
            )
        ):
            raise DraftConflict("send_attempt_already_reserved")
        await self.limits()
        token, created = secrets.token_urlsafe(32), now()
        expires = created + timedelta(
            seconds=self.settings.GMAIL_CONFIRMATION_TTL_SECONDS
        )
        # Validate MIME before creating consent; preview never obtains a token or calls Gmail.
        serialize(
            sender=account.account_email,
            recipient=draft.recipient_email,
            subject=draft.subject,
            body=draft.body,
            rfc_message_id=message_id(uuid.uuid4()),
            created_at=created,
        )
        self.session.add(
            SendConfirmation(
                token_hash=digest(token),
                **self.binding(draft, account, actor),
                created_at=created,
                expires_at=expires,
            )
        )
        result = dict(
            draft_id=draft.id,
            draft_revision=draft.draft_revision,
            approval_hash=draft.approval_hash,
            sender_account_id=account.id,
            sender=account.account_email,
            recipient=draft.recipient_email,
            subject=draft.subject,
            body=draft.body,
            approval_current=True,
            eligible_to_send=True,
            send_confirmation_required=True,
            confirmation_token=token,
            confirmation_expires_at=expires,
        )
        await self.session.commit()
        return result

    async def existing(self, draft_id, request):
        attempt = await self.session.scalar(
            select(OutreachSendAttempt)
            .execution_options(populate_existing=True)
            .where(
                or_(
                    OutreachSendAttempt.draft_id == draft_id,
                    OutreachSendAttempt.idempotency_key == request.idempotency_key,
                )
            )
        )
        if attempt:
            request_hash = fingerprint(request.model_dump(mode="json"))
            if attempt.draft_id != draft_id or attempt.request_hash != request_hash:
                raise DraftConflict("draft_or_idempotency_key_already_reserved")
        return attempt

    async def send(self, draft_id, request, *, actor="owner"):
        # Idempotent reads remain possible after disabling/disconnecting, without provider calls.
        if actor != "owner":
            raise DraftConflict("authenticated_owner_required")
        await self.lock()
        prior = await self.existing(draft_id, request)
        if prior:
            await self.session.commit()
            return await self.status(prior.id)
        self.enabled()
        await self.session.rollback()
        try:
            token = await self.connection.access_token()
        except ConnectionError as exc:
            raise DraftConflict(str(exc)) from None
        await self.lock()
        prior = await self.existing(draft_id, request)
        if prior:
            await self.session.commit()
            return await self.status(prior.id)
        draft, account = await self.validate(draft_id, actor)
        binding = self.binding(draft, account, actor)
        if (
            request.expected_revision != draft.draft_revision
            or request.approval_hash != draft.approval_hash
            or request.sender_account_id != account.id
        ):
            raise DraftConflict("send_context_changed")
        challenge = await self.session.scalar(
            select(SendConfirmation)
            .execution_options(populate_existing=True)
            .where(SendConfirmation.token_hash == digest(request.confirmation_token))
            .with_for_update()
        )
        if (
            not challenge
            or challenge.consumed_at is not None
            or challenge.expires_at.replace(tzinfo=timezone.utc) <= now()
            or any(getattr(challenge, key) != value for key, value in binding.items())
        ):
            raise DraftConflict("invalid_expired_or_used_confirmation")
        await self.limits()
        key, created = uuid.uuid4(), now()
        raw = serialize(
            sender=account.account_email,
            recipient=draft.recipient_email,
            subject=draft.subject,
            body=draft.body,
            rfc_message_id=message_id(key),
            created_at=created,
        )
        challenge.consumed_at = created
        await (
            self.session.flush()
        )  # Consent consumption and reservation still commit atomically.
        attempt = OutreachSendAttempt(
            id=key,
            **binding,
            confirmation_hash=challenge.token_hash,
            subject=draft.subject,
            body=draft.body,
            rfc_message_id=message_id(key),
            idempotency_key=request.idempotency_key,
            request_hash=fingerprint(request.model_dump(mode="json")),
            status="prepared",
            created_at=created,
            updated_at=created,
        )
        self.session.add(attempt)
        await (
            self.session.commit()
        )  # Durable reservation BEFORE dispatch, including across process death.
        await self.lock()
        attempt = await self.session.scalar(
            select(OutreachSendAttempt)
            .execution_options(populate_existing=True)
            .where(OutreachSendAttempt.id == key)
            .with_for_update()
        )
        if attempt.status != "prepared":
            return attempt_output(attempt)
        if attempt.created_at.replace(tzinfo=timezone.utc) < now() - timedelta(
            seconds=2 * self.settings.GMAIL_SEND_TIMEOUT_SECONDS + 60
        ):
            return await self.finish(
                key, "failed_before_send", "interrupted_attempt_requires_review"
            )
        attempt.status, attempt.attempted_at, attempt.reconciliation_required = (
            "attempting",
            now(),
            True,
        )
        await (
            self.session.commit()
        )  # A crash from here onward is conservatively uncertain.
        try:
            # Keep connection, draft and evidence locks through the call. Disconnect/edit/suppress serializes.
            await self.lock()
            draft, account = await self.validate(draft_id, actor)
            if binding != self.binding(draft, account, actor):
                raise DraftConflict("send_context_changed_after_reservation")
            current = TokenStore(self.settings).decrypt(
                account.encrypted_access_token, str(account.id) + ":access"
            )
            if current != token:
                raise DraftConflict("sender_token_changed_after_reservation")
            attempt = await self.session.scalar(
                select(OutreachSendAttempt)
                .execution_options(populate_existing=True)
                .where(OutreachSendAttempt.id == key)
                .with_for_update()
            )
            if attempt.status != "attempting":
                return attempt_output(attempt)
            result = await self.client.send(token, raw)
        except (DraftConflict, ConnectionError):
            return await self.finish(
                key, "failed_before_send", "context_changed_before_transmission"
            )
        except SendFailure as exc:
            if exc.category in {"credential_rejected", "scope_or_policy_denied"}:
                account.status, account.encrypted_access_token = (
                    "reauthorization_required",
                    None,
                )
            return await self.finish(
                key,
                "outcome_unknown" if exc.uncertain else "failed_before_send",
                exc.category,
            )
        # Provider metadata mirrors acceptance; human approval/revision stays intact.
        return await self.finish(key, "accepted_by_gmail", result=result)

    async def finish(self, key, state, failure=None, result=None):
        try:
            attempt = await self.session.scalar(
                select(OutreachSendAttempt)
                .execution_options(populate_existing=True)
                .where(OutreachSendAttempt.id == key)
                .with_for_update()
            )
            attempt.status, attempt.failure_category = state, failure
            attempt.reconciliation_required = state == "outcome_unknown"
            if result:
                (
                    attempt.gmail_message_id,
                    attempt.gmail_thread_id,
                    attempt.accepted_at,
                ) = result.id, result.threadId, now()
                await self.session.flush()
                # Core UPDATE avoids treating provider metadata as a new human draft revision.
                await self.session.execute(
                    update(OutreachLog.__table__)
                    .where(OutreachLog.id == attempt.draft_id)
                    .values(
                        gmail_message_id=result.id,
                        gmail_thread_id=result.threadId,
                        sent_at=attempt.accepted_at,
                    )
                )
            await self.session.commit()
            return attempt_output(attempt)
        except SQLAlchemyError:
            # Attempting is already durable. Never retry Gmail to compensate for persistence failure.
            await self.session.rollback()
            attempt = await self.session.get(
                OutreachSendAttempt, key, populate_existing=True
            )
            return attempt_output(attempt) | {
                "reconciliation_required": True,
                "failure_category": "provider_result_persistence_failed",
            }

    async def status(self, key):
        attempt = await self.session.scalar(
            select(OutreachSendAttempt)
            .execution_options(populate_existing=True)
            .where(OutreachSendAttempt.id == key)
            .with_for_update()
        )
        if not attempt:
            raise LookupError("Send attempt not found")
        deadline = now() - timedelta(
            seconds=2 * self.settings.GMAIL_SEND_TIMEOUT_SECONDS + 60
        )
        stamp = attempt.attempted_at or attempt.created_at
        if (
            attempt.status in {"prepared", "attempting"}
            and stamp.replace(tzinfo=timezone.utc) < deadline
        ):
            attempt.failure_category = "interrupted_attempt_requires_review"
            attempt.reconciliation_required = attempt.status == "attempting"
            attempt.status = (
                "outcome_unknown"
                if attempt.status == "attempting"
                else "failed_before_send"
            )
            await self.session.commit()
        return attempt_output(attempt)

    async def history(self, limit=20, offset=0):
        # Include preserved pre-4B records without manufacturing acceptance timestamps.
        association = exists().where(OutreachSendAttempt.draft_id == OutreachLog.id)
        timeline = (
            select(
                OutreachSendAttempt.id.label("id"),
                OutreachSendAttempt.created_at.label("created_at"),
                literal("attempt").label("kind"),
            )
            .union_all(
                select(OutreachLog.id, OutreachLog.created_at, literal("local")).where(
                    ~association
                )
            )
            .subquery()
        )
        page = (
            await self.session.execute(
                select(timeline)
                .order_by(timeline.c.created_at.desc(), timeline.c.id)
                .limit(limit)
                .offset(offset)
            )
        ).all()
        records = []
        for key, _, kind in page:
            if kind == "attempt":
                records.append(await self.status(key))
            else:
                draft = await self.drafts.get(key)
                records.append(
                    {
                        "id": draft.id,
                        "draft_id": draft.id,
                        "draft_revision": draft.draft_revision,
                        "subject": draft.subject,
                        "body": draft.body,
                        "recipient_email": draft.recipient_email,
                        "connected_account_id": draft.connected_account_id,
                        "sender_email": None,
                        "approval_status": draft.approval_status,
                        "status": "legacy_sent_unverified"
                        if draft.sent_at
                        else "not_attempted",
                        "created_at": draft.created_at,
                        "accepted_at": None,
                        "recorded_sent_at": draft.sent_at,
                        "gmail_message_id": draft.gmail_message_id,
                        "gmail_thread_id": draft.gmail_thread_id,
                        "reconciliation_required": bool(draft.sent_at),
                    }
                )
        return {
            "messages": records,
            "limit": limit,
            "offset": offset,
            "total": await self.session.scalar(
                select(func.count()).select_from(timeline)
            ),
        }
