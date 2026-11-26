"""PostgresStore portal rules, auth/limit markers and worker control (mixin over PostgresBase).

Inherits ProfileRepo because `update_rules -> _save_overrides -> update_preferences`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.app.browser_v2.rules import (
    EDITABLE_RULE_FIELDS,
    OVERRIDE_RULE_FIELDS,
    PortalRules,
    apply_overrides,
)
from backend.app.browser_v2.store.base import _json
from backend.app.browser_v2.store.phase9_records import circuit_values
from backend.app.browser_v2.store.profile_repo import ProfileRepo
from backend.app.browser_v2.store.records import (
    RevisionConflict,
    RulesNotFound,
    WorkerControl,
    WorkerState,
)


class RulesRepo(ProfileRepo):
    # --- portal rules ---------------------------------------------------------------
    async def rule_overrides(self) -> dict[str, Any]:
        """preferences.portal_rule_overrides ({platform: {rule: value}}); {} without a profile."""
        try:
            raw = await self.connection.fetchval(
                "SELECT preferences->'portal_rule_overrides' FROM public.candidate_profiles "
                "WHERE singleton_key='primary'")
        except Exception:  # noqa: BLE001 - profile table drift must never block the rules engine
            return {}
        value = _json(raw) if raw is not None else {}
        return value if isinstance(value, dict) else {}

    async def ensure_rule_rows(self) -> None:
        """Phase 8b: seed (disabled) rows for registry portals added after migration 004, once per store.
        The runtime role has INSERT on portal_rules; ON CONFLICT keeps every owner edit."""
        if getattr(self, "_rules_seeded", False):
            return
        self._rules_seeded = True
        from backend.app.browser_v2.portals import PORTALS

        try:
            await self.connection.execute(
                "INSERT INTO public.portal_rules (platform, enabled) SELECT p, false FROM unnest($1::text[]) AS p "
                "ON CONFLICT (platform) DO NOTHING", sorted(PORTALS))
        except Exception:  # noqa: BLE001, S110 - missing grant: the registry portals simply stay unlisted
            pass

    async def get_rules(self, platform: str) -> PortalRules:
        await self.ensure_rule_rows()
        row = await self.connection.fetchrow("SELECT * FROM public.portal_rules WHERE platform=$1", platform)
        rules = PortalRules.from_row(dict(row)) if row else PortalRules(platform=platform)
        return apply_overrides(rules, await self.rule_overrides())

    async def list_rules(self) -> list[PortalRules]:
        await self.ensure_rule_rows()
        rows = await self.connection.fetch("SELECT * FROM public.portal_rules ORDER BY platform")
        overrides = await self.rule_overrides()
        return [apply_overrides(PortalRules.from_row(dict(row)), overrides) for row in rows]

    async def _save_overrides(self, platform: str, values: dict[str, Any]) -> None:
        current = await self.rule_overrides()
        entry = dict(current.get(platform) or {}) | values
        await self.update_preferences({"portal_rule_overrides": current | {platform: entry}})

    async def update_rules(self, platform, changes, expected_revision):
        overrides = {c: changes[c] for c in OVERRIDE_RULE_FIELDS if c in changes}
        if overrides:
            # Revision-checked first so a stale dashboard form never writes the override.
            current = await self.connection.fetchval(
                "SELECT revision FROM public.portal_rules WHERE platform=$1", platform)
            if current is None:
                raise RulesNotFound(platform)
            if current != expected_revision:
                raise RevisionConflict(current)
            await self._save_overrides(platform, overrides)
        columns = [c for c in EDITABLE_RULE_FIELDS if c in changes]
        values = [str(changes[c]) if c == "unknown_applicants_policy" else changes[c] for c in columns]
        assignments = "".join(f"{column}=${index + 3}, " for index, column in enumerate(columns))
        row = await self.connection.fetchrow(
            f"""UPDATE public.portal_rules SET {assignments}revision=revision + 1, updated_at=now()
                WHERE platform=$1 AND revision=$2 RETURNING *""",
            platform, expected_revision, *values)
        if row is not None:
            return apply_overrides(PortalRules.from_row(dict(row)), await self.rule_overrides())
        current = await self.connection.fetchval(
            "SELECT revision FROM public.portal_rules WHERE platform=$1", platform)
        if current is None:
            raise RulesNotFound(platform)
        raise RevisionConflict(current)

    # --- auth, limits, HITL -----------------------------------------------------------
    async def record_auth(self, platform: str, status: str) -> None:
        await self.connection.execute(
            "UPDATE public.portal_rules SET auth_status=$2, auth_checked_at=now() WHERE platform=$1",
            platform, status)

    async def record_portal_limit(self, platform: str) -> None:
        await self.connection.execute(
            "UPDATE public.portal_rules SET portal_limit_hit_at=now() WHERE platform=$1", platform)

    # --- Phase 9B: persisted circuit breaker + fresh-sweep clock (no revision bump) -----
    async def record_circuit(self, platform: str, *, failures: int, level: int,
                             open_until: datetime | None, reason: str | None) -> None:
        failures, level, reason = circuit_values(failures, level, reason)
        await self.connection.execute(
            """UPDATE public.portal_rules SET circuit_failures=$2, circuit_level=$3,
                   circuit_open_until=$4, circuit_reason=$5 WHERE platform=$1""",
            platform, failures, level, open_until, reason)

    async def record_fresh_sweep(self, platform: str, at: datetime) -> None:
        await self.connection.execute(
            "UPDATE public.portal_rules SET last_fresh_sweep_at=$2 WHERE platform=$1", platform, at)

    # --- worker control ---------------------------------------------------------------
    async def get_worker_control(self) -> WorkerControl:
        row = await self.connection.fetchrow(
            "SELECT * FROM public.worker_control WHERE singleton_key='primary'")
        if row is None:
            row = await self.connection.fetchrow(
                """INSERT INTO public.worker_control (singleton_key) VALUES ('primary')
                   ON CONFLICT (singleton_key) DO UPDATE SET singleton_key=EXCLUDED.singleton_key
                   RETURNING *""")
        return WorkerControl.from_row(dict(row))

    async def set_worker_control(self, desired_state=None, *, dry_run=None, run_once=False):
        await self.get_worker_control()
        row = await self.connection.fetchrow(
            """UPDATE public.worker_control SET
                   desired_state=COALESCE($1, desired_state),
                   dry_run=COALESCE($2, dry_run),
                   run_once_requested_at=CASE WHEN $3 THEN now() ELSE run_once_requested_at END,
                   revision=revision + 1, updated_at=now()
               WHERE singleton_key='primary' RETURNING *""",
            WorkerState(desired_state).value if desired_state is not None else None, dry_run, run_once)
        return WorkerControl.from_row(dict(row))

    async def worker_heartbeat(self, observed_state, *, current_platform=None, last_error=None,
                               cycle_completed=False, clear_run_once=False):
        await self.connection.execute(
            """UPDATE public.worker_control SET observed_state=$1, heartbeat_at=now(),
                   current_platform=$2, last_error=$3,
                   last_cycle_at=CASE WHEN $4 THEN now() ELSE last_cycle_at END,
                   run_once_requested_at=CASE WHEN $5 THEN NULL ELSE run_once_requested_at END
               WHERE singleton_key='primary'""",
            observed_state, current_platform, (last_error or None) and last_error[:500],
            cycle_completed, clear_run_once)
