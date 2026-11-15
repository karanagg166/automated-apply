"""Job source adapters package."""

from backend.app.services.job_sources.apify_adapter import (
    ACTOR_CATALOG,
    ApifyJobAdapter,
)
from backend.app.services.job_sources.base import JobSourceAdapter
from backend.app.services.job_sources.direct_api import (
    ArbeitnowAdapter,
    GreenhouseAdapter,
    HackerNewsHiringAdapter,
    RemotiveAdapter,
)
from backend.app.services.job_sources.factory import JobSourceFactory
from backend.app.services.job_sources.gmail_adapter import GmailJobAlertAdapter

__all__ = [
    "JobSourceAdapter",
    "GreenhouseAdapter",
    "RemotiveAdapter",
    "ArbeitnowAdapter",
    "HackerNewsHiringAdapter",
    "ApifyJobAdapter",
    "ACTOR_CATALOG",
    "GmailJobAlertAdapter",
    "JobSourceFactory",
]
