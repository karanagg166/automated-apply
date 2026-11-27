"""Short PostgreSQL transactions; schedule lock serializes global admission."""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select

from backend.app.automation.models import (
    AutomationExecution,
    AutomationMatch,
    AutomationSchedule,
)
from backend.app.automation.schemas import ScheduleConfiguration
from backend.app.models.candidate_profile import CandidateProfile
from backend.app.models.startup import ProviderAccessWindow
from backend.app.services.discovery_budget import insert_for
from backend.app.services.job_sources.registry import resolve_source
from backend.app.services.startup_discovery.normalizer import utc
from backend.app.services.startup_discovery.source_registry import INTERVALS


async def instant(session, clock=None):
    if clock:
        return clock()
    if session.bind.dialect.name == "postgresql":
        return await session.scalar(select(func.clock_timestamp()))
    return datetime.now(timezone.utc)


async def schedule(session, *, lock=False):
    await session.execute(
        insert_for(session)(AutomationSchedule)
        .values(
            key="primary",
            enabled=False,
            version=1,
            configuration={},
        )
        .on_conflict_do_nothing(index_elements=["key"])
    )
    query = (
        select(AutomationSchedule)
        .where(AutomationSchedule.key == "primary")
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    return await session.scalar(query)


def configuration(row):
    return ScheduleConfiguration.model_validate(
        {**row.configuration, "enabled": row.enabled}
    )


async def approved_profile(session, config, *, lock=False):
    if not config.approved_profile_id:
        return None
    query = (
        select(CandidateProfile)
        .where(
            CandidateProfile.id == config.approved_profile_id,
            CandidateProfile.version == config.approved_profile_version,
        )
        .execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    return await session.scalar(query)


def blockers(config, settings):
    result = []
    if not settings.AUTOMATION_EXECUTION_ENABLED:
        result.append("operational_activation_required")
    if not config.sources:
        result.append("sources_required")
    for source in config.sources:
        if resolve_source(source, settings).availability != "available":
            result.append(source + "_configuration_required")
    return result


async def update_schedule(session, data, settings):
    row = await schedule(session, lock=True)
    if row.version != data.expected_version:
        raise HTTPException(409, "Schedule changed; reload before saving")
    config = data.configuration
    if config.enabled and blockers(config, settings):
        raise HTTPException(
            409, "Automation awaits operational activation and source configuration"
        )
    previous = configuration(row)
    changed_approval = (
        config.approved_profile_id,
        config.approved_profile_version,
    ) != (previous.approved_profile_id, previous.approved_profile_version)
    if (
        config.approved_profile_id
        and changed_approval
        and not await approved_profile(session, config)
    ):
        raise HTTPException(409, "Review the current saved profile version first")
    row.version += 1
    row.enabled = config.enabled
    row.configuration = config.model_dump(mode="json")
    row.next_run_at = await instant(session) if row.enabled else None
    # Configuration changes invalidate queued work; in-flight work is fenced at commit.
    pending = (
        await session.scalars(
            select(AutomationExecution)
            .where(
                AutomationExecution.state.in_(["pending", "claimed"]),
            )
            .with_for_update()
        )
    ).all()
    for task in pending:
        task.state, task.diagnostic = "blocked", "configuration_changed"
        task.finished_at = await instant(session)
        task.fence += 1
    await session.flush()


def execution_output(task):
    return {
        name: getattr(task, name)
        for name in (
            "id",
            "source",
            "trigger_type",
            "state",
            "created_at",
            "started_at",
            "finished_at",
            "diagnostic",
            "outcome",
            "discovery_run_id",
            "attempts",
            "available_at",
            "lease_until",
        )
    }


async def enqueue(session, row, request_key, trigger, now):
    config = configuration(row)
    for source in config.sources:
        # Coalesce different manual keys while this source already has active work.
        active = await session.scalar(
            select(AutomationExecution.id)
            .where(
                AutomationExecution.source == source,
                AutomationExecution.state.in_(["pending", "claimed", "running"]),
            )
            .limit(1)
        )
        if active:
            continue
        await session.execute(
            insert_for(session)(AutomationExecution)
            .values(
                request_key=request_key,
                source=source,
                trigger_type=trigger,
                schedule_version=row.version,
                configuration=config.model_dump(mode="json"),
                state="pending",
                fence=0,
                attempts=0,
                available_at=now,
                created_at=now,
                outcome={},
            )
            .on_conflict_do_nothing(index_elements=["request_key", "source"])
        )


async def preview(session, settings):
    row = await schedule(session)
    config = configuration(row)
    sources = []
    for name in config.sources:
        window = await session.get(ProviderAccessWindow, name)
        sources.append(
            {
                "source": name,
                "minimum_interval_seconds": INTERVALS[name],
                "next_allowed_at": window.next_allowed_at if window else None,
                "configured": resolve_source(name, settings).availability
                == "available",
            }
        )
    return {
        "provider_calls": 0,
        "planning_only": True,
        "sources": sources,
        "blockers": blockers(config, settings),
        "matching": "approved"
        if await approved_profile(session, config)
        else "awaiting_profile_approval",
        "limit_per_source": config.limit,
    }


async def status(session, settings):
    row = await schedule(session)
    config = configuration(row)
    now = await instant(session)
    active = await session.scalar(
        select(func.count())
        .select_from(AutomationExecution)
        .where(AutomationExecution.state.in_(["claimed", "running"]))
    )
    profile = await session.scalar(select(CandidateProfile))
    reasons = blockers(config, settings)
    return {
        "state": "disabled"
        if not row.enabled
        else "awaiting_configuration"
        if reasons
        else "running"
        if active
        else "ready",
        "version": row.version,
        "configuration": config.model_dump(mode="json"),
        "blockers": reasons,
        "next_run_at": row.next_run_at,
        "last_run_at": row.last_run_at,
        "worker_ready": bool(
            row.heartbeat_at and utc(row.heartbeat_at) > now - timedelta(seconds=60)
        ),
        "heartbeat_at": row.heartbeat_at,
        "active_executions": active,
        "profile": {"id": str(profile.id), "version": profile.version}
        if profile
        else None,
        "matching": "approved"
        if await approved_profile(session, config)
        else "awaiting_profile_approval",
    }


async def current_matches(session, config):
    if not await approved_profile(session, config):
        return []
    rows = (
        await session.scalars(
            select(AutomationMatch)
            .where(
                AutomationMatch.profile_id == config.approved_profile_id,
                AutomationMatch.profile_version == config.approved_profile_version,
            )
            .order_by(AutomationMatch.scored_at.desc())
            .limit(100)
        )
    ).all()
    return sorted(rows, key=lambda item: (-item.result["match_score"], str(item.job_id)))
