"""v2 control plane: automation status (per-portal quotas) and worker control."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from backend.app.api.v1.v2.deps import StoreDep, worker_read
from backend.app.browser_v2.rules import PortalRules, within_active_hours
from backend.app.browser_v2.schemas import (
    AutomationStatus,
    PortalStatus,
    WorkerControlRead,
    WorkerStartInput,
)
from backend.app.browser_v2.service import quota_counts
from backend.app.browser_v2.state import ApplicationState
from backend.app.browser_v2.store import Store, WorkerState

router = APIRouter()


# --- status -------------------------------------------------------------------------
async def portal_status(store: Store, rules: PortalRules, now: datetime) -> PortalStatus:
    counts = await quota_counts(store, rules, now)
    return PortalStatus(
        platform=rules.platform, enabled=rules.enabled, auto_apply_enabled=rules.auto_apply_enabled,
        auth_status=rules.auth_status, auth_checked_at=rules.auth_checked_at,
        portal_limit_hit_at=rules.portal_limit_hit_at, max_applies_per_day=rules.max_applies_per_day,
        max_applies_per_hour=rules.max_applies_per_hour, within_active_hours=within_active_hours(rules, now),
        waiting_for_user=await store.count_state(ApplicationState.WAITING_FOR_USER, rules.platform),
        **counts)


@router.get("/status", response_model=AutomationStatus)
async def automation_status(store: StoreDep) -> AutomationStatus:
    now = datetime.now(UTC)
    portals = [await portal_status(store, rules, now) for rules in await store.list_rules()]
    return AutomationStatus(
        generated_at=now, waiting_for_user=await store.count_state(ApplicationState.WAITING_FOR_USER),
        worker=worker_read(await store.get_worker_control(), now), portals=portals)


# --- worker control -----------------------------------------------------------------
@router.get("/worker", response_model=WorkerControlRead)
async def get_worker(store: StoreDep) -> WorkerControlRead:
    return worker_read(await store.get_worker_control())


@router.post("/worker/start", response_model=WorkerControlRead)
async def start_worker(store: StoreDep, data: WorkerStartInput | None = None) -> WorkerControlRead:
    dry_run = data.dry_run if data is not None else None
    return worker_read(await store.set_worker_control(WorkerState.RUNNING, dry_run=dry_run))


@router.post("/worker/pause", response_model=WorkerControlRead)
async def pause_worker(store: StoreDep) -> WorkerControlRead:
    return worker_read(await store.set_worker_control(WorkerState.PAUSED))


@router.post("/worker/stop", response_model=WorkerControlRead)
async def stop_worker(store: StoreDep) -> WorkerControlRead:
    return worker_read(await store.set_worker_control(WorkerState.STOPPED))


@router.post("/worker/run-once", response_model=WorkerControlRead)
async def run_worker_once(store: StoreDep) -> WorkerControlRead:
    return worker_read(await store.set_worker_control(run_once=True))
