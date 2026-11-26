"""Record validation for v2 feed clients.

A faithful port of the v1 `NormalizedJob` contract (plus the public-HTTPS URL and job-URL
identity rules it relies on), so a provider record that v1 rejected (unsafe URL, empty
title, over-long field, implausible date, > 256 KiB record ...) is still dropped and an
accepted one carries the same stripped values into the `RawPosting`.
"""

from __future__ import annotations

import ipaddress
import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    TypeAdapter,
    field_validator,
    model_validator,
)

from backend.app.browser_v2.adapters.feed_clients.models import RawPosting


def validate_public_https(value: HttpUrl) -> HttpUrl:
    host = (value.host or "").strip("[]").lower()
    if value.scheme != "https" or value.username is not None or value.password is not None:
        raise ValueError("A credential-free HTTPS URL is required")
    if value.port not in (None, 443) or not host or "." not in host or host.endswith(
            (".localhost", ".local", ".internal", ".localdomain")):
        raise ValueError("A public HTTPS hostname is required")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Private and reserved addresses are not allowed")
    if any(ord(c) < 32 or c in "\\\r\n" for c in unquote(str(value))):
        raise ValueError("Unsafe URL characters")
    return value


PublicHTTPSURL = Annotated[HttpUrl, Field(max_length=2048), AfterValidator(validate_public_https)]
_validator: TypeAdapter[HttpUrl] = TypeAdapter(PublicHTTPSURL)
_TRACKING = {"fbclid", "gclid", "ref", "referrer", "source", "trk", "trackingid", "gh_src"}
_ATS_PATHS = {
    "job-boards.greenhouse.io": r"/[^/]+/jobs/[0-9]+",
    "jobs.lever.co": r"/[^/]+/[A-Za-z0-9-]{10,}(?:/apply)?",
    "jobs.eu.lever.co": r"/[^/]+/[A-Za-z0-9-]{10,}(?:/apply)?",
    "jobs.ashbyhq.com": r"/[^/]+/[A-Za-z0-9-]{10,}(?:/application)?",
    "jobs.smartrecruiters.com": r"/[A-Za-z0-9_-]+/[0-9]{5,}(?:-[A-Za-z0-9_%~-]+)?",
}


def canonical_job_url(value: str) -> str:
    parsed = urlsplit(str(_validator.validate_python(value)))
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/") or "/"
    # These hosts serve the same Greenhouse board/post identities.
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        host = "job-boards.greenhouse.io"
    query = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING
    ]
    return urlunsplit(("https", host, path, urlencode(sorted(query)), ""))


def ats_job_url(value: str | None) -> str | None:
    """Only a recognizable per-job ATS path can be used as a common identity."""
    if value is None:
        return None
    normalized = canonical_job_url(value)
    parsed = urlsplit(normalized)
    pattern = _ATS_PATHS.get(parsed.hostname or "")
    if pattern and re.fullmatch(pattern, parsed.path):
        path = re.sub(r"/(?:apply|application)$", "", parsed.path)
        query = parsed.query
        if parsed.hostname == "jobs.smartrecruiters.com":
            path = re.sub(r"(/[0-9]{5,})(?:-.*)?$", r"\1", path)
            # The documented apply view is the same posting identity.
            query = urlencode([(k, v) for k, v in parse_qsl(query) if k != "oga"])
        return urlunsplit((parsed.scheme, parsed.netloc, path, query, ""))
    return None


def _now() -> datetime:
    return datetime.now(UTC)


class PostingRecord(BaseModel):
    """Field-for-field copy of v1 NormalizedJob (the dumped size is part of the contract)."""

    source_name: str = Field(min_length=1, max_length=100)
    source_job_id: str | None = Field(None, max_length=255)
    original_url: str = Field(max_length=2048)
    canonical_url: str | None = Field(None, max_length=2048)
    application_url: str | None = Field(None, max_length=2048)
    company_name: str | None = Field(None, max_length=255)
    company_domain: str | None = Field(None, max_length=255)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(None, max_length=200000)
    location: str | None = Field(None, max_length=255)
    country: str | None = Field(None, max_length=100)
    region: str | None = Field(None, max_length=100)
    is_remote: bool | None = None
    remote_type: Literal["remote", "hybrid", "onsite", "unknown"] = "unknown"
    employment_type: str | None = Field(None, max_length=50)
    experience_level: str | None = Field(None, max_length=50)
    experience_min_years: float | None = Field(None, ge=0, le=60, strict=True, allow_inf_nan=False)
    experience_max_years: float | None = Field(None, ge=0, le=60, strict=True, allow_inf_nan=False)
    salary_raw: str | None = Field(None, max_length=1000)
    salary_min: float | None = Field(None, ge=0, le=1e12, allow_inf_nan=False)
    salary_max: float | None = Field(None, ge=0, le=1e12, allow_inf_nan=False)
    salary_currency: str | None = None
    salary_period: Literal["hour", "day", "week", "month", "year"] | None = None
    equity: str | None = Field(None, max_length=1000)
    skills_required: list[str] = Field(default_factory=list, max_length=100)
    skills_preferred: list[str] = Field(default_factory=list, max_length=100)
    date_posted: datetime | None = None
    first_observed_date: datetime = Field(default_factory=_now)
    last_observed_date: datetime = Field(default_factory=_now)
    retrieved_at: datetime = Field(default_factory=_now)
    data_provenance: dict[str, Any] = Field(default_factory=dict)
    company_intelligence: dict[str, Any] = Field(default_factory=dict)
    source_verification_status: Literal["observed", "source_reported", "verified", "requires_review"] = "observed"
    quality_flags: list[str] = Field(default_factory=list, max_length=50)
    is_confirmed_current: bool = False
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    @field_validator("original_url", "canonical_url", "application_url")
    @classmethod
    def safe_urls(cls, value: str | None) -> str | None:
        if value is None:
            return value
        canonical_job_url(value)  # Preserve original evidence link; canonicalize separately.
        return value

    @field_validator("salary_currency")
    @classmethod
    def currency(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[A-Z]{3}|[$€£]", value):
            raise ValueError("Use a currency code or observed currency symbol")
        return value

    @field_validator("remote_type", mode="before")
    @classmethod
    def legacy_remote(cls, value: Any) -> Any:
        return "unknown" if value in (None, "unspecified") else value

    @field_validator("date_posted", "first_observed_date", "last_observed_date", "retrieved_at")
    @classmethod
    def timestamps(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
        if value < datetime(1990, 1, 1, tzinfo=UTC) or value > datetime.now(UTC) + timedelta(days=1):
            raise ValueError("Invalid observation/publication date")
        return value

    @model_validator(mode="after")
    def evidence(self) -> PostingRecord:
        if (
            self.experience_min_years is not None and self.experience_max_years is not None
            and self.experience_min_years > self.experience_max_years
        ):
            raise ValueError("Experience minimum exceeds maximum")
        original = canonical_job_url(self.original_url)
        application_identity = ats_job_url(self.application_url)
        if self.canonical_url and canonical_job_url(self.canonical_url) not in {original, application_identity}:
            raise ValueError("Canonical override requires an observed ATS application URL")
        self.canonical_url = application_identity or original
        if self.remote_type == "unknown" and self.is_remote is True:
            self.remote_type = "remote"
        self.is_remote = {"remote": True, "onsite": False}.get(self.remote_type)
        if not self.company_name:
            self.company_name = None
            if "company_unknown" not in self.quality_flags:
                self.quality_flags.append("company_unknown")
        if self.salary_min is not None and self.salary_max is not None and self.salary_min > self.salary_max:
            raise ValueError("Salary minimum exceeds maximum")
        self.first_observed_date = min(self.first_observed_date, self.last_observed_date)
        if len(self.model_dump_json().encode()) > 262144:
            raise ValueError("Normalized record exceeds 256 KiB")
        return self


def posting(**fields: Any) -> RawPosting:
    """Validate one provider record (raises ValueError, like v1) and keep what the adapters read."""
    record = PostingRecord(**fields)
    source_fields = record.data_provenance.get("source_fields")
    return RawPosting(source_job_id=record.source_job_id, title=record.title, company_name=record.company_name,
                      original_url=record.original_url, application_url=record.application_url,
                      description=record.description, date_posted=record.date_posted, location=record.location,
                      remote_type=record.remote_type, salary_raw=record.salary_raw,
                      source_fields=source_fields if isinstance(source_fields, dict) else {})
