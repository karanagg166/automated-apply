"""Milestone 2 ops telemetry: one read-only snapshot for the command-center status bar and overview.

Everything is derived from durable rows (worker_control, portal_rules, applications, state events,
hitl_requests, watcher_state, telegram state/ledger) so the API process reports the worker's truth,
not its own in-process counters.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.app.browser_v2.redact import redact_secrets as redact
from backend.app.browser_v2.rules import PortalRules, paused, within_active_hours
from backend.app.browser_v2.schemas.applications import WorkerControlRead
from backend.app.browser_v2.schemas.ops import (
    ActiveJobRead,
    BraveHealthRead,
    FirstMoverRead,
    OpsKpisRead,
    PortalTelemetryRead,
    TelegramOpsRead,
    WorkerTelemetryRead,
)
from backend.app.browser_v2.service import quota_counts
from backend.app.browser_v2.store import Store

STALE_RECONCILE_AFTER = timedelta(hours=24)
CACHE_WINDOW_DAYS = 7
WATCHER_ACTIVE_WITHIN = timedelta(hours=2)
CACHE_HIT_SOURCES = frozenset({"semantic_cache"})
# Answers that went through the cache lookup (deterministic facts / identity / resume never do).
CACHE_LOOKUP_SOURCES = frozenset({"semantic_cache", "llm", "human", "human_hitl"})
LIVE_OBSERVED = frozenset({"RUNNING", "IDLE", "SLEEPING"})


def percentile(values: list[float], fraction: float) -> int | None:
    """Nearest-rank percentile (no numpy); None for an empty sample."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(-(-fraction * len(ordered) // 1))))
    return round(ordered[rank - 1])


def ops_status(worker: WorkerControlRead) -> str:
    if worker.stale:
        return "OFFLINE"
    if worker.desired_state != "RUNNING":
        return "PAUSED"
    return "DRY_RUN" if worker.dry_run else "RUNNING"


def breaker_state(rules: PortalRules, now: datetime) -> str:
    if rules.circuit_open_until is not None and rules.circuit_open_until > now:
        return "open"
    if rules.circuit_level > 0:
        return "half_open"  # the open window elapsed: the next job is the trial
    return "closed"


def portal_health(rules: PortalRules, breaker: str, counts: Mapping[str, Any], now: datetime) -> tuple[str, str | None]:
    if rules.auth_status == "AUTH_REQUIRED":
        return "red", "auth_required"
    if breaker == "open":
        return "red", "circuit_open"
    if not rules.enabled:
        return "amber", "disabled"
    if paused(rules, now):
        return "amber", "paused"
    if counts.get("daily_limit_hit") or counts.get("portal_limit_hit_today"):
        return "amber", "daily_quota_full"
    if counts.get("hourly_limit_hit"):
        return "amber", "hourly_quota_full"
    if breaker == "half_open":
        return "amber", "circuit_half_open"
    return "green", None


async def portal_telemetry(store: Store, rules: PortalRules, now: datetime) -> PortalTelemetryRead:
    counts = await quota_counts(store, rules, now)
    breaker = breaker_state(rules, now)
    health, reason = portal_health(rules, breaker, counts, now)
    return PortalTelemetryRead(
        platform=rules.platform, enabled=rules.enabled, auto_apply_enabled=rules.auto_apply_enabled,
        paused_until=rules.paused_until, auth_status=rules.auth_status, auth_checked_at=rules.auth_checked_at,
        breaker_state=breaker, breaker_open_until=rules.circuit_open_until,  # type: ignore[arg-type]
        breaker_reason=redact(rules.circuit_reason)[:200] if rules.circuit_reason else None,
        breaker_level=rules.circuit_level, applied_today=counts["applied_today"],
        attempts_today=counts["attempts_today"], daily_cap=rules.max_applies_per_day,
        applied_this_hour=counts["applied_this_hour"], hourly_cap=rules.max_applies_per_hour,
        portal_limit_hit_today=bool(counts["portal_limit_hit_today"]),
        within_active_hours=within_active_hours(rules, now), last_sweep_at=rules.last_fresh_sweep_at,
        health=health, health_reason=reason)  # type: ignore[arg-type]


async def telegram_telemetry(store: Store, env: Mapping[str, str], now: datetime) -> TelegramOpsRead:
    from backend.app.telegram_v2.config import TelegramConfig
    from backend.app.telegram_v2.notify_policy import NotifyConfig

    config = TelegramConfig.from_env(env)
    policy = NotifyConfig.from_env(env)
    state = await store.get_telegram_state()
    window = None
    if policy.quiet_start is not None and policy.quiet_end is not None:
        window = f"{policy.quiet_start:%H:%M}-{policy.quiet_end:%H:%M} {policy.tz.key}"
    pushes = await store.ops_pushes_since(now - timedelta(hours=1))
    muted = state.muted_until if state.muted_until is not None and state.muted_until > now else None
    return TelegramOpsRead(
        configured=config.configured, muted_until=muted, quiet_hours_active=policy.in_quiet(now),
        quiet_hours=window, push_budget_per_hour=policy.max_pushes_per_hour,
        push_budget_remaining=max(policy.max_pushes_per_hour - pushes, 0),
        polling_state=state.polling_state if config.configured else "unconfigured")


def local_day_start(now: datetime, tz: str = "Asia/Kolkata") -> datetime:
    local = now.astimezone(ZoneInfo(tz))
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


async def build_telemetry(store: Store, worker: WorkerControlRead, env: Mapping[str, str],
                          now: datetime | None = None) -> WorkerTelemetryRead:
    now = now or datetime.now(UTC)
    day = local_day_start(now)
    portals = [await portal_telemetry(store, rules, now) for rules in await store.list_rules()]
    active = await store.ops_active_job()
    active_job = None
    if active is not None:
        started = active.get("started_at")
        active_job = ActiveJobRead(**{**active, "step": str(active.get("step") or "apply_started")[:80],
                                      "elapsed_sec": round((now - started).total_seconds(), 1) if started else None})
    lags = await store.ops_first_mover_lags(day)
    receipts = await store.ops_receipt_counts(day, now - STALE_RECONCILE_AFTER)
    sources = await store.ops_answer_sources(now - timedelta(days=CACHE_WINDOW_DAYS))
    lookups = sum(n for source, n in sources.items() if source in CACHE_LOOKUP_SOURCES)
    hits = sum(n for source, n in sources.items() if source in CACHE_HIT_SOURCES)
    pending = (await store.list_hitl("OPEN", None, 1, 0))[1]
    live = not worker.stale and worker.observed_state in LIVE_OBSERVED
    detail = redact(worker.last_error)[:200] if worker.last_error else (
        None if live else f"worker {worker.observed_state.lower()}")
    return WorkerTelemetryRead(
        generated_at=now, status=ops_status(worker), worker=worker, active_job=active_job,  # type: ignore[arg-type]
        brave=BraveHealthRead(healthy=(live and not worker.last_error) if not worker.stale else None, detail=detail),
        portals=portals,
        first_mover=FirstMoverRead(p50_seconds=percentile(lags, 0.5), p95_seconds=percentile(lags, 0.95),
                                   samples=len(lags)),
        telegram=await telegram_telemetry(store, env, now),
        kpis=OpsKpisRead(
            applied_today=sum(p.applied_today for p in portals), verified_receipts_today=receipts["verified_today"],
            pending_hitl=int(pending), cache_hit_rate=round(hits / lookups, 4) if lookups else None,
            cache_hit_window_days=CACHE_WINDOW_DAYS, cache_lookups=lookups,
            active_watchers=await store.ops_active_watchers(now - WATCHER_ACTIVE_WITHIN, now),
            needs_reconciliation=receipts["needs_reconciliation"]))
