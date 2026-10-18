"""Job ingestion service for processing and persisting NormalizedJob records."""

from typing import Any
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.logging import logger
from backend.app.models.job import Job
from backend.app.repositories.company import CompanyRepository
from backend.app.repositories.job import JobRepository
from backend.app.schemas.normalized_job import NormalizedJob


class IngestionResult(BaseModel):
    """Result summary of a batch job ingestion run."""

    total_received: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    job_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class JobIngestionService:
    """Service to ingest, deduplicate, and persist normalized job listings."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.company_repo = CompanyRepository(session)
        self.job_repo = JobRepository(session)

    async def ingest_jobs(
        self,
        jobs: list[NormalizedJob],
        auto_commit: bool = False,
    ) -> IngestionResult:
        """Ingest a list of NormalizedJob items into PostgreSQL (job_agent schema).

        Performs:
        1. Company discovery or creation
        2. Deduplication by canonical job_url
        3. Persistence of salary, skills, provenance, and verification flags
        """
        result = IngestionResult(total_received=len(jobs))

        for item in jobs:
            try:
                # 1. Ensure company exists or create
                company, _ = await self.company_repo.get_or_create(
                    name=item.company_name,
                    domain=item.company_domain,
                )

                # 2. Format salary if present
                salary_display = item.salary_raw
                if not salary_display and (item.salary_min or item.salary_max):
                    cur = item.salary_currency or "$"
                    if item.salary_min and item.salary_max:
                        salary_display = f"{cur}{item.salary_min:,.0f} - {cur}{item.salary_max:,.0f}"
                    elif item.salary_min:
                        salary_display = f"From {cur}{item.salary_min:,.0f}"
                    elif item.salary_max:
                        salary_display = f"Up to {cur}{item.salary_max:,.0f}"

                # 3. Save or update job with deduplication
                job, was_created = await self.job_repo.save_or_update_job(
                    title=item.title,
                    job_url=item.original_url,
                    source_platform=item.source_name,
                    company_id=company.id,
                    location=item.location,
                    is_remote=item.is_remote,
                    experience_level=item.experience_level,
                    salary_range=salary_display,
                    skills_required=item.skills_required,
                    description=item.description,
                    status="discovered",
                    date_posted=item.date_posted,
                )

                result.job_ids.append(str(job.id))
                if was_created:
                    result.inserted_count += 1
                else:
                    result.updated_count += 1

            except Exception as e:
                err_msg = f"Failed to ingest job '{item.title}' from {item.source_name}: {e}"
                logger.error(err_msg)
                result.errors.append(err_msg)
                result.skipped_count += 1

        if auto_commit:
            await self.session.commit()

        logger.info(
            f"Job Ingestion Completed: {result.inserted_count} new, {result.updated_count} updated, "
            f"{result.skipped_count} skipped across {result.total_received} items."
        )
        return result
