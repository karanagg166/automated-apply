"""Typed private setup, explicit serialization and non-destructive env seeding.

This module accepts a mapping supplied by its caller. It never reads .env, imports
global Settings, writes a configuration file, or infers personal information.
"""

import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Literal
from urllib.parse import parse_qs, urlsplit

from pydantic import Field, field_validator, model_validator

from backend.app.candidate_context.common import Contract, canonical_hash
from backend.app.core.urls import PublicHTTPSURL

LINK_NAMES = (
    "github",
    "linkedin",
    "leetcode",
    "codeforces",
    "codechef",
    "hackerrank",
    "portfolio",
    "naukri",
    "wellfound",
    "instahyre",
    "internshala",
    "yc",
    "gfg",
)
ENV_LINKS = {name: f"CANDIDATE_{name.upper()}_URL" for name in LINK_NAMES} | {
    "linkedin": "CANDIDATE_ORIGINAL_LINKEDIN_URL"
}
FILE_ID = r"[A-Za-z0-9_-]{10,200}"


def drive_identity(value: str, expected_id: str | None = None) -> tuple[str, str]:
    """Only a Drive binary-file viewer link. Never use the URL for network IO."""
    try:
        url = urlsplit(value)
        match = re.fullmatch(rf"/file/d/({FILE_ID})/view", url.path)
        query = parse_qs(url.query, strict_parsing=True, keep_blank_values=True)
        if (
            len(value) > 2048
            or not value.isascii()
            or not match
            or url.scheme != "https"
            or url.netloc != "drive.google.com"
            or url.fragment
            or set(query) - {"usp"}
            or len(query.get("usp", [])) > 1
            or any(ord(c) <= 32 for c in value)
        ):
            raise ValueError
        file_id = match.group(1)
        if expected_id and file_id != expected_id:
            raise ValueError
        return file_id, f"https://drive.google.com/file/d/{file_id}/view"
    except (ValueError, AttributeError):
        raise ValueError("exact_matching_drive_file_required") from None


class ResumeSource(Contract):
    canonical_url: str = Field(max_length=2048)
    file_id: str = Field(pattern=rf"^{FILE_ID}$")
    source_type: Literal["google_drive_authorized"] = "google_drive_authorized"
    # Opaque account binding, never an access token. Adapter verifies this identity.
    account_ref: str = Field(
        min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$"
    )
    generation: int = Field(default=1, ge=1)
    auto_sync_enabled: bool = False
    interval_minutes: int = Field(default=360, ge=60, le=10080)

    @model_validator(mode="after")
    def coherent_identity(self):
        _, canonical = drive_identity(self.canonical_url, self.file_id)
        object.__setattr__(self, "canonical_url", canonical)
        return self


class ProfileLinks(Contract):
    github: PublicHTTPSURL | None = None
    linkedin: PublicHTTPSURL | None = None
    leetcode: PublicHTTPSURL | None = None
    codeforces: PublicHTTPSURL | None = None
    codechef: PublicHTTPSURL | None = None
    hackerrank: PublicHTTPSURL | None = None
    portfolio: PublicHTTPSURL | None = None
    naukri: PublicHTTPSURL | None = None
    wellfound: PublicHTTPSURL | None = None
    instahyre: PublicHTTPSURL | None = None
    internshala: PublicHTTPSURL | None = None
    yc: PublicHTTPSURL | None = None
    gfg: PublicHTTPSURL | None = None
    other: tuple[PublicHTTPSURL, ...] = Field(default=(), max_length=20)

    @field_validator("*", mode="before")
    @classmethod
    def blank_is_missing(cls, value):
        return None if isinstance(value, str) and not value.strip() else value


class ProjectConfiguration(Contract):
    id: str = Field(pattern=r"^project-[a-z0-9][a-z0-9-]{0,30}$")
    name: str = Field(default="", max_length=200)
    priority: int = Field(ge=1, le=100)
    repository_url: PublicHTTPSURL | None = None
    live_url: PublicHTTPSURL | None = None
    tech_stack: tuple[str, ...] = Field(default=(), max_length=40)
    context_file: str = Field(default="", max_length=240)

    @field_validator("repository_url", "live_url", mode="before")
    @classmethod
    def blank_url(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("repository_url")
    @classmethod
    def exact_repository(cls, value):
        if value is not None and (
            value.host != "github.com"
            or value.query
            or value.fragment
            or not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?", value.path)
        ):
            raise ValueError("exact_github_repository_required")
        return value

    @field_validator("tech_stack")
    @classmethod
    def bounded_stack(cls, value):
        if any(not re.fullmatch(r"[\w .+#/-]{1,60}", item) for item in value):
            raise ValueError("invalid_technology")
        if len({item.casefold() for item in value}) != len(value):
            raise ValueError("duplicate_technology")
        return value

    @field_validator("context_file")
    @classmethod
    def safe_context_path(cls, value):
        if value:
            path = PurePosixPath(value)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in value
                or not value.startswith("candidate_context/")
                or path.suffix != ".md"
            ):
                raise ValueError("relative_candidate_context_markdown_required")
        return value


def empty_projects() -> tuple[ProjectConfiguration, ...]:
    return tuple(
        ProjectConfiguration(id=f"project-{i:02}", priority=i) for i in range(1, 4)
    )


class CandidateConfiguration(Contract):
    schema_version: Literal[1] = 1
    links: ProfileLinks = Field(default_factory=ProfileLinks)
    resume: ResumeSource | None = None
    projects: tuple[ProjectConfiguration, ...] = Field(
        default_factory=empty_projects, max_length=30
    )

    @model_validator(mode="after")
    def unique_projects(self):
        for field in ("id", "priority"):
            values = [getattr(project, field) for project in self.projects]
            if len(set(values)) != len(values):
                raise ValueError("duplicate_project_" + field)
        return self

    @property
    def content_hash(self) -> str:
        return canonical_hash(self)


def configuration_from_environment(values: Mapping[str, str]) -> CandidateConfiguration:
    """Use the existing CANDIDATE_* names; blanks remain missing, not personal facts."""
    import json

    if values.get("RESUME_SOURCE_TYPE", "") not in {"", "google_drive_authorized"}:
        raise ValueError("authorized_google_drive_source_required")

    links = {name: values.get(key) or None for name, key in ENV_LINKS.items()}
    links["other"] = json.loads(values.get("OTHER_PROFILE_URLS") or "[]")
    projects = []
    for i in range(1, 4):
        prefix = f"PROJECT_{i:02}_"
        projects.append(
            ProjectConfiguration.model_validate(
                dict(
                    id=f"project-{i:02}",
                    name=values.get(prefix + "NAME", ""),
                    priority=int(values.get(prefix + "PRIORITY") or i),
                    repository_url=values.get(prefix + "REPOSITORY_URL") or None,
                    live_url=values.get(prefix + "LIVE_URL") or None,
                    tech_stack=tuple(
                        v.strip()
                        for v in values.get(prefix + "TECH_STACK", "").split(",")
                        if v.strip()
                    ),
                    context_file=values.get(prefix + "CONTEXT_FILE", ""),
                )
            )
        )
    resume = None
    url = values.get("CANDIDATE_RESUME_DRIVE_URL", "").strip()
    file_id = values.get("CANDIDATE_RESUME_DRIVE_FILE_ID", "").strip()
    if url or file_id:
        if not url:
            url = f"https://drive.google.com/file/d/{file_id}/view"
        file_id, url = drive_identity(url, file_id or None)
        # Existing hourly setting stays authoritative; no conflicting minute alias.
        hours = int(values.get("RESUME_DRIVE_SYNC_INTERVAL_HOURS") or 6)
        enabled = values.get("RESUME_DRIVE_SYNC_ENABLED", "false").lower()
        if enabled not in {"true", "false"}:
            raise ValueError("boolean_sync_setting_required")
        resume = ResumeSource(
            canonical_url=url,
            file_id=file_id,
            account_ref=values.get("RESUME_DRIVE_ACCOUNT_REF", ""),
            interval_minutes=hours * 60,
            auto_sync_enabled=enabled == "true",
        )
    return CandidateConfiguration(
        links=ProfileLinks.model_validate(links),
        resume=resume,
        projects=tuple(projects),
    )


def seed_missing_environment(
    existing: Mapping[str, str], defaults: Mapping[str, str]
) -> dict[str, str]:
    """Return a copy; never overwrite a nonempty owner value or write a shared env."""
    result = dict(existing)
    for key, value in defaults.items():
        if not result.get(key, "").strip():
            result[key] = value
    return result


class ConfigurationChange(Contract):
    previous_hash: str | None
    current_hash: str
    changed_fields: tuple[str, ...]
    source: Literal["owner_dashboard", "private_environment", "owner_file"]
    actor_ref: str = Field(min_length=1, max_length=120)


def configuration_change(
    previous: CandidateConfiguration | None,
    current: CandidateConfiguration,
    *,
    source: Literal["owner_dashboard", "private_environment", "owner_file"],
    actor_ref: str,
) -> ConfigurationChange:
    before = previous.model_dump(mode="json") if previous else {}
    after = current.model_dump(mode="json")
    fields = tuple(sorted(key for key in after if before.get(key) != after[key]))
    return ConfigurationChange(
        previous_hash=previous.content_hash if previous else None,
        current_hash=current.content_hash,
        changed_fields=fields,
        source=source,
        actor_ref=actor_ref,
    )
