"""Ops telemetry: worker/portal/quota/first-mover snapshot, dry-run toggle, Telegram mute, rules explain,
breaker reset and the semantic-cache profile-hash stamp (Milestone 2 command center)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.app.api.v1.v2.deps import AIDep, StoreDep, worker_read
from backend.app.api.v1.v2.routers.events import HubDep
from backend.app.browser_v2.schemas import PortalRulesRead, WorkerControlRead
from backend.app.browser_v2.schemas.ops import (
    DryRunInput,
    RulesExplainInput,
    RulesExplainRead,
    StampProfileInput,
    StampProfileRead,
    TelegramMuteInput,
    TelegramMuteRead,
    WorkerTelemetryRead,
)
from backend.app.browser_v2.store import AuditEntry, Store

router = APIRouter()
logger = logging.getLogger(__name__)
LIVE_CONFIRMATION = "LIVE"


def runtime_env() -> dict[str, str]:
    from backend.app.ai_v2.router import load_env

    return load_env()


async def audit(store: Store, tool: str, args: dict[str, Any], before: dict[str, Any] | None,
                after: dict[str, Any] | None, outcome: str = "ok") -> None:
    """Dashboard actions land in the append-only agent_audit_log (source='api'), best effort."""
    try:
        await store.append_audit(AuditEntry(source="api", tool_name=tool, outcome=outcome, args=args,
                                            before_summary=before, after_summary=after))
    except Exception as exc:  # noqa: BLE001 - an audit outage never blocks the owner's toggle
        logger.warning("api audit append failed for %s: %s", tool, type(exc).__name__)


@router.get("/worker/telemetry", response_model=WorkerTelemetryRead)
async def worker_telemetry(store: StoreDep) -> WorkerTelemetryRead:
    from backend.app.browser_v2.telemetry import build_telemetry

    now = datetime.now(UTC)
    return await build_telemetry(store, worker_read(await store.get_worker_control(), now), runtime_env(), now)


@router.post("/worker/dry-run", response_model=WorkerControlRead,
             responses={428: {"description": "Turning dry-run off needs confirm='LIVE'"}})
async def set_dry_run(data: DryRunInput, store: StoreDep, hub: HubDep) -> WorkerControlRead:
    """Dry-run ON is always allowed; OFF (live submissions) needs the typed confirmation 'LIVE'."""
    before = await store.get_worker_control()
    if not data.dry_run and (data.confirm or "").strip() != LIVE_CONFIRMATION:
        await audit(store, "dashboard_dry_run", {"dry_run": False}, {"dry_run": before.dry_run}, None, "refused")
        raise HTTPException(428, "Type LIVE to disable dry-run (real applications will be submitted)")
    updated = await store.set_worker_control(dry_run=data.dry_run)
    await audit(store, "dashboard_dry_run", {"dry_run": data.dry_run}, {"dry_run": before.dry_run},
                {"dry_run": updated.dry_run, "revision": updated.revision})
    read = worker_read(updated)
    await hub.publish("worker.state", {"desired_state": read.desired_state, "dry_run": read.dry_run,
                                       "observed_state": read.observed_state, "revision": read.revision,
                                       "via": "dashboard"})
    return read


@router.post("/telegram/mute", response_model=TelegramMuteRead)
async def telegram_mute(data: TelegramMuteInput, store: StoreDep, hub: HubDep) -> TelegramMuteRead:
    """Same state as Telegram `/mute`: telegram_v2_state.muted_until (the bot's router reads it)."""
    until = datetime.now(UTC) + timedelta(minutes=data.minutes) if data.minutes else None
    before = await store.get_telegram_state()
    await store.update_telegram_state(muted_until=until)
    await audit(store, "dashboard_telegram_mute", {"minutes": data.minutes or 0},
                {"muted_until": before.muted_until}, {"muted_until": until})
    await hub.publish("worker.state", {"telegram_muted_until": until.isoformat() if until else None,
                                       "via": "dashboard"})
    return TelegramMuteRead(muted_until=until)


@router.post("/rules/explain", response_model=RulesExplainRead)
async def explain_rules(data: RulesExplainInput, store: StoreDep) -> RulesExplainRead:
    """Run a pasted listing through the live rules (no fetching: the URL only picks the portal)."""
    from backend.app.browser_v2.rules_explain import explain_payload, infer_platform

    rules = await store.get_rules(infer_platform(data))
    profile, _ = await store.load_profile()
    return explain_payload(data, rules, profile)


@router.post("/portal-rules/{platform}/breaker/reset", response_model=PortalRulesRead,
             responses={404: {"description": "Unknown portal"}})
async def reset_breaker(platform: str, store: StoreDep, hub: HubDep) -> PortalRulesRead:
    """Close the persisted circuit breaker; the worker reloads it at its next cycle."""
    current = {r.platform: r for r in await store.list_rules()}.get(platform)
    if current is None:
        raise HTTPException(404, "Unknown portal")
    await store.record_circuit(platform, failures=0, level=0, open_until=None, reason=None)
    await audit(store, "dashboard_breaker_reset", {"platform": platform},
                {"circuit_level": current.circuit_level, "circuit_reason": current.circuit_reason},
                {"circuit_level": 0})
    updated = await store.get_rules(platform)
    await hub.publish("portal.breaker_changed", {"platform": platform, "circuit_level": 0,
                                                 "circuit_open_until": None, "auth_status": updated.auth_status,
                                                 "enabled": updated.enabled, "via": "dashboard"})
    return PortalRulesRead.from_rules(updated)


@router.post("/semantic-cache/stamp-profile", response_model=StampProfileRead,
             responses={503: {"description": "Semantic cache unavailable"}})
async def stamp_profile(store: StoreDep, ai: AIDep, data: StampProfileInput | None = None) -> StampProfileRead:
    """Stamp owner-verified cache rows with the current profile hash (what `facts stamp-cache` does)."""
    from backend.app.browser_v2.cache_stamp import stamp_profile_hash

    scope = (data or StampProfileInput()).scope
    try:
        result = await stamp_profile_hash(store, ai, runtime_env(), scope=scope)
    except LookupError as exc:
        raise HTTPException(503, str(exc)) from None
    await audit(store, "dashboard_stamp_cache", {"scope": scope}, None,
                {"stamped": result.stamped, "stale_remaining": result.stale_remaining})
    return result
