"""Extended adapter contract; legacy callers may still request a list of jobs."""

from abc import ABC, abstractmethod
import asyncio
from typing import Any
import httpx
from backend.app.schemas.discovery import (
    DiscoveryQuery,
    DiscoveryResult,
    DiscoveryStatus,
    DiscoveryError,
)
from backend.app.schemas.normalized_job import NormalizedJob


class JobSourceAdapter(ABC):
    source_name: str

    @abstractmethod
    async def fetch_jobs(self, **kwargs: Any) -> list[NormalizedJob]: ...

    @abstractmethod
    async def test_connection(self) -> dict[str, Any]: ...

    def get_capabilities(self) -> dict:
        from backend.app.services.job_sources.registry import resolve_source

        source = resolve_source(self.source_name)
        return {
            "source": source.id,
            "operations": source.operations,
            "read_only": source.read_only,
            "mutations": source.mutation_capabilities,
            "query_parameters": getattr(self, "query_parameters", []),
        }

    def validate_configuration(self) -> list[str]:
        return []

    async def discover(self, query: DiscoveryQuery, **kwargs) -> DiscoveryResult:
        errors = self.validate_configuration()
        if errors:
            return DiscoveryResult(
                source=self.source_name,
                status=DiscoveryStatus.CONFIGURATION_REQUIRED,
                errors=errors,
            )
        try:
            async with asyncio.timeout(75):
                jobs = await self.fetch_jobs(
                    search_query=" ".join(query.keywords),
                    location=", ".join(query.locations),
                    limit=query.limit,
                    page=query.page,
                    **kwargs,
                )
            return DiscoveryResult(
                source=self.source_name,
                jobs=jobs,
                status=DiscoveryStatus.SUCCESS if jobs else DiscoveryStatus.NO_RESULTS,
            )
        except DiscoveryError as exc:
            return DiscoveryResult(
                source=self.source_name, status=exc.status, errors=[str(exc)]
            )
        except (httpx.HTTPError, TimeoutError, ValueError, KeyError, TypeError):
            return DiscoveryResult(
                source=self.source_name,
                status=DiscoveryStatus.UPSTREAM_ERROR,
                errors=["Provider response could not be processed"],
            )
