"""Identity-preserving factory. A generic provider never chooses a default platform."""

from backend.app.services.job_sources.base import JobSourceAdapter
from backend.app.services.job_sources.direct_api import (
    GreenhouseAdapter,
    RemotiveAdapter,
    ArbeitnowAdapter,
    HackerNewsHiringAdapter,
)
from backend.app.services.job_sources.registry import resolve_source, source_registry
from backend.app.schemas.discovery import DiscoveryError, DiscoveryStatus as Status


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
        "remotive": RemotiveAdapter,
        "arbeitnow": ArbeitnowAdapter,
        "hacker_news": HackerNewsHiringAdapter,
    }

    @classmethod
    def get_adapter(cls, source_name, **kwargs):
        config = resolve_source(source_name)
        if config.adapter_type == "apify":
            from backend.app.services.job_sources.apify_adapter import ApifyJobAdapter

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
