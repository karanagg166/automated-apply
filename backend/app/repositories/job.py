"""Repository for Job entity operations."""

from datetime import datetime
from uuid import UUID
from sqlalchemy import select
from backend.app.services.discovery_budget import insert_for
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.models.job import Job
from backend.app.repositories.base import BaseRepository


class JobRepository(BaseRepository[Job]):
    """Data access repository for jobs."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Job, session)

    async def get_by_url(self, job_url: str) -> Job | None:
        """Find job by unique canonical URL."""
        cleaned = job_url.strip()
        stmt = select(Job).where(Job.job_url == cleaned)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def save_or_update_job(
        self,
        title: str,
        job_url: str,
        source_platform: str,
        company_id: UUID | None = None,
        location: str | None = None,
        is_remote: bool = False,
        experience_level: str | None = None,
        salary_range: str | None = None,
        skills_required: list[str] | None = None,
        description: str | None = None,
        match_score: float | None = None,
        match_explanation: str | None = None,
        status: str = "discovered",
        date_posted: datetime | None = None,
    ) -> tuple[Job, bool]:
        """Save a new job or update existing posting if URL already exists.
        Returns (job, was_created).
        """
        existing = await self.get_by_url(job_url)
        if existing:
            # Update mutable fields without overwriting user review status if already changed
            if existing.status == "discovered" and status != "discovered":
                existing.status = status
            if match_score is not None:
                existing.match_score = match_score
            if match_explanation is not None:
                existing.match_explanation = match_explanation
            if description and not existing.description:
                existing.description = description
            await self.session.flush()
            return existing, False

        # A unique URL and conflict-safe insert handle concurrent legacy writers.
        values = dict(
            title=title.strip(),
            job_url=job_url.strip(),
            source_platform=source_platform.strip(),
            company_id=company_id,
            location=location,
            is_remote=is_remote,
            experience_level=experience_level,
            salary_range=salary_range,
            skills_required=skills_required or [],
            description=description,
            match_score=match_score,
            match_explanation=match_explanation,
            status=status,
            date_posted=date_posted,
        )
        inserted_id = (
            await self.session.execute(
                insert_for(self.session)(Job)
                .values(**values)
                .on_conflict_do_nothing(index_elements=[Job.job_url])
                .returning(Job.id)
            )
        ).scalar_one_or_none()
        if inserted_id:
            return await self.session.get(Job, inserted_id), True
        return await self.get_by_url(job_url), False

    async def list_jobs(
        self,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
    ) -> list[Job]:
        """List jobs with pagination and optional status filter."""
        stmt = select(Job).order_by(Job.created_at.desc()).limit(limit).offset(offset)
        if status:
            stmt = stmt.where(Job.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
