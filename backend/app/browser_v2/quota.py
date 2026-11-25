"""Phase 5 quota-hit dual action: one Gmail draft per job (ever) + tomorrow's portal retry.

When a portal hits the dashboard `max_applies_per_day` or its own native daily cap,
candidate jobs that passed the hard filters are parked as QUOTA_HIT_PENDING. Each
cycle, a bounded number of them are processed:

  Action 1 (draft, once): enrichment -> recruiter email -> composed draft -> IMAP /
           Mail.app. Skipped when applications.draft_created_at / email_drafts already
           exists; NO_EMAIL_FOUND never creates an addressee-less draft.
  Action 2 (retry, always): retry_after = next daily reset (active_hours_start, else
           00:05) in the portal timezone, QUOTA_HIT_PENDING -> DRAFTED_AND_QUEUED.

The worker later moves due DRAFTED_AND_QUEUED jobs back to SCORED and applies. A job
whose retry would fall outside `max_job_age_days` of its discovery expires to
FILTERED_OUT. Nothing here can submit an application or deliver an email.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from backend.app.browser_v2.adapters.base import JobDetail
from backend.app.browser_v2.portals import portal_label
from backend.app.browser_v2.rules import PortalRules
from backend.app.browser_v2.state import ApplicationState, InvalidTransition
from backend.app.browser_v2.store import ApplicationRecord, Store

if TYPE_CHECKING:
    from backend.app.ai_v2.runtime import AIRuntime
    from backend.app.enrichment_v2.service import EnrichmentService
    from backend.app.mail_v2.composer import DraftComposer
    from backend.app.mail_v2.service import MailDraftService

logger = logging.getLogger(__name__)
S = ApplicationState

DAILY_RESET = time(0, 5)
DRAFTS_PER_CYCLE = 5
JD_EXCERPT_CHARS = 2_000
QUOTA_LIMIT_REASONS = frozenset({"dashboard_daily_limit", "portal_daily_limit"})
DAILY_CAP_ENV = "QUOTA_FALLBACK_DAILY_CAP"
DEFAULT_DAILY_CAP = 10


def fallback_daily_cap() -> int:
    """Max new jobs parked (and so drafted) per portal per day while its quota is hit."""
    try:
        value = int(os.environ.get(DAILY_CAP_ENV, DEFAULT_DAILY_CAP))
    except ValueError:
        return DEFAULT_DAILY_CAP
    return min(max(value, 0), 100)


def next_daily_reset(rules: PortalRules, now: datetime) -> datetime:
    """Tomorrow at active_hours_start (never before 00:05) in the portal's timezone, as UTC."""
    zone = ZoneInfo(rules.timezone)
    local = now.astimezone(zone)
    start = rules.active_hours_start
    at = max(DAILY_RESET, start.replace(tzinfo=None)) if start is not None else DAILY_RESET
    return datetime.combine(local.date() + timedelta(days=1), at, tzinfo=zone).astimezone(UTC)


def retry_deadline(record: ApplicationRecord, rules: PortalRules, now: datetime) -> datetime:
    return (record.created_at or now) + timedelta(days=rules.max_job_age_days)


def contact_hints(detail: JobDetail) -> dict[str, Any]:
    """Bounded JD excerpt persisted with the state event (enrichment Tier 1 + draft tailoring)."""
    hints: dict[str, Any] = {}
    if detail.description:
        hints["jd_excerpt"] = detail.description[:JD_EXCERPT_CHARS]
    return hints


def hints_from_events(events: list[dict[str, Any]] | None) -> dict[str, Any]:
    for event in reversed(events or []):
        payload = event.get("payload")
        if isinstance(payload, Mapping) and isinstance(payload.get("contact_hints"), Mapping):
            return dict(payload["contact_hints"])
    return {}


@dataclass
class QuotaReport:
    platform: str
    drafted: int = 0
    queued: int = 0
    no_email: int = 0
    already_drafted: int = 0
    draft_failed: int = 0
    expired: int = 0
    rescheduled: int = 0
    errors: int = 0
    retry_after: datetime | None = None
    outcomes: list[dict[str, Any]] = field(default_factory=list)

    @property
    def touched(self) -> bool:
        return bool(self.queued or self.rescheduled or self.expired)


Notifier = Callable[[str], Awaitable[None]]


class QuotaHitProcessor:
    def __init__(self, store: Store, *, enrichment: EnrichmentService | None = None,
                 mail: MailDraftService | None = None, composer: DraftComposer | None = None,
                 ai: AIRuntime | None = None, clock: Callable[[], datetime] | None = None,
                 drafts_per_cycle: int = DRAFTS_PER_CYCLE) -> None:
        self.store = store
        self.enrichment = enrichment
        self.mail = mail
        self.composer = composer
        self.ai = ai
        self.clock = clock or (lambda: datetime.now(UTC))
        self.drafts_per_cycle = drafts_per_cycle

    async def process(self, rules: PortalRules, profile: Mapping[str, Any], *,
                      quota_exhausted: bool) -> QuotaReport:
        platform, now = rules.platform, self.clock()
        retry_at = next_daily_reset(rules, now)
        report = QuotaReport(platform=platform, retry_after=retry_at)
        if quota_exhausted:
            # Overdue retries cannot run today either: push them to the next reset (no new draft).
            for record in await self.store.due_retries(platform, now, limit=200):
                await self._requeue(record, rules, retry_at, "quota_hit_rescheduled", {}, report, now)
        pending = await self.store.list_by_state(platform, (S.QUOTA_HIT_PENDING,), limit=self.drafts_per_cycle)
        if pending and self.ai is not None:
            self.ai.bind_profile(profile)  # owner identifiers are scrubbed from the draft prompt
        for record in pending:
            try:
                await self.handle(record, rules, profile, retry_at, report, now)
            except InvalidTransition:
                logger.warning("quota processor: %s moved concurrently", record.external_job_id)
            except Exception as exc:
                report.errors += 1
                logger.exception("quota processor failed for %s", record.external_job_id)
                report.outcomes.append({"external_job_id": record.external_job_id,
                                        "error": type(exc).__name__})
                fresh = await self.store.get_application(record.id)
                if fresh is not None and fresh.state == S.QUOTA_HIT_PENDING:
                    await self._requeue(fresh, rules, retry_at, "quota_hit_queued_draft_failed",
                                        {"error": type(exc).__name__}, report, now)
        return report

    async def handle(self, record: ApplicationRecord, rules: PortalRules, profile: Mapping[str, Any],
                     retry_at: datetime, report: QuotaReport, now: datetime) -> None:
        fresh = await self.store.get_application(record.id) or record
        if fresh.state != S.QUOTA_HIT_PENDING:
            return
        if retry_at > retry_deadline(fresh, rules, now):
            await self._requeue(fresh, rules, retry_at, "quota_retry_expired", {}, report, now)
            return
        reason, payload = await self.draft_once(fresh, profile)
        await self._requeue(fresh, rules, retry_at, reason, payload, report, now)

    async def draft_once(self, record: ApplicationRecord, profile: Mapping[str, Any]
                         ) -> tuple[str, dict[str, Any]]:
        """Action 1. Returns the state-event reason and a payload (never the recipient address)."""
        from backend.app.mail_v2.composer import DraftComposer, DraftJob
        from backend.app.mail_v2.message import resume_attachment

        if self.mail is None or self.enrichment is None:
            return "quota_hit_queued_draft_unavailable", {"draft_reason": "mail_or_enrichment_not_wired"}
        if await self.mail.already_drafted(record):
            return "quota_hit_queued_already_drafted", {"draft_reason": "already_drafted"}
        if not self.mail.enabled:
            return "quota_hit_queued_draft_unavailable", {"draft_reason": "mail_unconfigured"}
        hints = hints_from_events(await self.store.application_events(record.id))
        jd_text = hints.get("jd_excerpt") if isinstance(hints.get("jd_excerpt"), str) else None
        found = await self.enrichment.find_recruiter_email(
            company_name=record.company_name, job_url=record.job_url, jd_text=jd_text,
            role_title=record.role_title)
        enrichment = {"status": found.status, "source": found.source, "cached": found.cached,
                      "credits_spent": found.credits_spent}
        if not found.found or not found.email:
            return "quota_hit_queued_no_email", {"draft_reason": "quota_hit_no_recruiter_email",
                                                 "enrichment": enrichment}
        composer = self.composer or DraftComposer(self.ai.router if self.ai is not None else None)
        attachment, _ = resume_attachment(self.mail.config.resume_path)
        content = await composer.compose(
            DraftJob(role_title=record.role_title, company_name=record.company_name, platform=record.platform,
                     job_url=record.job_url, jd_text=jd_text, recipient_first_name=found.first_name),
            profile, has_attachment=attachment is not None)
        full_name = profile.get("full_name")
        outcome = await self.mail.create_application_draft(
            record, found.email, content, sender_name=full_name if isinstance(full_name, str) else None,
            enrichment_source=found.source)
        details = {"enrichment": enrichment, "channel": outcome.channel, "fell_back": outcome.fell_back,
                   "composer": content.composer, "attachment": outcome.attachment}
        if outcome.created:
            return "quota_hit_drafted_and_queued", {"draft_reason": "drafted", **details}
        if outcome.already_drafted:
            return "quota_hit_queued_already_drafted", {"draft_reason": "already_drafted"}
        return "quota_hit_queued_draft_failed", {"draft_reason": outcome.error or "draft_failed",
                                                 "ambiguous": outcome.ambiguous, **details}

    async def _requeue(self, record: ApplicationRecord, rules: PortalRules, retry_at: datetime, reason: str,
                       payload: dict[str, Any], report: QuotaReport, now: datetime) -> None:
        """Action 2: always schedule tomorrow's retry (or expire a job past max_job_age_days)."""
        if reason != "quota_retry_expired" and retry_at > retry_deadline(record, rules, now):
            reason = "quota_retry_expired"
        if reason == "quota_retry_expired":
            await self.store.transition(record, S.FILTERED_OUT, reason,
                                        payload={"max_job_age_days": rules.max_job_age_days})
            report.expired += 1
            report.outcomes.append({"external_job_id": record.external_job_id, "state": "FILTERED_OUT",
                                    "reason": reason})
            return
        await self.store.transition(record, S.DRAFTED_AND_QUEUED, reason,
                                    payload=payload | {"retry_after": retry_at.isoformat()}, retry_after=retry_at)
        if reason == "quota_hit_rescheduled":
            report.rescheduled += 1
        else:
            report.queued += 1
            report.drafted += reason == "quota_hit_drafted_and_queued"
            report.no_email += reason == "quota_hit_queued_no_email"
            report.already_drafted += reason == "quota_hit_queued_already_drafted"
            report.draft_failed += reason in ("quota_hit_queued_draft_failed", "quota_hit_queued_draft_unavailable")
        report.outcomes.append({"external_job_id": record.external_job_id, "state": "DRAFTED_AND_QUEUED",
                                "reason": reason, "retry_after": retry_at.isoformat()})


def quota_summary(rules: PortalRules, drafted: int, queued: int, retry_at: datetime | None) -> str:
    """'Naukri daily limit hit — created 3 Gmail drafts & queued 5 jobs for tomorrow 08:00 IST'."""
    when = ""
    if retry_at is not None:
        local = retry_at.astimezone(ZoneInfo(rules.timezone))
        when = f" for tomorrow {local.strftime('%H:%M')} {local.strftime('%Z') or rules.timezone}"
    drafts = f"{drafted} Gmail draft{'s' if drafted != 1 else ''}"
    jobs = f"{queued} job{'s' if queued != 1 else ''}"
    return f"{portal_label(rules.platform)} daily limit hit — created {drafts} & queued {jobs}{when}"


async def build_quota_processor(service: Any, env: Mapping[str, str] | None = None) -> QuotaHitProcessor:
    """Real wiring for the worker / API: enrichment + mail bridge on the service's store."""
    from backend.app.enrichment_v2.service import EnrichmentService
    from backend.app.mail_v2.composer import DraftComposer
    from backend.app.mail_v2.config import MailConfig
    from backend.app.mail_v2.service import MailDraftService

    values = dict(env) if env is not None else None
    enrichment = await EnrichmentService.for_store(service.store, env=values)
    mail = MailDraftService(service.store, MailConfig.from_env(values))
    ai = getattr(service, "ai", None)
    return QuotaHitProcessor(service.store, enrichment=enrichment, mail=mail,
                             composer=DraftComposer(ai.router if ai is not None else None), ai=ai)
