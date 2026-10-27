"""Official credential-free ATS GET feeds, scoped to operator-allowlisted boards."""

import json
import math
import re
from urllib.parse import urlsplit

from backend.app.core.config import get_settings
from backend.app.schemas.discovery import DiscoveryError, DiscoveryQuery
from backend.app.schemas.discovery import DiscoveryStatus as Status
from backend.app.schemas.normalized_job import NormalizedJob
from backend.app.services.job_sources.direct_api import DirectAdapter
from backend.app.services.job_sources.normalization import parse_date


def structured_salary(minimum, maximum, currency, interval, periods):
    """Do not coerce strings, booleans, equity, or incompatible ranges into pay."""
    if any(
        value is not None
        and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1e12
        )
        for value in (minimum, maximum)
    ):
        return {}
    if minimum is None and maximum is None:
        return {}
    if minimum is not None and maximum is not None and minimum > maximum:
        return {}
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        return {}
    period = periods.get(interval) if isinstance(interval, str) else None
    if not period:
        return {}
    return dict(
        salary_min=minimum,
        salary_max=maximum,
        salary_currency=currency,
        salary_period=period,
    )


class PublicATSAdapter(DirectAdapter):
    query_parameters = ["page", "limit", "configured_boards"]

    def __init__(self, http_client=None, settings=None):
        super().__init__(http_client)
        self.settings = settings or get_settings()
        self.boards = dict(getattr(self.settings, self.source_name.upper() + "_BOARDS"))

    def validate_configuration(self):
        return (
            []
            if self.boards
            else [
                f"Configure {self.source_name.upper()}_BOARDS with allowlisted board-ID/employer-name pairs"
            ]
        )

    async def request(self, client, url, params=None):
        # Defense in depth: even internal callers cannot redirect this adapter's GET.
        if url not in {self.feed_url(board) for board in self.boards}:
            raise DiscoveryError(
                Status.CONFIGURATION_REQUIRED, "ATS feed URL is not allowlisted"
            )
        return await super().request(client, url, params)

    def job_url(self, value, board, *, application=False):
        if not isinstance(value, str):
            raise ValueError("Missing hosted job URL")
        parsed = urlsplit(value)
        suffix = r"(?:/apply)?" if self.source_name == "lever" else r"(?:/application)?"
        if (
            parsed.scheme != "https"
            or parsed.netloc != self.job_host
            or parsed.query
            or parsed.fragment
            or not re.fullmatch(
                r"/"
                + "(?i:"
                + re.escape(board)
                + ")"
                + r"/[A-Za-z0-9-]{1,100}"
                + (suffix if application else ""),
                parsed.path.removesuffix("/"),
            )
        ):
            raise ValueError("Hosted job URL conflicts with configured board")
        return value

    async def fetch_jobs(self, limit=20, page=1, **kwargs):
        DiscoveryQuery(limit=limit, page=page)
        if self.validate_configuration():
            raise DiscoveryError(
                Status.CONFIGURATION_REQUIRED, self.validate_configuration()[0]
            )
        # No request-supplied board or URL selection, including legacy adapter kwargs.
        if set(kwargs) - {"search_query", "location", "allow_paid", "reservation_id"}:
            raise DiscoveryError(
                Status.UNSUPPORTED, "Only configured ATS boards may be fetched"
            )
        start, remaining = (page - 1) * limit, limit
        jobs, errors, seen = [], [], {}
        self.next_cursor = None
        client = self.client()
        try:
            for board_index, (board, company) in enumerate(self.boards.items()):
                data = await self.request(
                    client, self.feed_url(board), self.feed_params()
                )
                records = self.records(data)
                if not isinstance(records, list):
                    raise DiscoveryError(
                        Status.UPSTREAM_ERROR, "Invalid ATS jobs collection"
                    )
                # Never expose unlisted Ashby postings. Missing visibility is malformed.
                records = (
                    [
                        r
                        for r in records
                        if not (isinstance(r, dict) and r.get("isListed") is False)
                    ]
                    if self.source_name == "ashby"
                    else records
                )
                if start >= len(records):
                    start -= len(records)
                    continue
                selected = records[start : start + remaining]
                for index, record in enumerate(selected):
                    try:
                        job = self.parse(record, board, company)
                        key = (board, job.source_job_id or job.canonical_url)
                        evidence = json.dumps(record, sort_keys=True)
                        if key in seen:
                            if seen[key] != evidence:
                                raise ValueError("Inconsistent duplicate posting")
                            continue
                        seen[key] = evidence
                        jobs.append(job)
                    except (
                        ValueError,
                        TypeError,
                        KeyError,
                        AttributeError,
                        OverflowError,
                    ):
                        errors.append(
                            f"Board {board_index}, record {index}: invalid or inconsistent listing evidence"
                        )
                remaining -= len(selected)
                if (
                    len(records) > start + len(selected)
                    or board_index < len(self.boards) - 1
                ):
                    self.next_cursor = str(page + 1) if page < 100 else None
                start = 0
                if remaining <= 0:
                    break
            self.record_errors = errors
            return jobs
        finally:
            if self._client is None:
                await client.aclose()


class LeverAdapter(PublicATSAdapter):
    source_name = "lever"
    JSON_TYPES = (list,)

    @property
    def job_host(self):
        return (
            "jobs.eu.lever.co"
            if self.settings.LEVER_REGION == "eu"
            else "jobs.lever.co"
        )

    def feed_url(self, board):
        host = (
            "api.eu.lever.co" if self.settings.LEVER_REGION == "eu" else "api.lever.co"
        )
        return f"https://{host}/v0/postings/{board}"

    def feed_params(self):
        return {"mode": "json"}

    def records(self, data):
        return data

    def parse(self, item, board, company):
        identifier = item["id"]
        if not isinstance(identifier, str) or not re.fullmatch(
            r"[A-Za-z0-9-]{1,100}", identifier
        ):
            raise ValueError("Missing posting identity")
        url = self.job_url(item["hostedUrl"], board)
        if urlsplit(url).path.rstrip("/").split("/")[-1] != identifier:
            raise ValueError("Posting ID and hosted URL disagree")
        application = (
            self.job_url(item["applyUrl"], board, application=True)
            if item.get("applyUrl")
            else None
        )
        if application and urlsplit(application).path.rstrip("/").removesuffix(
            "/apply"
        ) != urlsplit(url).path.rstrip("/"):
            raise ValueError("Application URL identity mismatch")
        categories = item.get("categories") or {}
        salary = item.get("salaryRange") or {}
        return NormalizedJob(
            source_name=self.source_name,
            source_job_id=identifier,
            original_url=url,
            application_url=application,
            company_name=company,
            title=item["text"],
            description=item.get("descriptionPlain") or item.get("description"),
            location=categories.get("location"),
            country=item.get("country"),
            remote_type={
                "remote": "remote",
                "hybrid": "hybrid",
                "on-site": "onsite",
            }.get(item.get("workplaceType"), "unknown"),
            employment_type={
                "Full-time": "full_time",
                "Part-time": "part_time",
                "Contract": "contract",
                "Internship": "internship",
            }.get(categories.get("commitment")),
            salary_raw=item.get("salaryDescriptionPlain"),
            **structured_salary(
                salary.get("min"),
                salary.get("max"),
                salary.get("currency"),
                salary.get("interval"),
                {
                    "per-year-salary": "year",
                    "per-month-salary": "month",
                    "per-week-salary": "week",
                    "per-day-wage": "day",
                    "per-hour-wage": "hour",
                },
            ),
            # Lever's documented posting fields do not establish a publication date.
            source_verification_status="source_reported",
            is_confirmed_current=True,
            data_provenance={
                "adapter": type(self).__name__,
                "board_token": f"{self.settings.LEVER_REGION}:{board}",
                "company_name_basis": "operator_configured_board",
                "source_fields": {
                    k: v
                    for k, v in item.items()
                    if k not in {"description", "descriptionPlain"}
                },
            },
        )


class AshbyAdapter(PublicATSAdapter):
    source_name = "ashby"
    job_host = "jobs.ashbyhq.com"

    def feed_url(self, board):
        return f"https://api.ashbyhq.com/posting-api/job-board/{board}"

    def feed_params(self):
        return {"includeCompensation": "true"}

    def records(self, data):
        if data.get("apiVersion") != "1":
            raise DiscoveryError(
                Status.UPSTREAM_ERROR, "Unsupported Ashby feed version"
            )
        return data["jobs"]

    def parse(self, item, board, company):
        if item.get("isListed") is not True:
            raise ValueError("Posting visibility missing")
        url = self.job_url(item["jobUrl"], board)
        application = (
            self.job_url(item["applyUrl"], board, application=True)
            if item.get("applyUrl")
            else None
        )
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
        remote = {"Remote": "remote", "Hybrid": "hybrid", "OnSite": "onsite"}.get(
            workplace, "unknown"
        )
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
        return NormalizedJob(
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
            **structured_salary(
                salary.get("minValue"),
                salary.get("maxValue"),
                salary.get("currencyCode"),
                salary.get("interval"),
                {
                    "1 YEAR": "year",
                    "1 MONTH": "month",
                    "1 WEEK": "week",
                    "1 DAY": "day",
                    "1 HOUR": "hour",
                },
            ),
            source_verification_status="source_reported",
            is_confirmed_current=True,
            data_provenance={
                "adapter": type(self).__name__,
                "board_token": board,
                "company_name_basis": "operator_configured_board",
                "publication_basis": "last_published_at",
                "source_fields": {
                    k: v
                    for k, v in item.items()
                    if k not in {"descriptionPlain", "descriptionHtml"}
                },
            },
        )
