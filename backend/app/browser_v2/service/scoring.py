"""Phase 9B: early-bird tier for a discovered listing (pure: no I/O, the caller passes `now`).

Used by `BrowserService.prefilter` (sweeps, rotation discovery, backlog) and by the fast-poll
watchers, so every discovery path scores a listing the same way.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from backend.app.browser_v2.domain import JobListing
from backend.app.browser_v2.priority import (
    PriorityInput,
    parse_posted_age_hours,
    posted_from,
    score,
)
from backend.app.browser_v2.rules import CandidatePreferences
from backend.app.browser_v2.rules.normalize import _role_matches
from backend.app.browser_v2.store import DiscoveryMeta

DEFAULT_VIA = "discovery"


def title_matches_target(title: str | None, prefs: CandidatePreferences) -> bool:
    """Strict target-role match (the LLM title gray zone is *not* a strong match)."""
    return bool(title) and bool(prefs.target_roles) and any(
        _role_matches(title or "", role) for role in prefs.target_roles)


def as_preferences(prefs: CandidatePreferences | Mapping[str, Any] | None) -> CandidatePreferences:
    """Watchers hand over the raw `candidate_profiles.preferences` mapping; the service passes the
    parsed dataclass. Accept both so every discovery path shares one scorer."""
    if isinstance(prefs, CandidatePreferences):
        return prefs
    return CandidatePreferences.from_profile({"preferences": dict(prefs or {})})


def score_listing(listing: JobListing, prefs: CandidatePreferences | Mapping[str, Any] | None, *, now: datetime,
                  newly_seen: bool = False, via: str | None = None, passed: bool = True) -> DiscoveryMeta:
    """Tier + best-known posting time for `listing`.

    strong match = `passed` (the caller's filter pipeline accepted the card; watchers that do not
    run it keep the default) AND the title matches a target role. `newly_seen` is only meaningful
    for a source that already has a baseline (sweeps/watchers)."""
    prefs = as_preferences(prefs)
    hours = listing.posted_age_hours
    if hours is None:
        hours = parse_posted_age_hours(listing.posted_text)
    posted = posted_from(now=now, age_hours=hours, age_days=listing.posted_age_days,
                         posted_at=listing.posted_at, lower_bound=listing.age_is_lower_bound)
    decision = score(PriorityInput(posted=posted, strong_match=passed and title_matches_target(listing.title, prefs),
                                   newly_seen=newly_seen), now)
    return DiscoveryMeta(priority=int(decision.priority), priority_reason=decision.reason, posted_at=posted.at,
                         posted_precision=posted.precision, discovered_via=via or DEFAULT_VIA)
