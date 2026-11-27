"""Milestone 2: post-apply mail receipt + funnel reconciliation (read-only mail -> applications).

Every housekeeping mail tick (before the recruiter-reply watcher, so a matched mail is recorded once
and never double-alerted) this:
  * reads the last couple of days of mail through the existing 3-tier `MailReadService` (READ only);
  * classifies each mail (`mail_v2.funnel`) and matches it to ONE application of the last 30 days;
  * CONFIRMATION -> APPLIED rows get `email_verified` / `confirmation_email_id` / `confirmed_at` in
    the receipt (+ a same-state timeline event); any funnel mail for a SUBMISSION_UNKNOWN row proves
    delivery, so the row becomes APPLIED (`verified_by_confirmation_email`);
  * OA / interview / recruiter reply -> a timeline event + `mail.funnel_signal` (P1 rollup);
    REJECTED -> timeline event + `mail.funnel_signal` that the notify policy keeps digest-only (P2);
  * counts stale SUBMISSION_UNKNOWN rows (> 24 h, no confirmation) as `needs_reconciliation`.
Idempotent: a message key already present in the application's timeline is skipped. Never stores
mail bodies (no snippet), codes or links; only the subject (bounded) and the message key.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.app.browser_v2.state import (
    EMAIL_RECONCILE_REASON,
    ApplicationState,
    InvalidTransition,
)
from backend.app.mail_v2.funnel import (
    CONFIRMATION,
    EVENT_KIND,
    LEGACY_EVENT_KIND,
    REJECTED,
    classify,
    match_application,
    processed_keys,
)
from backend.app.mail_v2.read_models import MailEvent, MailMessage, MailReadError

logger = logging.getLogger(__name__)
S = ApplicationState
WINDOW = timedelta(days=30)
SCAN_BACK = timedelta(days=2)  # IMAP SINCE is day-granular; dedup makes re-reads free
STALE_AFTER = timedelta(hours=24)
SUBJECT_CHARS = 200
Publish = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class FunnelReport:
    scanned: int = 0
    matched: int = 0
    verified: int = 0
    upgraded: int = 0
    signals: dict[str, int] = field(default_factory=dict)
    needs_reconciliation: int = 0
    errors: list[str] = field(default_factory=list)


class FunnelReconciler:
    def __init__(self, store: Any, reader: Any, *, publish: Publish | None = None,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.reader = reader
        self.publish = publish
        self.clock = clock or (lambda: datetime.now(UTC))

    async def run(self) -> FunnelReport:
        now = self.clock()
        report = FunnelReport()
        try:
            report.needs_reconciliation = len(await self.store.needs_reconciliation(now - STALE_AFTER))
        except Exception as exc:  # noqa: BLE001 - the stale count is informational
            report.errors.append("stale:" + type(exc).__name__)
        candidates = await self.store.mail_match_candidates(now - WINDOW)
        if not candidates:
            return report
        try:
            messages = await self.reader.recent(now - SCAN_BACK)
        except MailReadError as exc:
            report.errors.append(exc.code)
            return report
        for message in messages:
            report.scanned += 1
            try:
                await self.handle(message, candidates, report)
            except Exception as exc:  # noqa: BLE001 - one bad mail never stops the scan
                report.errors.append("message:" + type(exc).__name__)
                logger.warning("funnel reconcile of one mail failed: %s", type(exc).__name__)
        return report

    async def handle(self, message: MailMessage, candidates: list[Any], report: FunnelReport) -> None:
        kind = classify(message)
        if kind is None:
            return
        match = match_application(message, kind, candidates)
        if match is None:
            return
        record = match.record
        if message.key in processed_keys(await self.store.application_events(record.id)):
            return
        report.matched += 1
        await self.record_event(message, kind, record)
        received = (message.received_at or self.clock()).isoformat()
        payload = {"message_key": message.key, "kind": kind, "subject": message.subject[:SUBJECT_CHARS],
                   "sender_domain": message.sender_domain[:120], "received_at": received}
        patch = {"email_verified": True, "confirmation_email_id": message.key[:300], "confirmed_at": received} \
            if kind == CONFIRMATION or record.state == S.SUBMISSION_UNKNOWN else None
        if kind != CONFIRMATION and funnel_rank(kind) >= funnel_rank((record.receipt or {}).get("funnel_stage")):
            patch = (patch or {}) | {"funnel_stage": kind}  # the furthest funnel stage wins
        updated = None
        if record.state == S.SUBMISSION_UNKNOWN:
            try:
                updated = await self.store.transition(record, S.APPLIED, EMAIL_RECONCILE_REASON,
                                                      receipt=dict(record.receipt or {}) | (patch or {}),
                                                      payload=payload)
                report.upgraded += 1
            except InvalidTransition:
                updated = None  # a concurrent writer moved it; the next tick re-reads
        if updated is None:
            event = "email_verified" if kind == CONFIRMATION else f"mail_{kind.lower()}"
            if kind == CONFIRMATION and (record.receipt or {}).get("email_verified"):
                patch = None  # first confirmation wins; later ones are timeline-only
            updated = await self.store.annotate_application(record.id, event, payload, patch)
        if updated is not None:
            self._refresh(candidates, updated)
        if patch:
            report.verified += 1
            await self._publish("mail.reconciled", record, {
                "upgraded": record.state == S.SUBMISSION_UNKNOWN, "kind": kind, "confirmed_at": received})
        if kind != CONFIRMATION:
            report.signals[kind] = report.signals.get(kind, 0) + 1
            await self._publish("mail.funnel_signal", record, {
                "kind": kind, "subject": message.subject[:SUBJECT_CHARS], "message_key": message.key[:120],
                "digest_only": kind == REJECTED})

    async def record_event(self, message: MailMessage, kind: str, record: Any) -> None:
        """mail_events row (dedup by message key; stops the recruiter watcher re-alerting it)."""
        events = getattr(self.reader, "events", None)
        if events is None:
            return
        ready = await events.funnel_kinds_ready()
        stored = EVENT_KIND[kind] if ready else LEGACY_EVENT_KIND.get(kind)
        if stored is None:
            return
        try:
            await events.add(MailEvent(
                message.key, stored, message.source, message.sender[:200], message.subject[:300],
                None, message.received_at, platform=record.platform,
                company_name=record.company_name, application_id=record.id))
        except Exception as exc:  # noqa: BLE001 - the application timeline is the source of truth
            logger.info("mail event insert failed: %s", type(exc).__name__)

    async def _publish(self, topic: str, record: Any, extra: dict[str, Any]) -> None:
        if self.publish is None:
            return
        try:
            await self.publish(topic, {"platform": record.platform, "external_job_id": record.external_job_id,
                                       "application_id": record.id, "company": record.company_name,
                                       "title": record.role_title} | extra)
        except Exception as exc:  # noqa: BLE001 - notification is best effort
            logger.info("publish %s failed: %s", topic, type(exc).__name__)

    @staticmethod
    def _refresh(candidates: list[Any], updated: Any) -> None:
        for index, row in enumerate(candidates):
            if row.id == updated.id:
                candidates[index] = updated


FUNNEL_ORDER = ("RECRUITER_REPLY", "OA_INVITE", "INTERVIEW_INVITE", "REJECTED")


def funnel_rank(kind: str | None) -> int:
    """RECRUITER_REPLY < OA_INVITE < INTERVIEW_INVITE < REJECTED; unknown/None ranks lowest."""
    return FUNNEL_ORDER.index(kind) + 1 if kind in FUNNEL_ORDER else 0
