"""Job source adapters package."""

from backend.app.services.job_sources.base import JobSourceAdapter
from backend.app.services.job_sources.direct_api import (
    GreenhouseAdapter,
    RemotiveAdapter,
    ArbeitnowAdapter,
    HackerNewsHiringAdapter,
)
from backend.app.services.job_sources.apify_adapter import ApifyJobAdapter, ACTOR_CATALOG
from backend.app.services.job_sources.gmail_adapter import GmailJobAlertAdapter
from backend.app.services.job_sources.factory import JobSourceFactory

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
