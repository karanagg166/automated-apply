"""The sole platform pilot. Additional adapters must declare their actual capabilities."""

from backend.app.services.applications.platforms.naukri import NaukriPlatform
from backend.app.services.applications.platforms.owner_page import OwnerPagePlatform
from backend.app.services.applications.platforms.public_listing import (
    HOSTS,
    PublicListingPlatform,
)


def application_platforms():
    return [NaukriPlatform(), OwnerPagePlatform(), *(PublicListingPlatform(source) for source in HOSTS)]
