"""Bounded standalone worker; no recurring work is attached to API startup.

Claims before dispatch may be recovered. Dispatched outcomes are never replayed.
The schedule row provides cross-process admission (two slots); execution fences
and a final lease check protect the entire ingestion/matching transaction.
"""

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import func, select

from backend.app.automation.models import AutomationExecution, AutomationMatch
from backend.app.automation.schemas import ScheduleConfiguration
from backend.app.automation.store import (
    approved_profile,
    blockers,
    configuration,
    enqueue,
    instant,
    schedule,
)
from backend.app.dashboard.models import OwnerPreference
from backend.app.db.safety import require_session_target
from backend.app.models.company import Company
from backend.app.models.discovery import DiscoveryRun, JobSourceObservation
from backend.app.models.job import Job
from backend.app.models.startup import CompanySourceObservation, ProviderAccessWindow
from backend.app.schemas.candidate_profile import CandidateProfileRead
from backend.app.schemas.discovery import (
    DiscoveryError,
    DiscoveryQuery,
    DiscoveryResult,
    DiscoveryStatus,
)
from backend.app.services.discovery_budget import insert_for
from backend.app.services.job_deduplication import observation_key
from backend.app.services.job_discovery_matcher import JobDiscoveryMatcher
from backend.app.services.job_ingestion import JobIngestionService
from backend.app.services.job_sources.factory import JobSourceFactory
from backend.app.services.startup_discovery.connectivity import reserve_access
from backend.app.services.startup_discovery.intelligence import company_size
from backend.app.services.startup_discovery.normalizer import utc
from backend.app.services.startup_discovery.source_registry import INTERVALS

LEASE_SECONDS = 240
MAX_ACTIVE = 2


class LostLease(RuntimeError):
    pass


class DiscoveryWorker:
    def __init__(self, factory, settings, *, clock=None, adapter_factory=None):
        self.factory, self.settings, self.clock = factory, settings, clock
        self.adapter_factory = adapter_factory or JobSourceFactory.get_adapter
        if (
            adapter_factory is not None or clock is not None
        ) and settings.ENVIRONMENT != "testing":
            raise ValueError("Fixture adapters and clocks require isolated test mode")

    def guard(self, session):
        require_session_target(session, self.settings)
        if session.bind.dialect.name != "postgresql":
            raise ValueError("Automation execution requires PostgreSQL")

    async def claim(self):
        async with self.factory() as session, session.begin():
            self.guard(session)
            row = await schedule(session, lock=True)
            now = await instant(session, self.clock)
            row.heartbeat_at = now
            expired = (
                await session.scalars(
                    select(AutomationExecution)
                    .where(
                        AutomationExecution.state.in_(["claimed", "running"]),
                        AutomationExecution.lease_until <= now,
                    )
                    .with_for_update()
                )
            ).all()
            for task in expired:
                task.fence += 1
                if (
                    task.state == "claimed"
                    and task.attempts < 3
                    and row.enabled
                    and task.schedule_version == row.version
                ):
                    task.state, task.diagnostic = (
                        "pending",
                        "claim_expired_before_dispatch",
                    )
                    task.available_at = now + timedelta(seconds=30 * task.attempts)
                else:
                    task.state, task.diagnostic = (
                        "blocked",
                        "provider_outcome_unknown"
                        if task.state == "running"
                        else "claim_recovery_exhausted",
                    )
                    task.finished_at = now
                task.lease_until = None
            await session.flush()
            config = configuration(row)
            if not row.enabled or blockers(config, self.settings):
                return None
            if row.next_run_at is None or utc(row.next_run_at) <= now:
                key = (
                    "schedule_"
                    + str(row.version)
                    + "_"
                    + (
                        utc(row.next_run_at).isoformat()
                        if row.next_run_at
                        else now.isoformat()
                    )
                )
                await enqueue(session, row, key, "scheduled", now)
                row.last_run_at = now
                # Missed intervals coalesce to one run; no catch-up burst after restart.
                row.next_run_at = now + timedelta(seconds=config.interval_seconds)
            active = await session.scalar(
                select(func.count())
                .select_from(AutomationExecution)
                .where(AutomationExecution.state.in_(["claimed", "running"]))
            )
            if active >= MAX_ACTIVE:
                return None
            tasks = (
                await session.scalars(
                    select(AutomationExecution)
                    .where(
                        AutomationExecution.state == "pending",
                        AutomationExecution.available_at <= now,
                    )
                    .order_by(AutomationExecution.created_at, AutomationExecution.id)
                    .with_for_update(skip_locked=True)
                    .limit(8)
                )
            ).all()
            for task in tasks:
                if task.schedule_version != row.version:
                    task.state, task.diagnostic, task.finished_at = (
                        "blocked",
                        "configuration_changed",
                        now,
                    )
                    continue
                window = await session.get(ProviderAccessWindow, task.source)
                if window and utc(window.next_allowed_at) > now:
                    task.available_at = window.next_allowed_at
                    task.diagnostic = "source_cooldown"
                    continue
                task.state, task.fence = "claimed", task.fence + 1
                task.attempts += 1
                task.lease_until = now + timedelta(seconds=LEASE_SECONDS)
                return task.id, task.fence
        return None

    async def dispatch(self, identity):
        task_id, fence = identity
        async with self.factory() as session, session.begin():
            row = await schedule(session, lock=True)
            task = await session.scalar(
                select(AutomationExecution)
                .where(AutomationExecution.id == task_id)
                .with_for_update()
            )
            now = await instant(session, self.clock)
            if (
                task.fence != fence
                or task.state != "claimed"
                or utc(task.lease_until) <= now
            ):
                raise LostLease()
            config = ScheduleConfiguration.model_validate(task.configuration)
            if (
                not row.enabled
                or task.schedule_version != row.version
                or blockers(config, self.settings)
                or task.source not in config.sources
                or task.source not in INTERVALS
            ):
                task.state, task.diagnostic, task.finished_at = (
                    "blocked",
                    "configuration_changed",
                    now,
                )
                return None
            # Shared quota and dispatch marker commit atomically before the call.
            # No nested connection is needed with the conservative two-slot pool.
            try:
                await reserve_access(session, task.source, now)
            except DiscoveryError:
                task.state, task.diagnostic = "pending", "source_cooldown"
                window = await session.get(ProviderAccessWindow, task.source)
                task.available_at = window.next_allowed_at
                task.lease_until = None
                return None
            task.state, task.started_at, task.diagnostic = "running", now, None
            return task.source, config

    async def execute(self, identity):
        dispatched = await self.dispatch(identity)
        if not dispatched:
            return
        source, config = dispatched
        try:
            adapter = self.adapter_factory(source)
            async with asyncio.timeout(self.settings.DISCOVERY_TIMEOUT_SECONDS):
                result = await adapter.discover(
                    DiscoveryQuery(limit=config.limit), allow_paid=False
                )
            if len(result.jobs) > config.limit or any(
                job.source_name != source for job in result.jobs
            ):
                result = DiscoveryResult(
                    source=source,
                    status=DiscoveryStatus.UPSTREAM_ERROR,
                    errors=["invalid_provider_evidence"],
                )
        except asyncio.CancelledError:
            # Dispatch was committed: preserve unknown outcome, never replay it.
            await asyncio.shield(self.fail(identity, "provider_outcome_unknown"))
            raise
        except Exception as error:
            result = DiscoveryResult(
                source=source,
                status=DiscoveryStatus.UPSTREAM_ERROR,
                errors=[
                    "provider_timeout"
                    if isinstance(error, TimeoutError)
                    else "provider_error"
                ],
            )
        try:
            await self.complete(
                identity,
                result,
                getattr(locals().get("adapter"), "retry_after_seconds", None),
            )
        except LostLease:
            return
        except asyncio.CancelledError:
            await asyncio.shield(self.fail(identity, "provider_outcome_unknown"))
            raise
        except Exception:
            await self.fail(identity, "persistence_failed_after_dispatch")

    async def fail(self, identity, diagnostic):
        async with self.factory() as session, session.begin():
            task = await session.scalar(
                select(AutomationExecution)
                .where(AutomationExecution.id == identity[0])
                .with_for_update()
            )
            if task and task.fence == identity[1] and task.state == "running":
                task.state, task.diagnostic = "blocked", diagnostic
                task.finished_at = await instant(session, self.clock)
                task.lease_until = None

    async def complete(self, identity, result, retry_after=None):
        async with self.factory() as session, session.begin():
            row = await schedule(session, lock=True)
            task = await session.scalar(
                select(AutomationExecution)
                .where(AutomationExecution.id == identity[0])
                .with_for_update()
            )
            now = await instant(session, self.clock)
            if (
                task.fence != identity[1]
                or task.state != "running"
                or utc(task.lease_until) <= now
            ):
                raise LostLease()
            deadline = utc(task.lease_until)
            if not row.enabled or task.schedule_version != row.version:
                task.state, task.diagnostic, task.finished_at = (
                    "blocked",
                    "configuration_changed",
                    now,
                )
                task.lease_until = None
                return
            config = ScheduleConfiguration.model_validate(task.configuration)
            accepted_states = {
                DiscoveryStatus.SUCCESS,
                DiscoveryStatus.NO_RESULTS,
                DiscoveryStatus.PARTIAL,
            }
            # Failed adapters cannot smuggle records into a successful ingestion.
            jobs = result.jobs if result.status in accepted_states else []
            ingested = await JobIngestionService(session).ingest_jobs(jobs)
            profile = await approved_profile(session, config, lock=True)
            rankings = []
            if profile:
                profile = CandidateProfileRead.model_validate(profile)
                for job_id in set(ingested.job_ids):
                    job = await session.get(Job, uuid.UUID(job_id))
                    company = (
                        await session.get(Company, job.company_id)
                        if job.company_id
                        else None
                    )
                    # Include current normalized listing evidence as well as saved facts.
                    observed_keys = set(
                        (
                            await session.scalars(
                                select(JobSourceObservation.identity_key).where(
                                    JobSourceObservation.job_id == job.id,
                                    JobSourceObservation.source == task.source,
                                )
                            )
                        ).all()
                    )
                    listings = [j for j in jobs if observation_key(j) in observed_keys]
                    evidence = [
                        j.model_dump(
                            mode="json",
                            exclude={
                                "first_observed_date",
                                "last_observed_date",
                                "retrieved_at",
                            },
                        )
                        for j in listings
                    ]
                    evidence.sort(key=lambda item: json.dumps(item, sort_keys=True))
                    company_evidence = (
                        {
                            "name": company.name,
                            "domain": company.domain,
                            "metadata": company.metadata_,
                        }
                        if company
                        else None
                    )
                    if company_evidence is not None:
                        size_observations = (
                            await session.scalars(
                                select(CompanySourceObservation)
                                .where(
                                    CompanySourceObservation.company_id == company.id,
                                )
                                .order_by(CompanySourceObservation.observed_at.desc())
                                .limit(100)
                            )
                        ).all()
                        company_evidence["size"] = company_size(size_observations)
                    digest = hashlib.sha256(
                        json.dumps(
                            {
                                "job": {
                                    c.name: getattr(job, c.name)
                                    for c in Job.__table__.columns
                                    if c.name
                                    not in {
                                        "created_at",
                                        "updated_at",
                                        "first_observed_at",
                                        "last_observed_at",
                                        "match_score",
                                        "match_explanation",
                                        "application_status",
                                        "notes",
                                        "status",
                                    }
                                },
                                "company": company_evidence,
                                "listing": evidence,
                            },
                            sort_keys=True,
                            default=str,
                        ).encode()
                    ).hexdigest()
                    cached = await session.get(AutomationMatch, job.id)
                    if (
                        cached
                        and cached.profile_id == profile.id
                        and cached.profile_version == profile.version
                        and cached.evidence_hash == digest
                    ):
                        match = cached.result
                    else:
                        latest = max(
                            listings,
                            key=lambda j: (j.last_observed_date, j.original_url),
                            default=None,
                        )
                        match_job = job
                        if latest:
                            facts = {
                                c.name: getattr(job, c.name)
                                for c in Job.__table__.columns
                            }
                            for field in (
                                "title",
                                "description",
                                "skills_required",
                                "experience_level",
                                "location",
                                "remote_type",
                                "employment_type",
                                "salary_min",
                                "salary_max",
                                "salary_currency",
                                "salary_period",
                            ):
                                facts[field] = getattr(latest, field)
                            facts["is_remote"] = latest.remote_type == "remote"
                            match_job = SimpleNamespace(**facts)
                        match = (
                            JobDiscoveryMatcher(session)
                            .match(match_job, profile, company)
                            .model_dump(mode="json")
                        )
                        match["evidence"] = {
                            "listing": latest.model_dump(
                                mode="json",
                                include={
                                    "title",
                                    "description",
                                    "skills_required",
                                    "experience_level",
                                    "location",
                                    "remote_type",
                                    "employment_type",
                                    "salary_min",
                                    "salary_max",
                                    "salary_currency",
                                    "salary_period",
                                    "original_url",
                                    "source_name",
                                    "data_provenance",
                                    "date_posted",
                                },
                            )
                            if latest
                            else None,
                            "company": company_evidence,
                        }
                        if (
                            company_evidence
                            and company_evidence["size"]["team_size_band"] != "unknown"
                        ):
                            match["positive_factors"].append(
                                "Company-size evidence is available for owner review; engineering team size remains unknown"
                            )
                        else:
                            match["unknown_fields"].append("company_size")
                        values = dict(
                            job_id=job.id,
                            profile_id=profile.id,
                            profile_version=profile.version,
                            evidence_hash=digest,
                            result=match,
                            scored_at=now,
                        )
                        await session.execute(
                            insert_for(session)(AutomationMatch)
                            .values(**values)
                            .on_conflict_do_update(
                                index_elements=["job_id"],
                                set_={k: v for k, v in values.items() if k != "job_id"},
                            )
                        )
                    rankings.append(
                        {"job_id": job_id, "profile_version": profile.version, **match}
                    )
            rankings.sort(key=lambda item: (-item["match_score"], item["job_id"]))
            counts = {
                "retrieved": len(result.jobs) + result.rejected_count,
                "accepted": len(ingested.job_ids),
                "inserted": ingested.inserted_count,
                "duplicate": ingested.duplicate_count,
                "rejected": result.rejected_count + ingested.rejected_count,
                "failed": ingested.failed_count,
            }
            state = (
                "completed"
                if result.status in accepted_states
                else "blocked"
                if result.status
                in {
                    DiscoveryStatus.RATE_LIMITED,
                    DiscoveryStatus.CONFIGURATION_REQUIRED,
                    DiscoveryStatus.AUTH_REQUIRED,
                }
                else "failed"
            )
            if state == "completed" and (
                result.status == DiscoveryStatus.PARTIAL
                or counts["rejected"]
                or counts["failed"]
            ):
                state = "partial"
            window = await session.get(
                ProviderAccessWindow, task.source, with_for_update=True
            )
            if window and result.status not in accepted_states:
                delay = max(
                    INTERVALS[task.source],
                    3600 if result.status == DiscoveryStatus.RATE_LIMITED else 300,
                    retry_after or 0,
                )
                window.next_allowed_at = max(
                    utc(window.next_allowed_at), now + timedelta(seconds=delay)
                )
            observation_ids = (
                list(
                    (
                        await session.scalars(
                            select(JobSourceObservation.id).where(
                                JobSourceObservation.job_id.in_(
                                    [uuid.UUID(j) for j in ingested.job_ids]
                                ),
                                JobSourceObservation.source == task.source,
                            )
                        )
                    ).all()
                )
                if ingested.job_ids
                else []
            )
            run = DiscoveryRun(
                source=task.source,
                request_hash=hashlib.sha256(str(task.id).encode()).hexdigest(),
                idempotency_key="automation_" + str(task.id),
                query_summary={"job_ids": ingested.job_ids},
                status="partial" if state == "partial" else str(result.status),
                rankings=rankings,
                counts=counts,
                errors=["listing_evidence_rejected"] if counts["rejected"] else [],
                started_at=task.started_at,
                finished_at=now,
                usage={"paid": False},
            )
            session.add(run)
            await session.flush()
            task.discovery_run_id = run.id
            task.state, task.finished_at, task.lease_until = state, now, None
            task.diagnostic = (
                None
                if state == "completed"
                else "listing_evidence_rejected"
                if counts["rejected"]
                else "ingestion_failed"
                if counts["failed"]
                else str(result.status)
            )
            task.outcome = {
                "counts": counts,
                "job_ids": ingested.job_ids,
                "observation_ids": [str(i) for i in observation_ids],
                "matching": "approved" if profile else "awaiting_profile_approval",
                "rankings": rankings,
                "rejection_reasons": ["invalid_listing_evidence"]
                if counts["rejected"]
                else [],
                "next_allowed_at": utc(window.next_allowed_at).isoformat()
                if window
                else None,
                "evidence_mode": "mocked"
                if self.adapter_factory != JobSourceFactory.get_adapter
                else "provider_reported",
            }
            await session.flush()
            if await instant(session, self.clock) >= deadline:
                raise LostLease()

    async def tick(self):
        identity = await self.claim()
        if identity:
            await self.execute(identity)
        # Deferred quiet-hour events come from durable executions/matches.
        async with self.factory() as session, session.begin():
            from backend.app.dashboard.notifications import synchronize

            row = await schedule(session)
            if row.enabled and not blockers(configuration(row), self.settings):
                now = await instant(session, self.clock)
                await session.execute(
                    insert_for(session)(OwnerPreference)
                    .values(
                        key="automation_notification_scan",
                        value={},
                    )
                    .on_conflict_do_nothing(index_elements=["key"])
                )
                scan = await session.scalar(
                    select(OwnerPreference)
                    .where(
                        OwnerPreference.key == "automation_notification_scan",
                    )
                    .with_for_update(skip_locked=True)
                )
                next_at = scan.value.get("next_at") if scan else None
                if scan and (not next_at or datetime.fromisoformat(next_at) <= now):
                    scan.value = {"next_at": (now + timedelta(minutes=5)).isoformat()}
                    await synchronize(session, automation=True)
        return identity


async def serve(factory, settings, stop):
    worker = DiscoveryWorker(factory, settings)

    async def consume():
        while not stop.is_set():
            try:
                await worker.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Fixed diagnostic; no provider payload/credential is logged.
                from backend.app.core.logging import logger

                logger.error("automation_tick_failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except TimeoutError:
                continue

    consumers = [asyncio.create_task(consume()) for _ in range(MAX_ACTIVE)]
    await stop.wait()
    # Bound shutdown even if a transport ignores its own timeout.
    _, pending = await asyncio.wait(consumers, timeout=10)
    for task in pending:
        task.cancel()
    await asyncio.gather(*consumers, return_exceptions=True)
