"""URL eligibility only. A recognized ATS is never evidence of automation permission."""

import re
from urllib.parse import urlsplit

from backend.app.browser.asset_policy import RESTRICTED_HOSTS
from backend.app.services.applications.platforms.base import safe_url


def application_page_url(value, allowed_origins=()):
    url = safe_url(value)
    if not url:
        return None
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if parsed.query or parsed.fragment or any(
        host == restricted or host.endswith("." + restricted)
        for restricted in RESTRICTED_HOSTS | {"simplify.jobs", "mail.google.com"}
    ):
        return None
    path = parsed.path
    known = (
        host in {"boards.greenhouse.io", "job-boards.greenhouse.io"}
        and re.fullmatch(r"/[A-Za-z0-9_-]+/jobs/[A-Za-z0-9_-]+/?", path)
        or host in {"jobs.lever.co", "jobs.eu.lever.co", "jobs.ashbyhq.com"}
        and re.fullmatch(r"/[A-Za-z0-9_-]+/[A-Za-z0-9-]+(?:/(?:apply|application))?/?", path)
        or host == "jobs.smartrecruiters.com"
        and re.fullmatch(r"/[A-Za-z0-9_-]+/[0-9]+(?:-[A-Za-z0-9_%~-]+)?/?", path)
        or re.fullmatch(r"[a-z0-9-]+\.wd[0-9]+\.myworkdayjobs\.com", host)
        and "/job/" in path and len(path.strip("/").split("/")) >= 4
        or host == "docs.google.com" and path.startswith("/forms/")
    )
    # Generic employer forms require a separate, exact operator origin grant.
    origin = f"https://{host}:443"
    return url if known or origin in allowed_origins else None
