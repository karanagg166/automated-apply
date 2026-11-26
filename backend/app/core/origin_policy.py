"""Pure validators for operator-configured public origins and company source URLs.

``Settings`` normalizes ``BROWSER_ASSET_ORIGINS`` and ``COMPANY_SOURCE_URLS`` with
these functions. They used to live in the legacy ``backend.app.browser`` package,
which made every ``get_settings()`` caller (including all ``*_v2`` packages) load
frozen v1 code. The legacy modules keep their own identical copies until the v1
retirement; ``backend/tests/test_v2_isolation.py`` asserts the two stay in parity.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlsplit

RESTRICTED_HOSTS = frozenset(
    {
        "linkedin.com",
        "naukri.com",
        "wellfound.com",
        "instahyre.com",
        "internshala.com",
        "accounts.google.com",
    }
)


def asset_origin(value: str, *, testing: bool = False) -> str:
    """Return ``scheme://host:port`` for a credential-free public HTTPS origin."""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if (
            not value.isascii()
            or len(value) > 2048
            or any(ord(c) <= 32 or ord(c) == 127 or c == "\\" for c in value)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or "?" in value
            or "#" in value
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or parsed.port == 0
            or not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", host)
            or "." not in host
            or host.endswith((".local", ".internal", ".localhost", ".localdomain", "."))
            or (address is not None and not address.is_global and not (testing and host == "127.0.0.1"))
            or any(host == item or host.endswith("." + item) for item in RESTRICTED_HOSTS)
            or (
                parsed.scheme != "https"
                and not (testing and host == "127.0.0.1" and parsed.scheme == "http")
            )
        ):
            raise ValueError()
        return f"{parsed.scheme}://{host}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"
    except (ValueError, AttributeError):
        raise ValueError(
            "Asset origins require permitted credential-free HTTPS origins without paths or queries"
        ) from None


def source_url(value: str, *, testing: bool = False) -> str:
    """Return the normalized exact public company page URL (origin + path)."""
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
                re.IGNORECASE,
            )
            or path == "/robots.txt"
        ):
            raise ValueError()
        return origin + path
    except (ValueError, TypeError, AttributeError):
        raise ValueError(
            "Company sources require exact public HTTPS pages without credentials, query strings or account/API paths"
        ) from None
