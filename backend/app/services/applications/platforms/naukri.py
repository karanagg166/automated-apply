"""Naukri preparation pilot: validate saved URLs locally, hand off manually."""

from datetime import date, datetime, timezone
from urllib.parse import urlsplit

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
