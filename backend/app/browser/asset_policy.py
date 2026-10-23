"""Operator-approved public assets. No website text can extend this policy."""

import hashlib
import ipaddress
import json
import re
from urllib.parse import unquote, urlsplit

RESTRICTED_HOSTS = {
    "linkedin.com",
    "naukri.com",
    "wellfound.com",
    "instahyre.com",
    "internshala.com",
    "accounts.google.com",
}
MAX_ASSET_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_REQUESTS = 128
MAX_PARALLEL = 4
RESPONSE_HEADERS = {
    "content-type",
    "cache-control",
    "access-control-allow-origin",
    "access-control-allow-credentials",
    "cross-origin-resource-policy",
    "cross-origin-embedder-policy",
    "content-security-policy",
    "x-content-type-options",
}
SUFFIXES = {
    "script": (".js", ".mjs"),
    "stylesheet": (".css",),
    "font": (".woff", ".woff2", ".ttf", ".otf"),
}
MIMES = {
    "script": {
        "application/javascript",
        "text/javascript",
        "application/ecmascript",
        "text/ecmascript",
    },
    "stylesheet": {"text/css"},
    "font": {
        "font/woff",
        "font/woff2",
        "font/ttf",
        "font/otf",
        "application/font-woff",
        "application/x-font-ttf",
        "application/x-font-opentype",
    },
}


def asset_origin(value, *, testing=False):
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
            or host.endswith((".local", ".internal", ".localhost", ".localdomain"))
            or (
                address is not None
                and not address.is_global
                and not (testing and host == "127.0.0.1")
            )
            or host.endswith(".")
            or any(
                host == item or host.endswith("." + item) for item in RESTRICTED_HOSTS
            )
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


def asset_target(url, kind, *, testing=False):
    try:
        parsed = urlsplit(url)
        base = asset_origin(f"{parsed.scheme}://{parsed.netloc}", testing=testing)
        path = unquote(parsed.path)
        if (
            len(url) > 2048
            or not url.isascii()
            or not parsed.path.startswith("/")
            or parsed.path.startswith("//")
            or parsed.query
            or parsed.fragment
            or "?" in url
            or "#" in url
            or any(ord(c) <= 32 or ord(c) == 127 or c in "\\?#" for c in path)
            or any(part in {".", ".."} for part in path.split("/"))
            or kind not in SUFFIXES
            or not path.lower().endswith(SUFFIXES[kind])
        ):
            raise ValueError()
        return base, parsed
    except (ValueError, AttributeError):
        raise ValueError("Unsupported public asset") from None


def policy(settings):
    data = {
        "origins": sorted(
            set(
                asset_origin(value, testing=settings.ENVIRONMENT == "testing")
                for value in settings.BROWSER_ASSET_ORIGINS
            )
        ),
        "kinds": sorted(SUFFIXES),
        "max_asset_bytes": MAX_ASSET_BYTES,
        "max_total_bytes": MAX_TOTAL_BYTES,
        "max_requests": MAX_REQUESTS,
        "max_parallel": MAX_PARALLEL,
        "phase": "initial_load_before_analysis_or_takeover",
        "credentials": False,
    }
    return {
        **data,
        "digest": hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest(),
    }
