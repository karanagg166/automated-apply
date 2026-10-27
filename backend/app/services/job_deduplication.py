"""Conservative identity hierarchy. Similarity alone never merges jobs."""

import hashlib
import re

from sqlalchemy import or_, select, text

from backend.app.core.job_urls import canonical_job_url
from backend.app.models.discovery import JobSourceObservation
from backend.app.models.job import Job


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def folded(value):
    return " ".join(re.sub(r"<[^>]*>", " ", value or "").casefold().split())


def observation_key(item):
    return digest(
        "id:"
        + str(item.data_provenance.get("board_token", ""))
        + ":"
        + item.source_job_id
        if item.source_job_id
        else "url:" + canonical_job_url(item.original_url)
    )


def content_identity(item, company_id):
    description = folded(item.description)
    if (
        not company_id
        or not item.company_domain
        or not item.location
        or len(description) < 200
        or item.remote_type == "unknown"
    ):
        return None
    return digest(
        "|".join(
            (
                str(company_id),
                folded(item.title),
                folded(item.location),
                item.remote_type,
                description,
            )
        )
    )


async def ingestion_lock(session):
    # Small bounded personal ingestion batches: serialize identity resolution across workers.
    # Unique keys remain the final database guard. The lock is transaction-scoped.
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(240204)"))


class JobDeduplication:
    def __init__(self, session):
        self.session = session

    async def resolve(self, item, company_id):
        observation = await self.session.scalar(
            select(JobSourceObservation).where(
                JobSourceObservation.source == item.source_name,
                JobSourceObservation.identity_key == observation_key(item),
            )
        )
        if observation:
            job = await self.session.get(Job, observation.job_id)
            if company_id and job.company_id and company_id != job.company_id:
                raise ValueError("Source identity conflicts with company evidence")
            return job, "source_identity", []
        key = item.canonical_url
        job = await self.session.scalar(
            select(Job).where(or_(Job.canonical_key == key, Job.job_url == key))
        )
        if job:
            return job, "canonical_url", []
        # Legacy URLs remain unchanged by migration. Normalize them only during observed ingestion.
        legacy = (
            await self.session.scalars(select(Job).where(Job.canonical_key.is_(None)))
        ).all()
        for candidate in legacy:
            try:
                if canonical_job_url(candidate.job_url) == key:
                    return candidate, "legacy_canonical_url", []
            except ValueError:
                continue
        return await self.resolve_content(item, company_id)

    async def resolve_content(self, item, company_id):
        """Continue after source/URL checks under the same ingestion transaction lock."""
        identity = content_identity(item, company_id)
        if identity:
            job = await self.session.scalar(
                select(Job).where(Job.content_identity == identity)
            )
            if job:
                return job, "company_role_location_content", []
        possible = []
        if company_id:
            candidates = (
                await self.session.scalars(
                    select(Job).where(Job.company_id == company_id).limit(500)
                )
            ).all()
            possible = [
                str(j.id) for j in candidates if folded(j.title) == folded(item.title)
            ]
        return None, "new", possible[:20]
