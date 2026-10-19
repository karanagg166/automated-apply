"""Savepoint-isolated ingestion preserving every human application decision."""

from datetime import timezone

from pydantic import BaseModel, Field
from sqlalchemy import case
from sqlalchemy.exc import SQLAlchemyError

from backend.app.models.discovery import JobSourceObservation
from backend.app.repositories.company import CompanyRepository
from backend.app.repositories.job import JobRepository
from backend.app.schemas.normalized_job import NormalizedJob
from backend.app.services.discovery_budget import insert_for
from backend.app.services.job_deduplication import (
    JobDeduplication,
    content_identity,
    ingestion_lock,
    observation_key,
)


class IngestionResult(BaseModel):
    total_received: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    duplicate_count: int = 0
    rejected_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    job_ids: list[str] = Field(default_factory=list)
    possible_duplicates: dict[str, list[str]] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class JobIngestionService:
    def __init__(self, session):
        self.session = session
        self.company_repo, self.job_repo = (
            CompanyRepository(session),
            JobRepository(session),
        )

    async def ingest_jobs(self, jobs, auto_commit=False):
        if len(jobs) > 100:
            raise ValueError("Ingestion is limited to 100 records")
        result = IngestionResult(total_received=len(jobs))
        await ingestion_lock(self.session)
        for index, raw in enumerate(jobs):
            try:
                item = NormalizedJob.model_validate(
                    raw.model_dump() if isinstance(raw, NormalizedJob) else raw
                )
            except (ValueError, TypeError):
                result.rejected_count += 1
                result.errors.append(f"Record {index}: normalization rejected")
                continue
            try:
                async with self.session.begin_nested():
                    company = None
                    deduplication = JobDeduplication(self.session)
                    job, reason, possible = await deduplication.resolve(item, None)
                    if job and job.company_id and not item.company_domain:
                        # Existing source/URL identity is stronger than a newly ambiguous name.
                        company = await self.company_repo.get_by_id(job.company_id)
                        if item.company_name and " ".join(
                            item.company_name.casefold().split()
                        ) != " ".join(company.name.casefold().split()):
                            raise ValueError(
                                "Changed employer name requires identity review"
                            )
                    elif item.company_name:
                        company, _ = await self.company_repo.get_or_create(
                            item.company_name, item.company_domain
                        )
                    if job is None:
                        job, reason, possible = await deduplication.resolve(
                            item, company.id if company else None
                        )
                    if (
                        job
                        and job.company_id
                        and company
                        and job.company_id != company.id
                    ):
                        raise ValueError(
                            "Canonical identity conflicts with company evidence"
                        )
                    created = job is None
                    if created:
                        job, created = await self.job_repo.save_or_update_job(
                            title=item.title,
                            job_url=item.canonical_url,
                            source_platform=item.source_name,
                            company_id=company.id if company else None,
                            location=item.location,
                            is_remote=item.is_remote is True,
                            experience_level=item.experience_level,
                            salary_range=(item.salary_raw or self.salary_display(item))[
                                :100
                            ]
                            or None,
                            skills_required=item.skills_required,
                            description=item.description,
                            date_posted=item.date_posted,
                        )
                    if not job.company_id and company:
                        job.company_id = company.id
                    # Never change title/status/score/explanation/notes on a re-observation.
                    if not job.canonical_key:
                        job.canonical_key = item.canonical_url
                    if not job.content_identity:
                        job.content_identity = content_identity(item, job.company_id)
                    if not job.description:
                        job.description = item.description
                    for field in ("application_url", "employment_type"):
                        if (
                            getattr(job, field) is None
                            and getattr(item, field) is not None
                        ):
                            setattr(job, field, getattr(item, field))
                    # Salary is one evidence group; never combine incompatible source units/currencies.
                    salary_fields = (
                        "salary_min",
                        "salary_max",
                        "salary_currency",
                        "salary_period",
                    )
                    if all(getattr(job, field) is None for field in salary_fields):
                        for field in salary_fields:
                            setattr(job, field, getattr(item, field))
                    if (
                        job.remote_type in (None, "unknown")
                        and item.remote_type != "unknown"
                    ):
                        job.remote_type = item.remote_type
                        job.is_remote = (
                            item.is_remote is True
                        )  # Legacy bool retained; v2 uses remote_type.
                    job.first_observed_at = (
                        job.first_observed_at or item.first_observed_date
                    )
                    previous = job.last_observed_at
                    if previous and previous.tzinfo is None:
                        previous = previous.replace(tzinfo=timezone.utc)
                    job.last_observed_at = (
                        max(previous, item.last_observed_date)
                        if previous
                        else item.last_observed_date
                    )
                    if created:
                        job.source_verification_status = item.source_verification_status
                        job.discovery_metadata = item.model_dump(mode="json")
                    values = dict(
                        job_id=job.id,
                        source=item.source_name,
                        identity_key=observation_key(item),
                        source_job_id=item.source_job_id,
                        original_url=item.original_url,
                        first_observed_at=item.first_observed_date,
                        last_observed_at=item.last_observed_date,
                        provenance={
                            **item.data_provenance,
                            "deduplication": reason,
                            "quality_flags": item.quality_flags,
                        },
                        verification_status=item.source_verification_status,
                    )
                    statement = insert_for(self.session)(JobSourceObservation).values(
                        **values
                    )
                    await self.session.execute(
                        statement.on_conflict_do_update(
                            index_elements=[
                                JobSourceObservation.source,
                                JobSourceObservation.identity_key,
                            ],
                            set_={
                                "last_observed_at": case(
                                    (
                                        JobSourceObservation.last_observed_at
                                        > item.last_observed_date,
                                        JobSourceObservation.last_observed_at,
                                    ),
                                    else_=item.last_observed_date,
                                ),
                                "provenance": values["provenance"],
                                "verification_status": values["verification_status"],
                                "original_url": values["original_url"],
                            },
                        )
                    )
                    if company and item.company_intelligence:
                        company.metadata_ = {
                            **(company.metadata_ or {}),
                            "startup_discovery": {
                                **item.company_intelligence,
                                "observed_at": item.last_observed_date.isoformat(),
                                "source_url": item.original_url,
                            },
                        }
                    await self.session.flush()
                    saved_id = str(job.id)
                result.job_ids.append(saved_id)
                if possible:
                    result.possible_duplicates[saved_id] = possible
                if created:
                    result.inserted_count += 1
                else:
                    result.updated_count += 1
                    result.duplicate_count += 1
            except ValueError:
                result.rejected_count += 1
                result.errors.append(f"Record {index}: conflicting identity evidence")
            except SQLAlchemyError:
                result.failed_count += 1
                result.errors.append(f"Record {index}: database persistence failed")
        result.skipped_count = result.rejected_count + result.failed_count
        if auto_commit:
            await self.session.commit()
        return result

    @staticmethod
    def salary_display(item):
        if item.salary_min is None and item.salary_max is None:
            return ""
        currency = item.salary_currency or ""
        if item.salary_min is not None and item.salary_max is not None:
            return (
                f"{currency}{item.salary_min:,.0f} - {currency}{item.salary_max:,.0f}"
            )
        return f"{currency}{item.salary_min if item.salary_min is not None else item.salary_max:,.0f}"
