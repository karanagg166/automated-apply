"""Phase 9D profile-sync commands: sync-profile (dry-run by default) and probe-profile-page.

    backend/venv/bin/python -m backend.app.browser_v2.cli sync-profile --portal naukri [--dry-run]
    ... sync-profile --portal naukri --confirm-live      (asks you to type 'SYNC naukri')
    ... probe-profile-page --portal naukri [--url <profile page>]

Both refuse to run while the dedicated Brave profile is in use (e.g. the 24/7 worker):
stop the worker first. A live sync additionally needs ``profile_sync.<portal>.live = true`` in
the candidate preferences and the Postgres store (the run history must persist).
"""

from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable
from typing import Any

from backend.app.browser_v2.cli.common import emit

CONFIRM_WORD = "SYNC"


class SyncRefused(RuntimeError):
    pass


def _assert_profile_free(lock_check: Callable[[], None] | None) -> None:
    from backend.app.browser_v2 import profile as brave_profile

    (lock_check or brave_profile.assert_profile_free)()


def confirm_live(portal: str, *, assume_yes: bool, input_fn: Callable[[str], str], is_tty: bool) -> None:
    if assume_yes:
        return
    if not is_tty:
        raise SyncRefused("live_needs_typed_confirmation (run in a terminal or add --yes)")
    typed = input_fn(f"LIVE profile sync on {portal}: saves changed fields on the portal. "
                     f"Type '{CONFIRM_WORD} {portal}': ")
    if typed.strip() != f"{CONFIRM_WORD} {portal}":
        raise SyncRefused("confirmation_mismatch")


async def sync_profile_command(portal: str, live: bool = False, assume_yes: bool = False, *,
                               service_factory: Callable[..., Awaitable[tuple[Any, str]]] | None = None,
                               lock_check: Callable[[], None] | None = None,
                               input_fn: Callable[[str], str] = input, is_tty: bool | None = None) -> int:
    from backend.app.browser_v2.profile import ProfileError

    report: dict[str, Any] = {"portal": portal, "mode": "live" if live else "dry_run"}
    try:
        _assert_profile_free(lock_check)
        if live:
            confirm_live(portal, assume_yes=assume_yes, input_fn=input_fn,
                         is_tty=sys.stdin.isatty() if is_tty is None else is_tty)
    except (ProfileError, SyncRefused) as exc:
        emit(report | {"ok": False, "refused": str(exc)})
        return 2
    if service_factory is None:
        from backend.app.browser_v2.service import build_service

        service_factory = build_service
    service, backend = await service_factory(require_db=live)
    try:
        if live and backend.split(" ")[0] != "postgres":
            emit(report | {"ok": False, "refused": "live_requires_postgres_store"})
            return 2
        from backend.app.browser_v2.profile_sync.scheduler import build_profile_sync

        env_profile = getattr(service, "env_profile", None) or {}
        sync = build_profile_sync(service.store, service.manager, session_adapters=getattr(service, "adapters", None),
                                  fallback_resume_path=env_profile.get("resume_path"))
        result = await sync.service.sync(portal, dry_run=not live, trigger="cli")
        emit(report | {"ok": result.status not in {"failed", "auth_required"}, "store": backend.split(" ")[0],
                       "summary": result.summary(), **result.public()})
        return 0 if result.status not in {"failed", "auth_required"} else 1
    finally:
        await service.manager.close()
        await service.store.close()


async def probe_profile_command(portal: str, url: str | None = None, *,
                                service_factory: Callable[..., Awaitable[tuple[Any, str]]] | None = None,
                                lock_check: Callable[[], None] | None = None) -> int:
    from backend.app.browser_v2.profile import ProfileError
    from backend.app.browser_v2.profile_sync.adapters import default_profile_adapters

    adapter = default_profile_adapters().get(portal)
    target = url or (adapter.profile_url if adapter is not None else None)
    if adapter is None or not target:
        emit({"ok": False, "portal": portal, "refused": "pass --url <profile page> (no verified default URL)"})
        return 2
    try:
        _assert_profile_free(lock_check)
    except ProfileError as exc:
        emit({"ok": False, "portal": portal, "refused": str(exc)})
        return 2
    if service_factory is None:
        from backend.app.browser_v2.service import build_service

        service_factory = build_service
    service, _ = await service_factory(require_db=False)
    try:
        from backend.app.browser_v2.profile_sync.probe import capture_outline

        profile, _answers = await service.store.load_profile()
        prefs = (profile or {}).get("preferences") or {}
        identity = {**(profile or {}), "current_location": prefs.get("current_location")}
        async with service.manager.job() as page:
            result = await capture_outline(page, portal, adapter, target, profile=identity)
        emit({"ok": True, "portal": portal, **result})
        return 0
    finally:
        await service.manager.close()
        await service.store.close()
