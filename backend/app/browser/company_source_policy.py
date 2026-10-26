"""Exact operator-reviewed public company documents, independent of browser access."""

import re
from urllib.parse import urlsplit

from backend.app.browser.asset_policy import asset_origin

AGENT = "AutomatedApply-CompanyContext"
MAX_HTML = 512 * 1024
MAX_ROBOTS = 64 * 1024


def source_url(value, *, testing=False):
    try:
        parsed = urlsplit(value)
        origin = asset_origin(f"{parsed.scheme}://{parsed.netloc}", testing=testing)
        path = parsed.path or "/"
        if (
            len(value) > 2048
            or not value.isascii()
            or parsed.query
            or parsed.fragment
            or "?" in value
            or "#" in value
            or not re.fullmatch(r"/[A-Za-z0-9/._~-]*", path)
            or path.startswith("//")
            or any(part in {".", ".."} for part in path.split("/"))
            or re.search(
                r"/(?:api|graphql|auth|oauth|login|signin|sign-in|account)(?:/|$)",
                path,
                re.I,
            )
            or path == "/robots.txt"
        ):
            raise ValueError()
        return origin + path
    except (ValueError, TypeError, AttributeError):
        raise ValueError(
            "Company sources require exact public HTTPS pages without credentials, query strings or account/API paths"
        ) from None


def robots_permit(text, path):
    """Conservative REP subset: every disallow group applies, allow never overrides.

    Supports bounded path wildcards/end markers. Unknown encoding/rate directives
    require manual reading. An allowed path never establishes access permission.
    """
    lines = text.splitlines()
    if len(lines) > 2000:
        return False
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            return False
        field, value = (part.strip() for part in line.split(":", 1))
        field = field.casefold()
        if field in {"crawl-delay", "request-rate"}:
            return False
        if field != "disallow" or not value:
            continue
        if len(value) > 512 or not value.startswith("/") or "%" in value:
            return False
        end = value.endswith("$")
        pattern = re.escape(value[:-1] if end else value).replace(r"\*", ".*")
        if re.match(pattern + ("$" if end else ""), path):
            return False
    return True
