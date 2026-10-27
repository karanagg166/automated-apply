"""Local review packets for documented public feeds; no website is fetched or submitted."""

from urllib.parse import urlsplit

from backend.app.schemas.applications import Destination, PlatformCapability
from backend.app.services.applications.platforms.base import safe_url

HOSTS = {
    "greenhouse": {"boards.greenhouse.io", "job-boards.greenhouse.io"},
    "remotive": {"remotive.com"},
    "arbeitnow": {"www.arbeitnow.com", "arbeitnow.com"},
    "hacker_news": {"news.ycombinator.com"},
    "lever": {"jobs.lever.co", "jobs.eu.lever.co"},
    "ashby": {"jobs.ashbyhq.com"},
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
        if self.source in {"lever", "ashby"}:
            from backend.app.services.job_sources.public_ats import hosted_job_url

            try:
                parsed = urlsplit(original or "")
                board = parsed.path.strip("/").split("/")[0]
                hosted_job_url(original, board, self.source, parsed.netloc)
                hosted_job_url(destination, board, self.source, parsed.netloc, application=True)
                suffix = "/apply" if self.source == "lever" else "/application"
                consistent = consistent and urlsplit(destination).path.rstrip("/").removesuffix(suffix) == parsed.path.rstrip("/")
            except (ValueError, TypeError, IndexError):
                consistent = False
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
