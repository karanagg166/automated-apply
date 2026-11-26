"""Naukri preparation pilot: validate saved URLs locally, hand off manually."""

import re
from datetime import date, datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

from backend.app.schemas.applications import Destination, PlatformCapability
from backend.app.services.applications.platforms.base import safe_url


def naukri_host(url):
    host = (urlsplit(url).hostname or "").lower()
    return host == "naukri.com" or host.endswith(".naukri.com")


def posting_unavailable(job, now=None):
    """An Apply control cannot override saved closed/expired posting evidence."""
    evidence = (getattr(job, "discovery_metadata", None) or {}).get("data_provenance", {})
    if getattr(job, "status", None) in {"archived", "closed"} or getattr(job, "source_verification_status", None) in {"expired", "invalid", "closed"} or evidence.get("posting_status") == "closed":
        return True
    valid_through = evidence.get("valid_through")
    if valid_through:
        try:
            return date.fromisoformat(valid_through) < (now or datetime.now(timezone.utc)).date()
        except (TypeError, ValueError):
            return True  # Corrupt expiry evidence needs review, never authorization.
    return False


class NaukriPlatform:
    def capabilities(self):
        return PlatformCapability(platform="naukri", browser_autofill="assisted_native_fields")

    def recognizes(self, job, observations=()):
        # A label alone is insufficient to assert the actual posting source.
        return (
            job.source_platform.casefold() == "naukri"
            or naukri_host(safe_url(job.job_url) or "")
            or any(
                source == "naukri" and naukri_host(safe_url(url) or "")
                for source, url in observations
            )
        )

    def destination(self, job, observations=()):
        original = safe_url(job.job_url)
        source_valid = bool(original and naukri_host(original))
        label_valid = job.source_platform.casefold() == "naukri"
        observed = next(
            (
                safe_url(url)
                for source, url in observations
                if source == "naukri" and naukri_host(safe_url(url) or "")
            ),
            None,
        )
        confidence = (
            "source_consistent"
            if (source_valid and label_valid) or observed
            else "source_conflict"
        )
        warnings = [
            "URL syntax was checked locally; availability and destination ownership have not been live verified"
        ]
        if confidence == "source_conflict":
            warnings.append(
                "Saved platform label and posting host disagree; confirm or correct the saved source"
            )
        # Only a stored application URL or the actual Naukri posting is usable. No fabricated path.
        raw = job.application_url or (job.job_url if source_valid else observed)
        url = safe_url(raw)
        if posting_unavailable(job):
            return Destination(
                application_url=url,
                kind="expired_or_invalid",
                source_confidence=confidence,
                warnings=warnings,
            )
        if not url:
            return Destination(
                kind="expired_or_invalid" if raw else "unknown",
                source_confidence=confidence,
                warnings=warnings,
            )
        return Destination(
            application_url=url,
            kind="naukri_hosted" if naukri_host(url) else "employer_external",
            valid=True,
            source_confidence=confidence,
            warnings=warnings,
        )


def normalized_url(url):
    checked = safe_url(url)
    if not checked:
        raise ValueError("public_https_job_url_required")
    p = urlsplit(checked)
    if p.hostname not in {"naukri.com", "www.naukri.com"}:
        raise ValueError("naukri_job_url_required")
    # Accept only a posting, never a login, search, profile or redirect endpoint.
    if not re.fullmatch(
        r"/job-listings-[a-zA-Z0-9%_-]+-[0-9]{10,20}/?", p.path
    ):
        raise ValueError("naukri_posting_path_required")
    return urlunsplit(("https", "www.naukri.com", p.path.rstrip("/"), "", ""))


def matching_job(job):
    """Use the latest explicit re-import without changing human-edited Job columns."""
    observed = job.discovery_metadata or {}
    view = SimpleNamespace(**vars(job))
    if observed.get("source_name") == "naukri":
        for target, source in {
            "title": "title", "description": "description", "location": "location",
            "skills_required": "skills_required", "remote_type": "remote_type",
            "employment_type": "employment_type", "salary_min": "salary_min",
            "experience_level": "experience_level",
            "salary_max": "salary_max", "salary_currency": "salary_currency",
            "salary_period": "salary_period",
            "application_url": "application_url",
        }.items():
            setattr(view, target, observed.get(source))
        view.is_remote = view.remote_type == "remote"
        try:
            view.date_posted = datetime.fromisoformat(observed["date_posted"])
        except (KeyError, TypeError, ValueError):
            view.date_posted = None
    return view


def reviewed_job_context(job, company):
    """Use one reviewed listing for matching, policy, packets and answers.

    Canonical Job/Company rows retain human history. An owner-reviewed employer
    correction is listing evidence, not proof that the old company's domain or
    enrichment belongs to the newly named employer.
    """
    view = matching_job(job)
    observed = job.discovery_metadata or {}
    if observed.get("source_name") != "naukri":
        return job, company
    name = observed.get("company_name")
    same_employer = bool(
        company and name
        and " ".join(company.name.casefold().split())
        == " ".join(name.casefold().split())
    )
    if not same_employer:
        company = SimpleNamespace(
            id=None, name=name, domain=None, metadata_={}
        ) if name else None
        view.company_id = None
    return view, company
