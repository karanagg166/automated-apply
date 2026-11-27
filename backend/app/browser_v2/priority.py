"""Phase 9B early-bird priority model (pure domain: no I/O, no clock reads).

Tiers (lower runs first):
  P0 URGENT  strong match AND (posted <= 2 h ago with hour precision, OR a newly-seen delta on a
             source that already has a baseline and whose posting age is unknown or <= 24 h),
             OR a job URL the owner sent ("apply to <url> now").
  P1 FRESH   posted <= 24 h ago, OR an owner-answered HITL resume, OR a job-alert e-mail link.
  P2 STANDARD posted 1-7 days ago (and the default for unknown age).
  P3 BACKLOG quota retry (DRAFTED_AND_QUEUED) or older eligible jobs.

Within a tier the queue runs newest posting first. Stale tiers decay (P0 -> P1 after 2 h
unprocessed, P1 -> P2 after 24 h) so a burst of old "early-bird" rows never starves fresh ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import IntEnum

P0_MAX_AGE = timedelta(hours=2)
P1_MAX_AGE = timedelta(hours=24)
P2_MAX_AGE = timedelta(days=7)
DELTA_MAX_AGE = timedelta(hours=24)
P0_DECAY_AFTER = timedelta(hours=2)
P1_DECAY_AFTER = timedelta(hours=24)
PRECISIONS = ("hour", "day", "unknown")


class Priority(IntEnum):
    P0 = 0
    P1 = 1
    P2 = 2
    P3 = 3

    @property
    def label(self) -> str:
        return f"P{int(self)}"


@dataclass(frozen=True)
class PostedAt:
    at: datetime | None
    precision: str = "unknown"  # hour | day | unknown

    @property
    def known(self) -> bool:
        return self.at is not None and self.precision != "unknown"


@dataclass(frozen=True)
class PriorityInput:
    posted: PostedAt = PostedAt(None)
    strong_match: bool = False
    newly_seen: bool = False  # first time this id appears on a source that already has a baseline
    user_requested: bool = False
    hitl_resume: bool = False
    via_alert_email: bool = False
    quota_retry: bool = False


@dataclass(frozen=True)
class PriorityDecision:
    priority: Priority
    reason: str


_HOURS = re.compile(r"(\d+)\s*\+?\s*(minute|min|hour|hr|h)s?\b", re.IGNORECASE)
_NOW_WORDS = re.compile(r"\b(just now|just posted|few (?:minutes|mins|seconds)( ago)?|moments? ago|an hour ago|"
                        r"a few hours ago)\b", re.IGNORECASE)


def parse_posted_age_hours(text: str | None) -> float | None:
    """Hour-precision age from card text: "3 hours ago" -> 3, "45 minutes ago" -> 0.75,
    "Just now" -> 0. Returns None when the text only has day precision (or none)."""
    if not text:
        return None
    lowered = " ".join(text.lower().split())
    if re.search(r"\b(day|week|month|year)s?\b", lowered) or "yesterday" in lowered:
        return None
    match = _HOURS.search(lowered)
    if match:
        value = float(match.group(1))
        return value / 60.0 if match.group(2).startswith("min") else value
    if _NOW_WORDS.search(lowered):
        return 0.0
    return None


def posted_from(*, now: datetime, age_hours: float | None = None, age_days: int | None = None,
                posted_at: datetime | None = None, lower_bound: bool = False) -> PostedAt:
    """Best-known posting time. An exact timestamp wins, then hour age, then day age.
    ``lower_bound`` ("30+ days ago") never claims more precision than "day"."""
    if posted_at is not None:
        at = posted_at if posted_at.tzinfo else posted_at.replace(tzinfo=UTC)
        precision = "day" if (at.hour, at.minute, at.second) == (0, 0, 0) else "hour"
        return PostedAt(min(at, now), precision)
    if age_hours is not None and age_hours >= 0 and not lower_bound:
        return PostedAt(now - timedelta(hours=age_hours), "hour")
    if age_days is not None and age_days >= 0:
        return PostedAt(now - timedelta(days=age_days), "day")
    return PostedAt(None, "unknown")


def score(inp: PriorityInput, now: datetime) -> PriorityDecision:
    """Deterministic tier for a newly discovered or re-queued job."""
    if inp.user_requested:
        return PriorityDecision(Priority.P0, "owner_requested")
    age = (now - inp.posted.at) if inp.posted.at is not None else None
    if inp.strong_match:
        if age is not None and inp.posted.precision == "hour" and age <= P0_MAX_AGE:
            return PriorityDecision(Priority.P0, "posted_within_2h")
        if inp.newly_seen and (age is None or age <= DELTA_MAX_AGE):
            return PriorityDecision(Priority.P0, "new_on_watched_source")
    if inp.hitl_resume:
        return PriorityDecision(Priority.P1, "hitl_answered")
    if inp.quota_retry:
        return PriorityDecision(Priority.P3, "quota_retry")
    if age is not None and age <= P1_MAX_AGE:
        return PriorityDecision(Priority.P1, "posted_within_24h")
    if inp.via_alert_email:
        return PriorityDecision(Priority.P1, "job_alert_email")
    if age is None:
        return PriorityDecision(Priority.P2, "posting_age_unknown")
    if age <= P2_MAX_AGE:
        return PriorityDecision(Priority.P2, "posted_within_7d")
    return PriorityDecision(Priority.P3, "older_than_7d")


def decayed(priority: int, queued_at: datetime, now: datetime) -> int:
    """P0 left unprocessed for 2 h becomes P1; P1 left for 24 h becomes P2. Never promotes."""
    waited = now - queued_at
    if priority == Priority.P0 and waited > P0_DECAY_AFTER:
        priority = Priority.P1
        waited -= P0_DECAY_AFTER
    if priority == Priority.P1 and waited > P1_DECAY_AFTER:
        priority = Priority.P2
    return int(priority)


def queue_key(priority: int, posted_at: datetime | None, created_at: datetime) -> tuple[int, float]:
    """Sort key: tier first, then newest posting (falls back to discovery time)."""
    when = posted_at or created_at
    return int(priority), -when.timestamp()


def better(a: int | None, b: int | None) -> int:
    """The more urgent of two tiers (used when a row is re-discovered or handed off)."""
    values = [int(v) for v in (a, b) if v is not None]
    return min(values) if values else int(Priority.P2)


# --- adaptive cadence (IST hiring hours) -------------------------------------------------------
PEAK_HOURS_IST = (9, 20)  # 09:00-20:00 Asia/Kolkata: most Indian postings go live


def is_peak(now: datetime, hours: tuple[int, int] = PEAK_HOURS_IST) -> bool:
    from zoneinfo import ZoneInfo

    local = now.astimezone(ZoneInfo("Asia/Kolkata"))
    return hours[0] <= local.hour < hours[1]


def cadence_factor(now: datetime, *, peak: float = 1.0, off_peak: float = 2.0) -> float:
    """Interval multiplier: poll at full speed in IST hiring hours, back off overnight."""
    return peak if is_peak(now) else off_peak
