"""Base abstract class for job source adapters."""

from abc import ABC, abstractmethod
from typing import Any
from backend.app.schemas.normalized_job import NormalizedJob


class JobSourceAdapter(ABC):
    """Abstract interface that all job source adapters must implement."""

    source_name: str

    @abstractmethod
    async def fetch_jobs(self, **kwargs: Any) -> list[NormalizedJob]:
        """Fetch and normalize job postings from the underlying source.

        Returns:
            List of NormalizedJob instances conforming to the unified schema.
        """
        pass

    @abstractmethod
    async def test_connection(self) -> dict[str, Any]:
        """Perform a safe, read-only connectivity check.

        Returns:
            Dictionary containing:
                - status: 'passed' | 'failed' | 'not_attempted'
                - source: str
                - sample_count: int
                - message: str
                - details: dict[str, Any]
        """
        pass
