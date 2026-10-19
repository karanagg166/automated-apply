"""REST transport checks independent of optional MCP transport."""

from urllib.parse import urlsplit


def transport_error(settings, scheme, host, origins):
    if settings.ENVIRONMENT not in {"staging", "production"}:
        return None
    # Forwarded headers are trusted only by uvicorn from explicitly configured ingress IPs.
    if settings.API_REQUIRE_TLS and scheme != "https":
        return "https_required"
    try:
        parsed = urlsplit("//" + host)
        if (not parsed.hostname or parsed.username or parsed.password or parsed.path
                or parsed.query or parsed.fragment or parsed.hostname.lower() not in settings.API_ALLOWED_HOSTS):
            return "untrusted_host"
        parsed.port  # Validate an optional port without accepting URL credentials/paths.
    except ValueError:
        return "untrusted_host"
    if len(origins) > 1 or (origins and origins[0] not in settings.API_ALLOWED_ORIGINS):
        return "untrusted_origin"
    return None
