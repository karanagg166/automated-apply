"""Phase 9B fast-poll watcher value objects, cadences and the injected-callable protocols.

The hub never imports the worker or the service: the orchestrator injects
`score_listing` (service), `wake` (worker) and `publish` (event bus) as plain callables.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from backend.app.browser_v2.adapters.common import role_query_match
from backend.app.browser_v2.adapters.feed_clients.http import Validators
from backend.app.browser_v2.adapters.feeds import FeedJob
from backend.app.browser_v2.adapters.public_sources import REMOTIVE_MAX_FETCHES_PER_DAY
from backend.app.browser_v2.domain import JobListing
from backend.app.browser_v2.priority import PriorityInput, posted_from, score
from backend.app.browser_v2.store.phase9_records import DiscoveryMeta

MINUTE = 60.0
HOUR = 60 * MINUTE
# Per-source cadence (seconds) by family; every source in a family is polled round-robin, staggered.
FAMILY_INTERVALS: dict[str, float] = {
    "greenhouse": 3 * MINUTE,
    "lever": 3 * MINUTE,
    "ashby": 3 * MINUTE,
    "himalayas": 5 * MINUTE,
    "we_work_remotely": 5 * MINUTE,
    "hiringcafe": 5 * MINUTE,
    "remotive": 24 * HOUR / REMOTIVE_MAX_FETCHES_PER_DAY,
    "arbeitnow": HOUR,
    "hacker_news": 3 * HOUR,
}
FAMILIES = tuple(FAMILY_INTERVALS)
JITTER = 0.2  # +-20 %
FAMILY_STAGGER_SEC = 7.0  # startup offset between families (never a burst at boot)
IDLE_RECHECK_SEC = 5 * MINUTE  # a family with no enabled source re-reads rules/prefs this often
MAX_SLEEP_SEC = MINUTE  # re-read the source list at least once a minute while waiting
BREAKER_THRESHOLD = 3
BREAKER_OPEN = (timedelta(minutes=15), timedelta(minutes=30), timedelta(minutes=60))
DEFAULT_RETRY_AFTER = timedelta(minutes=15)
MAX_POSTING_AGE = timedelta(days=7)
MAX_ROLES = 5
HIRINGCAFE_HOURLY_CALLS = 12


@dataclass(frozen=True)
class BudgetSpec:
    source: str  # watcher_state row holding the counter
    limit: int
    window: str  # day | hour


REMOTIVE_BUDGET = BudgetSpec("remotive:budget", REMOTIVE_MAX_FETCHES_PER_DAY, "day")
HIRINGCAFE_BUDGET = BudgetSpec("hiringcafe:budget", HIRINGCAFE_HOURLY_CALLS, "hour")


@dataclass(frozen=True)
class Fetched:
    """One source read: `jobs is None` means "not modified" (nothing to parse)."""

    status: int
    validators: Validators | None
    jobs: list[FeedJob] | None


Fetcher = Callable[[Any, Any, Validators | None], Awaitable[Fetched]]  # (ConditionalHttp, AsyncClient, validators)


@dataclass(frozen=True)
class WatchSource:
    key: str  # watcher_state.source, e.g. "greenhouse:stripe"
    family: str
    platform: str  # portal rule + JobListing.platform
    interval: float
    kind: str = "http"  # http | hiringcafe
    fetch: Fetcher | None = None
    query: str | None = None
    budget: BudgetSpec | None = None


@dataclass
class PollOutcome:
    source: str
    status: str  # baseline | not_modified | polled | disabled | circuit_open | budget_exhausted | error | unknown
    new: int = 0
    upserted: int = 0
    p0: int = 0
    woke: bool = False
    next_poll_at: datetime | None = None
    error: str | None = None


class ScoreListing(Protocol):
    """`service.score_listing` (B2): sync or async, returns the DiscoveryMeta to upsert with."""

    def __call__(self, listing: JobListing, prefs: Mapping[str, Any], *, now: datetime, newly_seen: bool,
                 via: str) -> DiscoveryMeta | Awaitable[DiscoveryMeta]: ...


Wake = Callable[[str], Any]  # worker.wake(reason); sync or async
Publish = Callable[[str, dict[str, Any]], Any]  # bus.publish(topic, payload); sync or async
PrefsProvider = Callable[[], Awaitable[Mapping[str, Any]]]
RulesProvider = Callable[[], Awaitable[Mapping[str, Any]]]  # {platform: PortalRules-like (has .enabled)}
Clock = Callable[[], datetime]
Sleeper = Callable[[float], Awaitable[Any]]
McpCall = Callable[[str, dict[str, Any]], Awaitable[str]]  # (tool, arguments) -> markdown text


def aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def target_roles(prefs: Mapping[str, Any]) -> list[str]:
    roles = prefs.get("target_roles") if isinstance(prefs, Mapping) else None
    if not isinstance(roles, (list, tuple)):
        return []
    cleaned = [" ".join(str(r).split())[:100] for r in roles if isinstance(r, str) and r.strip()]
    return list(dict.fromkeys(cleaned))[:MAX_ROLES]


def role_slug(role: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", role.lower()).strip("-")[:60] or "any"


def passes_prefilter(job: FeedJob, roles: list[str], now: datetime) -> bool:
    """Cheap role/age gate before scoring (unknown posting age passes; the worker's rules decide later)."""
    if not job.title:
        return False
    if roles and not any(role_query_match(job.title, role) for role in roles):
        return False
    posted = aware(job.posted_at)
    return posted is None or now - posted <= MAX_POSTING_AGE


def fallback_score_listing(listing: JobListing, prefs: Mapping[str, Any], *, now: datetime, newly_seen: bool,
                           via: str) -> DiscoveryMeta:
    """Used only when no service scorer is injected: role match = strong match, pure `priority.score`."""
    roles = target_roles(prefs)
    strong = bool(roles) and any(role_query_match(listing.title, role) for role in roles)
    posted = posted_from(now=now, age_hours=listing.posted_age_hours, age_days=listing.posted_age_days,
                         posted_at=listing.posted_at, lower_bound=listing.age_is_lower_bound)
    decision = score(PriorityInput(posted=posted, strong_match=strong, newly_seen=newly_seen), now)
    return DiscoveryMeta(priority=int(decision.priority), priority_reason=decision.reason, posted_at=posted.at,
                         posted_precision=posted.precision, discovered_via=via)
