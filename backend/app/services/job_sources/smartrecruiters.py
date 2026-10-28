"""Documented public Posting API only; never credentials, internal jobs or applications."""

import re
from urllib.parse import urlsplit

from backend.app.core.config import get_settings
from backend.app.schemas.discovery import DiscoveryError, DiscoveryQuery
from backend.app.schemas.discovery import DiscoveryStatus as Status
from backend.app.schemas.normalized_job import NormalizedJob
from backend.app.services.job_sources.direct_api import DirectAdapter
from backend.app.services.job_sources.normalization import employment, parse_date

IDENTIFIER = re.compile(r"[A-Za-z0-9-]{1,100}")


def posting_url(value, board, identifier):
    """Only actual source-supplied links matching this company/posting are usable."""
    parsed = urlsplit(value) if isinstance(value, str) else None
    if (
        parsed is None
        or parsed.scheme != "https"
        or parsed.netloc != "jobs.smartrecruiters.com"
        or parsed.fragment
        or parsed.query not in {"", "oga=true"}
        or not re.fullmatch(
            r"/" + re.escape(board) + "/" + re.escape(identifier)
            + r"(?:-[A-Za-z0-9_%~-]+)?/?", parsed.path, re.I
        )
    ):
        raise ValueError("Posting URL does not match the configured employer and ID")
    return value


class SmartRecruitersAdapter(DirectAdapter):
    source_name = "smartrecruiters"
    query_parameters = ["page", "limit", "configured_boards"]

    def __init__(self, http_client=None, settings=None):
        super().__init__(http_client)
        self.settings = settings or get_settings()
        self.boards = dict(self.settings.SMARTRECRUITERS_BOARDS)

    def validate_configuration(self):
        return [] if self.boards else ["Configure SMARTRECRUITERS_BOARDS with reviewed employer IDs"]

    def feed_url(self, board):
        return f"https://api.smartrecruiters.com/v1/companies/{board}/postings"

    async def request(self, client, url, params=None):
        allowed = any(
            url == self.feed_url(board)
            or url.startswith(self.feed_url(board) + "/")
            and IDENTIFIER.fullmatch(url.removeprefix(self.feed_url(board) + "/"))
            for board in self.boards
        )
        if not allowed:
            raise DiscoveryError(Status.CONFIGURATION_REQUIRED, "ATS feed URL is not allowlisted")
        return await super().request(client, url, params)

    def parse(self, item, board, identifier):
        if item.get("id") != identifier or item.get("active") is not True:
            raise ValueError("Inactive or inconsistent public posting")
        company = item["company"]
        if company.get("identifier", "").casefold() != board.casefold():
            raise ValueError("Posting employer mismatch")
        url = posting_url(item["postingUrl"], board, identifier)
        application = posting_url(item["applyUrl"], board, identifier) if item.get("applyUrl") else None
        location = item.get("location") or {}
        if item.get("releasedDate") is not None and not isinstance(item["releasedDate"], str):
            raise ValueError("Invalid publication timestamp type")
        sections = (item.get("jobAd") or {}).get("sections") or {}
        # Exclude recruiter identity, private links and arbitrary provider JSON at rest.
        description = "\n\n".join(
            sections[key]["text"] for key in ("jobDescription", "qualifications", "additionalInformation")
            if key in sections and isinstance(sections[key].get("text"), str)
        ) or None
        return NormalizedJob(
            source_name=self.source_name,
            source_job_id=identifier,
            original_url=url,
            application_url=application,
            company_name=self.boards[board],
            title=item["name"],
            description=description,
            location=", ".join(str(location[k]) for k in ("city", "region", "country") if location.get(k)) or None,
            country=location.get("country"),
            region=location.get("region"),
            # A false remote flag alone does not establish an onsite policy.
            remote_type="remote" if location.get("remote") is True else "unknown",
            employment_type=employment((item.get("typeOfEmployment") or {}).get("label")),
            experience_level=(item.get("experienceLevel") or {}).get("label"),
            date_posted=parse_date(item.get("releasedDate")),
            source_verification_status="source_reported",
            is_confirmed_current=True,
            data_provenance={
                "adapter": type(self).__name__, "board_token": board,
                "company_name_basis": "operator_configured_board",
                "publication_basis": "releasedDate",
                "public_posting_id": identifier,
            },
        )

    async def fetch_jobs(self, limit=20, page=1, **kwargs):
        DiscoveryQuery(limit=limit, page=page)
        if self.validate_configuration():
            raise DiscoveryError(Status.CONFIGURATION_REQUIRED, self.validate_configuration()[0])
        if set(kwargs) - {"search_query", "location", "allow_paid", "reservation_id"}:
            raise DiscoveryError(Status.UNSUPPORTED, "Only configured ATS boards may be fetched")
        start, remaining = (page - 1) * limit, limit
        jobs, seen = [], set()
        self.record_errors, self.next_cursor = [], None
        client = self.client()
        try:
            for index, board in enumerate(self.boards):
                data = await self.request(client, self.feed_url(board), {"offset": start, "limit": remaining})
                records, total = data.get("content"), data.get("totalFound")
                if (
                    not isinstance(records, list) or len(records) > remaining
                    or type(total) is not int or total < 0
                    or type(data.get("offset")) is not int
                    or type(data.get("limit")) is not int
                    or data.get("offset") != start or data.get("limit") != remaining
                    or len(records) != min(remaining, max(0, total - start))
                ):
                    raise DiscoveryError(Status.UPSTREAM_ERROR, "Inconsistent public posting pagination")
                if start >= total:
                    start -= total
                    continue
                for record in records:
                    try:
                        identifier = record["id"]
                        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier):
                            raise ValueError("Invalid posting ID")
                        if (board, identifier) in seen:
                            raise ValueError("Duplicate posting in provider page")
                        seen.add((board, identifier))
                        # Construct the fixed-host path. Never follow the untrusted ref URL.
                        detail = await self.request(client, self.feed_url(board) + "/" + identifier)
                        jobs.append(self.parse(detail, board, identifier))
                    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
                        if isinstance(exc, DiscoveryError):
                            raise
                        self.record_errors.append("Invalid public posting evidence")
                remaining -= len(records)
                if total > start + len(records) or index < len(self.boards) - 1:
                    self.next_cursor = str(page + 1) if page < 100 else None
                start = 0
                if remaining <= 0:
                    break
            return jobs
        finally:
            if self._client is None:
                await client.aclose()
