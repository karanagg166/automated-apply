"""v2-owned HTTP clients for the zero-login public job feeds and ATS boards.

Ported from the reviewed v1 `services.job_sources` clients (same fixed hosts, params,
pagination, size caps and record validation) so v2 no longer depends on `services/`,
plus `ConditionalHttp` (ETag / Last-Modified / body-hash short-circuit, Retry-After,
per-host pacing) for the Phase 9B fast-poll watchers.
"""

from __future__ import annotations

from backend.app.browser_v2.adapters.feed_clients.arbeitnow import ArbeitnowClient
from backend.app.browser_v2.adapters.feed_clients.ashby import AshbyClient
from backend.app.browser_v2.adapters.feed_clients.base import (
    FeedSource,
    FeedSourceError,
)
from backend.app.browser_v2.adapters.feed_clients.greenhouse import GreenhouseClient
from backend.app.browser_v2.adapters.feed_clients.hacker_news import HackerNewsClient
from backend.app.browser_v2.adapters.feed_clients.http import (
    ConditionalHttp,
    FeedHttpError,
    FetchResult,
    HttpStatusError,
    RateLimited,
    ResponseTooLarge,
    Validators,
)
from backend.app.browser_v2.adapters.feed_clients.lever import LeverClient
from backend.app.browser_v2.adapters.feed_clients.models import RawPosting
from backend.app.browser_v2.adapters.feed_clients.remotive import RemotiveClient
from backend.app.browser_v2.adapters.feed_clients.smartrecruiters import (
    SmartRecruitersClient,
)

__all__ = [
    "ArbeitnowClient",
    "AshbyClient",
    "ConditionalHttp",
    "FeedHttpError",
    "FeedSource",
    "FeedSourceError",
    "FetchResult",
    "GreenhouseClient",
    "HackerNewsClient",
    "HttpStatusError",
    "LeverClient",
    "RateLimited",
    "RawPosting",
    "RemotiveClient",
    "ResponseTooLarge",
    "SmartRecruitersClient",
    "Validators",
]
