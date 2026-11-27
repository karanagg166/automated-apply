"""Milestone 2: opt-in high-score outreach DRAFT handoff after a successful application.

OFF by default (AUTO_OUTREACH_DRAFT_ENABLED=false). When on, every `job.applied` event is queued
(bounded) and drained between jobs by `MaintenanceMixin.drain_outreach`: a job whose fit score is at
least OUTREACH_DRAFT_SCORE_THRESHOLD (default 85) gets ONE enrichment lookup + ONE grounded Gmail
draft, reusing the quota-fallback path (`QuotaHitProcessor.draft_once`: cached enrichment with credit
caps, `DraftComposer`, `MailDraftService` with per-application idempotency). It can only ever SAVE a
draft (IMAP APPEND to Drafts / Mail.app save); nothing here can send an email.

Fit score (0-100, deterministic, no LLM): an explicit `score` / `fit_score` on the event wins; else
strong target-role title match 60 + early-bird tier (P0 30, P1 25, P2 10) + target company 10.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from backend.app.browser_v2.rules import CandidatePreferences, normalize_text
from backend.app.browser_v2.service.scoring import title_matches_target
from backend.app.browser_v2.state import ApplicationState

logger = logging.getLogger(__name__)
ENABLED_ENV = "AUTO_OUTREACH_DRAFT_ENABLED"
THRESHOLD_ENV = "OUTREACH_DRAFT_SCORE_THRESHOLD"
DEFAULT_THRESHOLD = 85.0
TIER_POINTS = {0: 30, 1: 25, 2: 10}
MAX_QUEUE = 25
DRAINS_PER_TICK = 3
Publish = Callable[[str, dict[str, Any]], Awaitable[None]]


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _number(value: Any) -> float | None:
    try:
        return None if value is None or isinstance(value, bool) else float(value)
    except (TypeError, ValueError):
        return None


def fit_score(record: Any, preferences: Mapping[str, Any], event: Mapping[str, Any] | None = None) -> float:
    explicit = _number((event or {}).get("fit_score")) or _number((event or {}).get("score"))
    if explicit is not None:
        return max(0.0, min(100.0, explicit))
    prefs = CandidatePreferences.from_profile({"preferences": dict(preferences)})
    score = 60.0 if title_matches_target(getattr(record, "role_title", None), prefs) else 0.0
    priority = getattr(record, "priority", None)
    score += TIER_POINTS.get(int(priority) if isinstance(priority, int) else 2, 0)
    companies = preferences.get("target_companies")
    company = normalize_text(getattr(record, "company_name", None) or "")
    if company and isinstance(companies, (list, tuple)) and any(
            isinstance(c, str) and normalize_text(c) == company for c in companies):
        score += 10
    return min(score, 100.0)


class OutreachHandoff:
    def __init__(self, store: Any, quota: Any, *, publish: Publish | None = None, enabled: bool = False,
                 threshold: float = DEFAULT_THRESHOLD) -> None:
        self.store = store
        self.quota = quota
        self.publish = publish
        self.enabled = enabled
        self.threshold = threshold
        self.queue: deque[dict[str, Any]] = deque(maxlen=MAX_QUEUE)
        self.results: list[dict[str, Any]] = []

    @classmethod
    def from_env(cls, store: Any, quota: Any, env: Mapping[str, str], *,
                 publish: Publish | None = None) -> OutreachHandoff:
        threshold = _number(env.get(THRESHOLD_ENV))
        return cls(store, quota, publish=publish, enabled=_flag(env.get(ENABLED_ENV)),
                   threshold=DEFAULT_THRESHOLD if threshold is None else max(0.0, min(threshold, 100.0)))

    async def on_applied(self, topic: str, payload: dict[str, Any]) -> None:
        """Bus subscriber (`job.applied`): queue only; the draft is made between jobs, never inline."""
        if not self.enabled or not payload.get("platform") or not payload.get("external_job_id"):
            return
        self.queue.append({k: payload.get(k) for k in ("platform", "external_job_id", "score", "fit_score")})

    async def drain(self, limit: int = DRAINS_PER_TICK) -> list[dict[str, Any]]:
        done: list[dict[str, Any]] = []
        while self.enabled and self.queue and len(done) < limit:
            event = self.queue.popleft()
            try:
                done.append(await self.handle(event))
            except Exception as exc:  # noqa: BLE001 - one draft never blocks the worker
                logger.warning("outreach draft for %s failed: %s", event.get("external_job_id"), type(exc).__name__)
                done.append({"external_job_id": event.get("external_job_id"), "outcome": "error"})
        self.results = (self.results + done)[-50:]
        return done

    async def handle(self, event: Mapping[str, Any]) -> dict[str, Any]:
        record = await self.store.get(str(event["platform"]), str(event["external_job_id"]))
        base = {"external_job_id": event.get("external_job_id"), "platform": event.get("platform")}
        if record is None or record.state != ApplicationState.APPLIED:
            return base | {"outcome": "not_applied"}
        profile, _ = await self.store.load_profile()
        profile = profile if isinstance(profile, dict) else {}
        prefs = profile.get("preferences") if isinstance(profile.get("preferences"), Mapping) else {}
        score = fit_score(record, prefs or {}, event)
        if score < self.threshold:
            return base | {"outcome": "below_threshold", "fit_score": score}
        draft_once = getattr(self.quota, "draft_once", None)
        if draft_once is None:
            return base | {"outcome": "mail_not_wired", "fit_score": score}
        _, details = await draft_once(record, profile)
        outcome = str(details.get("draft_reason") or "draft_failed")
        if outcome == "drafted":
            await self.store.annotate_application(record.id, "outreach_drafted", {
                "fit_score": score, "channel": details.get("channel"), "composer": details.get("composer"),
                "resume_variant": details.get("resume_variant"), "sent": False})
            if self.publish is not None:
                await self.publish("job.outreach_draft", {
                    "platform": record.platform, "external_job_id": record.external_job_id,
                    "application_id": record.id, "company": record.company_name, "title": record.role_title,
                    "fit_score": score})
        return base | {"outcome": outcome, "fit_score": score}
