"""Local review packets for documented public feeds; no website is fetched or submitted."""

from urllib.parse import urlsplit

from backend.app.schemas.applications import Destination, PlatformCapability
from backend.app.services.applications.platforms.base import safe_url

HOSTS = {
    "greenhouse": {"boards.greenhouse.io", "job-boards.greenhouse.io"},
    "remotive": {"remotive.com"},
    "arbeitnow": {"www.arbeitnow.com", "arbeitnow.com"},
    "hacker_news": {"news.ycombinator.com"},
}


class PublicListingPlatform:
    def __init__(self, source):
        self.source = source

    def capabilities(self):
        return PlatformCapability(platform=self.source)

    def recognizes(self, job, observations=()):
        return job.source_platform == self.source

    def destination(self, job, observations=()):
        original = safe_url(job.job_url)
        consistent = bool(
            original and urlsplit(original).hostname in HOSTS[self.source]
        )
        # A discussion comment or aggregate listing is a research reference, never an
        # invented official employer application destination. Explicit saved URL required.
        destination = safe_url(job.application_url)
        verified_listing = job.source_verification_status == "source_reported"
        valid = bool(
            consistent and destination and verified_listing and job.status != "archived"
        )
        return Destination(
            application_url=destination,
            kind="employer_external" if destination else "unknown",
            valid=valid,
            source_confidence="source_consistent" if consistent else "source_conflict",
            warnings=[
                "Verify employer ownership and vacancy on the official website before approval",
                "No form schema, upload, application receipt or submission is verified",
            ],
        )
