"""Phase 9B fast-poll watchers (non-browser discovery for the early-bird queue).

Greenhouse / Lever / Ashby boards (3 min), Himalayas + We Work Remotely (5 min), HiringCafe via
its public MCP endpoint (5 min, <= 12 calls/hour), Remotive (<= 4/day), Arbeitnow (1 h) and
Hacker News (3 h). Conditional GETs, baseline-then-delta, per-source breaker, all state in
`watcher_state`. `build_watcher_hub(...)` is the wiring entry point for the worker runtime.
"""

from __future__ import annotations

from backend.app.browser_v2.watchers.hiringcafe import (
    HiringCafeError,
    HiringCafeJob,
    HiringCafeParseError,
    employer_apply_link,
    parse_search,
    search_arguments,
)
from backend.app.browser_v2.watchers.hub import WatcherHub, build_watcher_hub
from backend.app.browser_v2.watchers.models import (
    FAMILIES,
    FAMILY_INTERVALS,
    HIRINGCAFE_BUDGET,
    REMOTIVE_BUDGET,
    BudgetSpec,
    Fetched,
    PollOutcome,
    ScoreListing,
    WatchSource,
    fallback_score_listing,
)

__all__ = [
    "FAMILIES",
    "FAMILY_INTERVALS",
    "HIRINGCAFE_BUDGET",
    "REMOTIVE_BUDGET",
    "BudgetSpec",
    "Fetched",
    "HiringCafeError",
    "HiringCafeJob",
    "HiringCafeParseError",
    "PollOutcome",
    "ScoreListing",
    "WatchSource",
    "WatcherHub",
    "build_watcher_hub",
    "employer_apply_link",
    "fallback_score_listing",
    "parse_search",
    "search_arguments",
]
