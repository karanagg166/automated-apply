"""Owner-supplied employer URL preparation. Browser permission is checked separately."""

from backend.app.schemas.applications import Destination, PlatformCapability


class AssistedEmployerPlatform:
    def recognizes(self, job, observations=()):
        return job.source_platform == "manual_browser"

    def capabilities(self):
        return PlatformCapability(platform="manual_browser", browser_autofill="assisted_native_fields")

    def destination(self, job, observations=()):
        return Destination(
            application_url=job.application_url,
            kind="employer_external",
            valid=bool(job.application_url),
            source_confidence="unverified",
            warnings=[
                "Owner-supplied destination; confirm employer identity and automation permission",
                "Assisted filling only; owner submits manually",
            ],
        )
