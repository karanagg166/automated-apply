"""An explicitly selected browser page is a local draft, not a verified vacancy."""

import re
from urllib.parse import parse_qsl, urlsplit

from backend.app.schemas.applications import Destination, PlatformCapability
from backend.app.services.applications.platforms.base import safe_url


def manual_page_url(value, settings=None):
    url = safe_url(value)
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.fragment:
        return None
    host = parsed.hostname or ""
    if host in {"naukri.com", "www.naukri.com"}:
        from backend.app.execution.naukri import normalized_url
        try:
            normalized_url(url)
        except ValueError:
            return None
        return url if not parsed.query else None
    zoho = bool(re.fullmatch(r"[a-z0-9][a-z0-9-]*\.zohorecruit\.(?:in|com)", host))
    if zoho:
        if not re.fullmatch(r"/jobs/Careers/[0-9]+/[A-Za-z0-9_-]+/?", parsed.path):
            return None
        query = parse_qsl(parsed.query, keep_blank_values=True)
        if len(query) > 2 or len({key for key, _ in query}) != len(query):
            return None
        if any(key not in {"source", "ref"} or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", val) for key, val in query):
            return None
    else:
        from backend.app.browser.site_policy import application_page_url
        from backend.app.core.config import get_settings

        settings = settings or get_settings()
        return application_page_url(url, settings.BROWSER_ALLOWED_ORIGINS)
    return url


class OwnerPagePlatform:
    def recognizes(self, job, observations=()):
        return job.source_platform == "owner_extension"

    def capabilities(self):
        return PlatformCapability(platform="owner_extension")

    def destination(self, job, observations=()):
        url = manual_page_url(job.application_url)
        return Destination(
            application_url=url,
            kind="employer_external" if url else "unknown",
            valid=bool(url and job.job_url == url and job.status != "archived"),
            source_confidence="unverified",
            warnings=[
                "Owner-selected page; employer identity and vacancy are unverified",
                "Manual extension answers only; upload and submission remain owner-operated",
            ],
        )
