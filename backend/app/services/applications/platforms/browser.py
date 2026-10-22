"""Owner-supplied employer URL preparation. Browser permission is checked separately."""

from urllib.parse import urlsplit

from backend.app.core.config import get_settings
from backend.app.schemas.applications import Destination, PlatformCapability
from backend.app.services.applications.platforms.base import safe_url


class AssistedEmployerPlatform:
    def recognizes(self, job, observations=()):
        return job.source_platform == "manual_browser"

    def capabilities(self):
        return PlatformCapability(
            platform="manual_browser", browser_autofill="assisted_native_fields"
        )

    def destination(self, job, observations=()):
        destination = safe_url(job.application_url)
        if not destination and job.application_url:
            settings = get_settings()
            parsed = urlsplit(job.application_url)
            mock = (
                settings.ENVIRONMENT == "testing"
                and parsed.scheme == "http"
                and parsed.hostname == "127.0.0.1"
                and not parsed.username
                and not parsed.password
                and not parsed.fragment
            )
            if mock:
                from backend.app.browser.runner import origin

                if origin(job.application_url) in settings.BROWSER_ALLOWED_ORIGINS:
                    destination = job.application_url
        return Destination(
            application_url=destination,
            kind="employer_external",
            valid=bool(destination) and job.status != "archived",
            source_confidence="unverified",
            warnings=[
                "Owner-supplied destination; confirm employer identity and automation permission",
                "Assisted filling only; owner submits manually",
            ],
        )
