"""Bounded authenticated discovery orchestration; provider failures are durable outcomes."""

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from backend.app.ai.usage import concurrency_limiter
from backend.app.core.config import get_settings
from backend.app.models.discovery import DiscoveryRun
from backend.app.repositories.candidate_profile import ProfileNotFoundError
from backend.app.schemas.discovery import (
    DiscoveryError,
    DiscoveryResult,
)
from backend.app.schemas.discovery import (
    DiscoveryStatus as Status,
)
from backend.app.schemas.normalized_job import NormalizedJob
from backend.app.services.candidate_profile_service import CandidateProfileService
from backend.app.services.discovery_budget import DiscoveryBudget, insert_for
from backend.app.services.job_ingestion import JobIngestionService
from backend.app.services.job_sources.factory import JobSourceFactory
from backend.app.services.job_sources.registry import resolve_source


class IdempotencyConflict(ValueError):
    pass


def iso_utc(value):
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    ).isoformat()


def run_output(run, settings=None):
    settings = settings or get_settings()
    started = datetime.fromisoformat(iso_utc(run.started_at))
    expired = run.status == "running" and started < datetime.now(
        timezone.utc
    ) - timedelta(seconds=settings.DISCOVERY_TIMEOUT_SECONDS + 120)
    return {
        "id": str(run.id),
        "source": run.source,
        "status": "recovery_required" if expired else run.status,
        "counts": run.counts,
        "errors": [
            "Execution lease expired; no automatic provider replay. Inspect saved runs and retained budget before a new owner-triggered run."
        ]
        if expired
        else run.errors,
        "started_at": iso_utc(run.started_at),
        "finished_at": iso_utc(run.finished_at) if run.finished_at else None,
        "provider_run_id": run.provider_run_id,
        "usage": run.usage,
        "rankings": run.rankings,
        "job_ids": (run.query_summary or {}).get("job_ids", []),
    }


def build_query(query, profile):
    if profile is None:
        return query
    prefs = profile.preferences
    return query.model_copy(
        update={
            "keywords": query.keywords or prefs.target_titles[:10],
            "locations": query.locations or prefs.preferred_locations[:10],
            "remote_preference": query.remote_preference or prefs.remote_preference,
            "employment_types": query.employment_types or prefs.employment_types,
        }
    )


class JobDiscoveryService:
    def __init__(self, session, factory, settings=None):
        self.session, self.factory = session, factory
        self.settings = settings or get_settings()
        self.budget = DiscoveryBudget(factory)

    async def claim(self, request):
        fingerprint = hashlib.sha256(
            json.dumps(
                request.model_dump(mode="json", exclude={"idempotency_key"}),
                sort_keys=True,
            ).encode()
        ).hexdigest()
        run_id = uuid.uuid4()
        async with self.factory() as session:
            statement = insert_for(session)(DiscoveryRun).values(
                id=run_id,
                source=request.source,
                request_hash=fingerprint,
                query_summary=request.query.model_dump(mode="json"),
                idempotency_key=request.idempotency_key,
                status="running",
            )
            inserted = (
                await session.execute(
                    statement.on_conflict_do_nothing().returning(DiscoveryRun.id)
                )
            ).scalar_one_or_none()
            if inserted is None:
                existing = await session.scalar(
                    select(DiscoveryRun).where(
                        DiscoveryRun.idempotency_key == request.idempotency_key
                    )
                )
                if existing.request_hash != fingerprint:
                    raise IdempotencyConflict(
                        "Idempotency key was used with a different request"
                    )
                return existing, False
            await session.commit()
        return run_id, True

    async def preview(self, request):
        config = resolve_source(request.source, self.settings)
        profile = None
        if request.use_profile:
            try:
                profile = await CandidateProfileService(self.session).get_profile()
            except ProfileNotFoundError:
                pass
        query = build_query(request.query, profile)
        estimate = None
        if config.adapter_type == "apify":
            raw = self.settings.APIFY_SOURCES.get(config.id, {})
            from backend.app.services.job_sources.apify_adapter import (
                ActorConfiguration,
            )

            try:
                actor = ActorConfiguration.model_validate(raw)
                estimate = (
                    actor.estimated_start_usd
                    + request.query.limit * actor.estimated_per_item_usd
                )
            except ValueError:
                pass
        return {
            "source": config.model_dump(),
            "query": query.model_dump(),
            "jobs": [],
            "provider_calls": 0,
            "estimated_usd": estimate,
            "estimate_only": True,
            "message": "Planning only; no providers called and no jobs or runs written",
        }

    async def run(self, request):
        config = resolve_source(request.source, self.settings)
        if (
            request.manual_jobs
            and config.adapter_type != "manual"
            and request.source != "manual"
        ):
            raise ValueError("Manual records require a manual import source")
        if len(request.manual_jobs) > request.query.limit:
            raise ValueError("Manual records exceed the query result cap")
        run_id, claimed = await self.claim(request)
        if not claimed:
            return run_output(run_id, self.settings)
        result = DiscoveryResult(source=request.source, status=Status.UPSTREAM_ERROR)
        counts = {
            "discovered": 0,
            "inserted": 0,
            "updated": 0,
            "duplicate": 0,
            "rejected": 0,
            "failed": 0,
            "skipped": 0,
        }
        rankings = []
        saved_job_ids = []
        started = phase_started = perf_counter()
        phase = "profile"
        timings = {}
        ingestion = None

        def next_phase(name):
            nonlocal phase, phase_started
            instant = perf_counter()
            timings[phase] = round(instant - phase_started, 6)
            phase, phase_started = name, instant

        def diagnostics():
            instant = perf_counter()
            return {
                "phase_seconds": {**timings, phase: round(instant - phase_started, 6)},
                "total_seconds": round(instant - started, 6),
                "last_phase": phase,
                "deadline_seconds": self.settings.DISCOVERY_TIMEOUT_SECONDS,
                "record_attempts": len(ingestion.record_seconds) if ingestion else 0,
                "max_record_seconds": round(max(ingestion.record_seconds, default=0), 6)
                if ingestion
                else 0,
            }

        try:
            async with asyncio.timeout(self.settings.DISCOVERY_TIMEOUT_SECONDS):
                profile = None
                if request.use_profile:
                    # Materialize the profile without holding a database connection
                    # during independent pacing claims or public HTTP. Runtime pools
                    # may have just one connection and a short idle transaction limit.
                    async with self.factory() as profile_session:
                        try:
                            profile = await CandidateProfileService(
                                profile_session
                            ).get_profile()
                        except ProfileNotFoundError:
                            pass
                query = build_query(request.query, profile)
                next_phase("concurrency_wait")
                async with concurrency_limiter(self.settings.DISCOVERY_MAX_CONCURRENCY):
                    next_phase("provider")
                    if config.adapter_type == "manual":
                        jobs, errors = [], []
                        for index, record in enumerate(request.manual_jobs):
                            try:
                                item = NormalizedJob.model_validate(record)
                                if (
                                    config.id != "manual"
                                    and item.source_name != config.id
                                ):
                                    raise ValueError("Manual source mismatch")
                                (
                                    item.source_verification_status,
                                    item.is_confirmed_current,
                                ) = "requires_review", False
                                item.data_provenance = {
                                    **item.data_provenance,
                                    "import_mode": "manual",
                                }
                                jobs.append(item)
                            except (ValueError, TypeError):
                                errors.append(
                                    f"Manual record {index}: invalid listing evidence"
                                )
                        result = DiscoveryResult(
                            source=request.source,
                            status=Status.PARTIAL
                            if errors
                            else Status.SUCCESS
                            if jobs
                            else Status.MANUAL_INPUT_REQUIRED,
                            jobs=jobs,
                            errors=errors,
                            rejected_count=len(errors),
                        )
                    elif config.adapter_type in ("restricted", "gmail"):
                        result = DiscoveryResult(
                            source=request.source,
                            status=Status.AUTH_REQUIRED
                            if config.id == "linkedin"
                            else Status.MANUAL_INPUT_REQUIRED,
                            errors=[
                                f"{config.id}: {config.availability}; use validated manual import"
                            ],
                        )
                    else:
                        options = (
                            {"budget": self.budget, "settings": self.settings}
                            if config.adapter_type == "apify"
                            else {"settings": self.settings}
                            if config.id in {"lever", "ashby"}
                            else {}
                        )
                        adapter = JobSourceFactory.get_adapter(
                            request.source, **options
                        )
                        from backend.app.services.job_sources.direct_api import (
                            DirectAdapter,
                        )
                        from backend.app.services.startup_discovery.connectivity import (
                            claim_access,
                        )

                        if (
                            isinstance(adapter, DirectAdapter)
                            and adapter._client is None
                            and not adapter.validate_configuration()
                        ):
                            await claim_access(self.factory, request.source)
                        result = await adapter.discover(
                            query,
                            allow_paid=request.allow_paid,
                            reservation_id=str(run_id),
                        )
                    if (
                        len(result.jobs) > query.limit
                        or any(job.source_name != request.source for job in result.jobs)
                        and config.adapter_type != "manual"
                    ):
                        result = DiscoveryResult(
                            source=request.source,
                            status=Status.UPSTREAM_ERROR,
                            errors=["Provider violated source identity or result cap"],
                        )
                    next_phase("filtering")
                    counts["discovered"] = len(result.jobs)
                    counts["rejected"] = result.rejected_count
                    counts["skipped"] = result.rejected_count
                    filtered = []
                    for job in result.jobs:
                        # Only explicit query mismatches are discarded; unknown fields stay visible.
                        if (
                            query.max_age_days
                            and job.date_posted
                            and job.date_posted
                            < datetime.now(timezone.utc)
                            - timedelta(days=query.max_age_days)
                        ):
                            counts["skipped"] += 1
                            continue
                        if request.query.keywords and not any(
                            k.casefold()
                            in (job.title + " " + (job.description or "")).casefold()
                            for k in request.query.keywords
                        ):
                            counts["skipped"] += 1
                            continue
                        explicit = request.query
                        if (
                            explicit.locations
                            and job.location
                            and not any(
                                loc.casefold() in job.location.casefold()
                                for loc in explicit.locations
                            )
                        ):
                            counts["skipped"] += 1
                            continue
                        if (
                            explicit.employment_types
                            and job.employment_type
                            and job.employment_type not in explicit.employment_types
                        ):
                            counts["skipped"] += 1
                            continue
                        if explicit.remote_preference not in (
                            None,
                            "any",
                        ) and job.remote_type not in (
                            "unknown",
                            explicit.remote_preference,
                        ):
                            counts["skipped"] += 1
                            continue
                        filtered.append(job)
                    if filtered:
                        next_phase("ingestion")
                        ingestion = JobIngestionService(self.session)
                        ingested = await ingestion.ingest_jobs(filtered)
                        saved_job_ids = ingested.job_ids
                        for name in (
                            "inserted",
                            "updated",
                            "duplicate",
                            "rejected",
                            "failed",
                            "skipped",
                        ):
                            counts[name] += getattr(ingested, name + "_count")
                        if profile:
                            next_phase("matching")
                            from backend.app.models.company import Company
                            from backend.app.models.job import Job
                            from backend.app.services.job_discovery_matcher import (
                                JobDiscoveryMatcher,
                            )

                            rows = (
                                await self.session.execute(
                                    select(Job, Company)
                                    .outerjoin(Company, Job.company_id == Company.id)
                                    .where(
                                        Job.id.in_(
                                            [
                                                uuid.UUID(value)
                                                for value in set(ingested.job_ids)
                                            ]
                                        )
                                    )
                                )
                            ).all()
                            for job, company in rows:
                                job_id = str(job.id)
                                match = JobDiscoveryMatcher(self.session).match(
                                    job, profile, company
                                )
                                rankings.append(
                                    {
                                        "job_id": job_id,
                                        "profile_version": profile.version,
                                        **match.model_dump(),
                                    }
                                )
                            rankings.sort(
                                key=lambda match: (
                                    -match["match_score"],
                                    match["job_id"],
                                )
                            )
                        result.errors.extend(ingested.errors)
                        if ingested.failed_count or ingested.rejected_count:
                            result.status = Status.PARTIAL
                next_phase("finalization")
                run = await self.session.get(DiscoveryRun, run_id)
                if (
                    result.status == Status.SUCCESS
                    and counts["discovered"]
                    and not counts["inserted"]
                    and not counts["updated"]
                ):
                    result.status = Status.NO_RESULTS
                run.query_summary = {**run.query_summary, "job_ids": saved_job_ids}
                run.rankings = rankings
                run.status, run.counts, run.errors = (
                    str(result.status),
                    counts,
                    result.errors[:100],
                )
                run.finished_at, run.provider_run_id, run.usage = (
                    datetime.now(timezone.utc),
                    result.provider_run_id,
                    {**result.usage, "diagnostics": diagnostics()},
                )
                # Job writes and successful final audit commit together.
                await self.session.commit()
                return run_output(run)
        except BaseException as exc:
            try:
                await self.session.rollback()
            except SQLAlchemyError:
                # A server restart/idle timeout can also break rollback. Discard
                # the connection before the independent failure audit borrows it.
                await self.session.invalidate()

            # Independent state update survives cancellation and any poisoned ingestion transaction.
            async def fail_run(error):
                async with self.factory() as session:
                    run = await session.get(DiscoveryRun, run_id)
                    # COMMIT acknowledgement can be lost after a durable success.
                    # Inspect the saved audit; never overwrite it or replay work.
                    if run.finished_at is not None:
                        return run_output(run, self.settings)
                    run.status = (
                        "cancelled"
                        if isinstance(error, asyncio.CancelledError)
                        else "upstream_error"
                        if isinstance(error, TimeoutError)
                        else str(error.status)
                        if isinstance(error, DiscoveryError)
                        else "failed"
                    )
                    run.errors = [
                        "Discovery cancelled"
                        if isinstance(error, asyncio.CancelledError)
                        else f"Discovery failed during {phase}; no batch changes committed"
                    ]
                    run.counts = {
                        **counts,
                        "inserted": 0,
                        "updated": 0,
                        "duplicate": 0,
                        "failed": max(1, counts["failed"]),
                    }
                    run.finished_at = datetime.now(timezone.utc)
                    run.provider_run_id = result.provider_run_id or run.provider_run_id
                    run.usage = {
                        **(result.usage or run.usage),
                        "diagnostics": diagnostics(),
                    }
                    await session.commit()
                    return run_output(run)

            output = await asyncio.shield(fail_run(exc))
            if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
                raise
            return output
