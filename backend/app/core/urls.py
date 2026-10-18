"""Validation only: candidate URLs are never fetched by this module."""
import ipaddress
from typing import Annotated
from urllib.parse import unquote

from pydantic import AfterValidator, HttpUrl, Field


def validate_public_https(value: HttpUrl) -> HttpUrl:
    host = (value.host or "").strip("[]").lower()
    if value.scheme != "https" or value.username is not None or value.password is not None:
        raise ValueError("A credential-free HTTPS URL is required")
    if value.port not in (None, 443) or not host or "." not in host or host.endswith((".localhost", ".local", ".internal", ".localdomain")):
        raise ValueError("A public HTTPS hostname is required")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Private and reserved addresses are not allowed")
    if any(ord(c) < 32 or c in "\\\r\n" for c in unquote(str(value))):
        raise ValueError("Unsafe URL characters")
    return value


PublicHTTPSURL = Annotated[HttpUrl, Field(max_length=2048), AfterValidator(validate_public_https)]
