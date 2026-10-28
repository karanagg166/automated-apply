"""Identity-preserving factory. A generic provider never chooses a default platform."""

from backend.app.schemas.discovery import DiscoveryError
from backend.app.schemas.discovery import DiscoveryStatus as Status
from backend.app.services.job_sources.base import JobSourceAdapter
from backend.app.services.job_sources.direct_api import (
    ArbeitnowAdapter,
    GreenhouseAdapter,
    HackerNewsHiringAdapter,
    RemotiveAdapter,
)
from backend.app.services.job_sources.public_ats import AshbyAdapter, LeverAdapter
from backend.app.services.job_sources.registry import resolve_source, source_registry
from backend.app.services.job_sources.smartrecruiters import SmartRecruitersAdapter


class UnavailableAdapter(JobSourceAdapter):
    def __init__(self, config):
        self.source_name, self.config = config.id, config

    async def fetch_jobs(self, **kwargs):
        raise DiscoveryError(
            Status.MANUAL_INPUT_REQUIRED
            if self.config.adapter_type == "manual"
            else Status.AUTH_REQUIRED
            if self.source_name == "linkedin"
            else Status.UNSUPPORTED,
            f"{self.source_name}: {self.config.availability}",
        )

    def get_capabilities(self):
        return self.config.model_dump()

    async def test_connection(self):
        return {
            "status": "not_attempted",
            "source": self.source_name,
            "sample_count": 0,
            "message": self.config.availability,
            "details": {},
        }


class JobSourceFactory:
    _adapters = {
        "greenhouse": GreenhouseAdapter,
        "lever": LeverAdapter,
        "ashby": AshbyAdapter,
        "smartrecruiters": SmartRecruitersAdapter,
        "remotive": RemotiveAdapter,
        "arbeitnow": ArbeitnowAdapter,
        "hacker_news": HackerNewsHiringAdapter,
    }

    @classmethod
    def get_adapter(cls, source_name, **kwargs):
        config = resolve_source(source_name)
        if config.adapter_type == "apify":
            from backend.app.core.config import get_settings
            from backend.app.services.job_sources.apify_adapter import ApifyJobAdapter
            from backend.app.services.providers.apify import ApifyRoutePool
            settings = kwargs.get("settings") or get_settings()
            routes = settings.APIFY_SOURCE_ROUTES.get(config.id, [])
            if routes and "configuration" not in kwargs:
                if len(routes) > 5:
                    raise ValueError("At most five reviewed Apify routes per source")
                return ApifyRoutePool([ApifyJobAdapter(source_name=config.id, configuration=route, **kwargs) for route in routes])
            return ApifyJobAdapter(source_name=config.id, **kwargs)
        if config.id in cls._adapters:
            return cls._adapters[config.id](**kwargs)
        # Legacy Gmail can still be explicitly constructed, but protected discovery doesn't execute it.
        if config.id == "gmail_alert":
            from backend.app.services.job_sources.gmail_adapter import (
                GmailJobAlertAdapter,
            )

            return GmailJobAlertAdapter(**kwargs)
        return UnavailableAdapter(config)

    @classmethod
    def list_supported_sources(cls):
        return list(source_registry())
