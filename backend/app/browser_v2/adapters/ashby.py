"""Ashby direct-ATS adapter (Milestone 2): discovery + hosted form apply, zero login.

Discovery is unchanged (allowlisted `preferences.ashby_boards` through the public
api.ashbyhq.com posting feed, `feed_clients.ashby`). Apply opens the hosted form at
jobs.ashbyhq.com/<board>/<uuid>/application and fills it with the shared deterministic-first
`HostedFormFiller` (identity facts -> semantic cache v2 -> LLM -> owner HITL), the Human Pulse
pacing, the pre-submit read-back and the submit marker. Dry runs stop before Submit.

Conservative by default: the seeded portal_rules row keeps `ashby` disabled with
`auto_apply_enabled=false` until the owner turns it on (inspect + score only meanwhile).
Ashby postings found behind OTHER portals stay external (no automatic cross-portal handoff).
"""

from __future__ import annotations

from typing import Any

from backend.app.browser_v2.adapters.feeds import FeedJob
from backend.app.browser_v2.adapters.public_sources import (
    AshbyAdapter as AshbyFeedAdapter,
)
from backend.app.browser_v2.adapters.shared.external_handoff import (
    SUPPORTED_ATS,
    classify_ashby,
    classify_ats,
)

ASHBY_SUPPORTED = SUPPORTED_ATS | {"ashby"}


class AshbyAdapter(AshbyFeedAdapter):
    platform = "ashby"
    supported_ats = ASHBY_SUPPORTED

    def classify(self, url: str | None) -> str | None:
        return classify_ashby(url) or classify_ats(url)

    async def resolve_apply_url(self, page: Any, job: FeedJob) -> str | None:
        """The hosted Ashby posting (its /application form) when the feed has no separate link."""
        for candidate in (job.apply_url, job.url):
            if classify_ashby(candidate) is not None:
                return candidate
        return job.apply_url
