"""Future platforms implement this interface without changing packet business logic."""

from typing import Protocol

from pydantic import TypeAdapter, ValidationError

from backend.app.core.urls import PublicHTTPSURL
from backend.app.schemas.applications import Destination, PlatformCapability


class ApplicationPlatform(Protocol):
    def capabilities(self) -> PlatformCapability: ...

    def destination(self, job, observations=()) -> Destination: ...

    def recognizes(self, job, observations=()) -> bool: ...


def safe_url(value):
    if not value:
        return None
    try:
        return str(TypeAdapter(PublicHTTPSURL).validate_python(value))
    except (ValidationError, ValueError):
        return None
