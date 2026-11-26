"""The validated posting a v2 feed client hands to its FeedAdapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RawPosting:
    """Exactly the evidence the v2 adapters read (HTML descriptions stay HTML)."""

    source_job_id: str | None
    title: str
    company_name: str | None
    original_url: str
    application_url: str | None = None
    description: str | None = None
    date_posted: datetime | None = None
    location: str | None = None
    remote_type: str = "unknown"  # remote | hybrid | onsite | unknown
    salary_raw: str | None = None
    # Provider fields kept for adapters that read beyond the normalized ones (Lever `createdAt`).
    source_fields: Mapping[str, Any] = field(default_factory=dict)
