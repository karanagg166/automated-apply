"""Job source factory and registry."""

from typing import Any
from backend.app.services.job_sources.base import JobSourceAdapter
from backend.app.services.job_sources.direct_api import (
    GreenhouseAdapter,
    RemotiveAdapter,
    ArbeitnowAdapter,
    HackerNewsHiringAdapter,
)
from backend.app.services.job_sources.apify_adapter import ApifyJobAdapter
from backend.app.services.job_sources.gmail_adapter import GmailJobAlertAdapter


class JobSourceFactory:
    """Factory to instantiate and resolve job source adapters."""

    _adapters: dict[str, type[JobSourceAdapter]] = {
        "greenhouse": GreenhouseAdapter,
        "remotive": RemotiveAdapter,
        "arbeitnow": ArbeitnowAdapter,
        "hacker_news": HackerNewsHiringAdapter,
        "apify": ApifyJobAdapter,
        "gmail_alert": GmailJobAlertAdapter,
    }

    @classmethod
    def get_adapter(cls, source_name: str, **kwargs: Any) -> JobSourceAdapter:
        """Resolve adapter instance by source name."""
        name_clean = source_name.lower().strip()
        adapter_cls = cls._adapters.get(name_clean)
        if not adapter_cls:
            # If requesting a specific portal like 'naukri' or 'wellfound', use Apify adapter
            if name_clean in (
                "naukri",
                "instahyre",
                "wellfound",
                "work_at_a_startup",
                "cutshort",
                "hirist",
                "foundit",
                "indeed",
                "glassdoor",
            ):
                return ApifyJobAdapter(**kwargs)
            raise ValueError(f"Unknown job source '{source_name}'. Registered: {list(cls._adapters.keys())}")
        return adapter_cls(**kwargs)

    @classmethod
    def list_supported_sources(cls) -> list[str]:
        """Return list of all supported job source names."""
        return list(cls._adapters.keys()) + [
            "naukri",
            "instahyre",
            "wellfound",
            "work_at_a_startup",
            "cutshort",
            "hirist",
            "foundit",
            "indeed",
            "glassdoor",
        ]
