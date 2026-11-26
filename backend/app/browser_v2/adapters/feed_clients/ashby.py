"""Ashby public job-board API (api.ashbyhq.com posting-api), listed postings only."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from backend.app.browser_v2.adapters.feed_clients.ats_board import AtsBoardSource
from backend.app.browser_v2.adapters.feed_clients.base import FeedSourceError
from backend.app.browser_v2.adapters.feed_clients.models import RawPosting
from backend.app.browser_v2.adapters.feed_clients.normalization import (
    parse_date,
    structured_salary,
)
from backend.app.browser_v2.adapters.feed_clients.validation import posting

ASHBY_PERIODS = {"1 YEAR": "year", "1 MONTH": "month", "1 WEEK": "week", "1 DAY": "day", "1 HOUR": "hour"}


class AshbyClient(AtsBoardSource):
    source_name = "ashby"
    job_host = "jobs.ashbyhq.com"

    def feed_url(self, board: str) -> str:
        return f"https://api.ashbyhq.com/posting-api/job-board/{board}"

    def feed_params(self) -> dict[str, str]:
        return {"includeCompensation": "true"}

    def records(self, data: Any) -> Any:
        if data.get("apiVersion") != "1":
            raise FeedSourceError("Unsupported Ashby feed version")
        return data["jobs"]

    def visible(self, records: list[Any]) -> list[Any]:
        # Never expose unlisted Ashby postings. Missing visibility is malformed.
        return [r for r in records if not (isinstance(r, dict) and r.get("isListed") is False)]

    def parse(self, item: Any, board: str, company: str) -> RawPosting:
        if item.get("isListed") is not True:
            raise ValueError("Posting visibility missing")
        url = self.job_url(item["jobUrl"], board)
        application = self.job_url(item["applyUrl"], board, application=True) if item.get("applyUrl") else None
        if application and urlsplit(application).path.rstrip("/").removesuffix(
            "/application"
        ) != urlsplit(url).path.rstrip("/"):
            raise ValueError("Application URL identity mismatch")
        compensation = item.get("compensation") or {}
        components = compensation.get("summaryComponents") or []
        salaries = [c for c in components if c.get("compensationType") == "Salary"]
        salary = salaries[0] if len(salaries) == 1 else {}
        workplace = item.get("workplaceType")
        # isRemote includes hybrid; without workplaceType the precise policy is unknown.
        remote = {"Remote": "remote", "Hybrid": "hybrid", "OnSite": "onsite"}.get(workplace, "unknown")
        flag = item.get("isRemote")
        published = item.get("publishedAt")
        if published is not None and not isinstance(published, str):
            raise ValueError("Invalid publication timestamp type")
        if flag is not None and (
            not isinstance(flag, bool)
            or workplace in {"Remote", "Hybrid", "OnSite"}
            and flag != (workplace != "OnSite")
        ):
            raise ValueError("Inconsistent workplace evidence")
        return posting(
            source_name=self.source_name,
            source_job_id=urlsplit(url).path.rstrip("/").split("/")[-1],
            original_url=url,
            application_url=application,
            company_name=company,
            title=item["title"],
            description=item.get("descriptionPlain") or item.get("descriptionHtml"),
            location=item.get("location"),
            remote_type=remote,
            employment_type={
                "FullTime": "full_time",
                "PartTime": "part_time",
                "Contract": "contract",
                "Intern": "internship",
                "Temporary": "temporary",
            }.get(item.get("employmentType")),
            date_posted=parse_date(published),
            salary_raw=compensation.get("scrapeableCompensationSalarySummary"),
            **structured_salary(salary.get("minValue"), salary.get("maxValue"), salary.get("currencyCode"),
                                salary.get("interval"), ASHBY_PERIODS),
            source_verification_status="source_reported",
            is_confirmed_current=True,
            data_provenance={
                "adapter": "AshbyAdapter",
                "board_token": board,
                "company_name_basis": "operator_configured_board",
                "publication_basis": "last_published_at",
                "source_fields": {k: v for k, v in item.items() if k not in {"descriptionPlain", "descriptionHtml"}},
            },
        )
