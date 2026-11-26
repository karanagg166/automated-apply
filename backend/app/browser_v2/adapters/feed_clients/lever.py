"""Lever postings feed (api.lever.co / api.eu.lever.co), identity-checked hosted URLs."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from backend.app.browser_v2.adapters.feed_clients.ats_board import AtsBoardSource
from backend.app.browser_v2.adapters.feed_clients.models import RawPosting
from backend.app.browser_v2.adapters.feed_clients.normalization import structured_salary
from backend.app.browser_v2.adapters.feed_clients.validation import posting

LEVER_PERIODS = {
    "per-year-salary": "year",
    "per-month-salary": "month",
    "per-week-salary": "week",
    "per-day-wage": "day",
    "per-hour-wage": "hour",
}


def configured_region() -> str:
    from backend.app.core.config import get_settings

    return str(get_settings().LEVER_REGION)


class LeverClient(AtsBoardSource):
    source_name = "lever"
    JSON_TYPES = (list,)

    def __init__(self, http_client: httpx.AsyncClient, *, region: str | None = None, **kwargs: Any) -> None:
        super().__init__(http_client, **kwargs)
        self.region = configured_region() if region is None else region  # "global" | "eu"
        self.job_host = "jobs.eu.lever.co" if self.region == "eu" else "jobs.lever.co"

    def feed_url(self, board: str) -> str:
        host = "api.eu.lever.co" if self.region == "eu" else "api.lever.co"
        return f"https://{host}/v0/postings/{board}"

    def feed_params(self) -> dict[str, str]:
        return {"mode": "json"}

    def records(self, data: Any) -> Any:
        return data

    def parse(self, item: Any, board: str, company: str) -> RawPosting:
        identifier = item["id"]
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,100}", identifier):
            raise ValueError("Missing posting identity")
        url = self.job_url(item["hostedUrl"], board)
        if urlsplit(url).path.rstrip("/").split("/")[-1] != identifier:
            raise ValueError("Posting ID and hosted URL disagree")
        application = self.job_url(item["applyUrl"], board, application=True) if item.get("applyUrl") else None
        if application and urlsplit(application).path.rstrip("/").removesuffix(
            "/apply"
        ) != urlsplit(url).path.rstrip("/"):
            raise ValueError("Application URL identity mismatch")
        categories: Any = item.get("categories") or {}
        salary: Any = item.get("salaryRange") or {}
        return posting(
            source_name=self.source_name,
            source_job_id=identifier,
            original_url=url,
            application_url=application,
            company_name=company,
            title=item["text"],
            description=item.get("descriptionPlain") or item.get("description"),
            location=categories.get("location"),
            country=item.get("country"),
            remote_type={"remote": "remote", "hybrid": "hybrid", "on-site": "onsite"}.get(
                item.get("workplaceType"), "unknown"),
            employment_type={
                "Full-time": "full_time",
                "Part-time": "part_time",
                "Contract": "contract",
                "Internship": "internship",
            }.get(categories.get("commitment")),
            salary_raw=item.get("salaryDescriptionPlain"),
            **structured_salary(salary.get("min"), salary.get("max"), salary.get("currency"),
                                salary.get("interval"), LEVER_PERIODS),
            # Lever's documented posting fields do not establish a publication date.
            source_verification_status="source_reported",
            is_confirmed_current=True,
            data_provenance={
                "adapter": "LeverAdapter",
                "board_token": f"{self.region}:{board}",
                "company_name_basis": "operator_configured_board",
                "source_fields": {k: v for k, v in item.items() if k not in {"description", "descriptionPlain"}},
            },
        )
