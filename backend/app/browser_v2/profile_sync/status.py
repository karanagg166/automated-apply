"""Read-only profile-sync status: last run per portal + calibrated / live flags (API, Telegram)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.app.browser_v2.profile_sync.adapters import (
    ProfileAdapter,
    default_profile_adapters,
)
from backend.app.browser_v2.profile_sync.models import profile_sync_live
from backend.app.browser_v2.profile_sync.runs import (
    PostgresProfileSyncRuns,
    ProfileSyncRuns,
    runs_for,
)

RUN_KEYS = ("id", "trigger", "dry_run", "status", "error", "started_at", "finished_at")


def run_public(row: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """A run row without value references: per-field statuses only."""
    if row is None:
        return None
    out = {key: row.get(key) for key in RUN_KEYS}
    fields = row.get("fields")
    out["fields"] = {name: value.get("status") for name, value in fields.items()
                     if isinstance(value, Mapping)} if isinstance(fields, Mapping) else {}
    receipt = row.get("receipt")
    out["freshness_touched"] = isinstance(receipt, Mapping) and receipt.get("freshness_touched") is True
    return out


async def sync_status(store: Any, *, adapters: Mapping[str, ProfileAdapter] | None = None,
                      runs: ProfileSyncRuns | None = None) -> dict[str, Any]:
    adapters = adapters or default_profile_adapters()
    runs = runs or runs_for(store)
    profile, _ = await store.load_profile()
    prefs = (profile or {}).get("preferences") or {}
    available = await runs.ready() if isinstance(runs, PostgresProfileSyncRuns) else True
    portals = []
    for platform, adapter in adapters.items():
        portals.append({
            "platform": platform,
            "calibrated": bool(adapter.calibrated),
            "calibrated_fields": sorted(adapter.calibrated_fields) if adapter.calibrated else [],
            "supported_fields": sorted(adapter.supported_fields),
            "live": profile_sync_live(prefs, platform),
            "last_run": run_public(await runs.last(platform)) if available else None,
        })
    return {"runs_available": available, "portals": portals}
