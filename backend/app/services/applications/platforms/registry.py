"""The sole platform pilot. Additional adapters must declare their actual capabilities."""

from backend.app.services.applications.platforms.naukri import NaukriPlatform


def application_platforms():
    return [NaukriPlatform()]
