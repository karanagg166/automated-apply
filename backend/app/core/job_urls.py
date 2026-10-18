"""Deterministic URL identity; validation only, never follows submitted URLs."""

from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from pydantic import TypeAdapter
from backend.app.core.urls import PublicHTTPSURL

_validator = TypeAdapter(PublicHTTPSURL)
_TRACKING = {
    "fbclid",
    "gclid",
    "ref",
    "referrer",
    "source",
    "trk",
    "trackingid",
    "gh_src",
}


def canonical_job_url(value: str) -> str:
    parsed = urlsplit(str(_validator.validate_python(value)))
    host = parsed.hostname.lower()
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
    import re

    normalized = canonical_job_url(value)
    parsed = urlsplit(normalized)
    patterns = {
        "job-boards.greenhouse.io": r"/[^/]+/jobs/[0-9]+",
        "jobs.lever.co": r"/[^/]+/[A-Za-z0-9-]{10,}(?:/apply)?",
        "jobs.ashbyhq.com": r"/[^/]+/[A-Za-z0-9-]{10,}(?:/application)?",
    }
    pattern = patterns.get(parsed.hostname)
    if pattern and re.fullmatch(pattern, parsed.path):
        path = re.sub(r"/(?:apply|application)$", "", parsed.path)
        return urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))
    return None
