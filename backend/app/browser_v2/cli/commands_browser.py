"""Browser/portal commands: login-setup, check-session, test-apply, verify-submissions, apply-one."""

from __future__ import annotations

import subprocess
from typing import Any

from backend.app.browser_v2 import profile as brave_profile
from backend.app.browser_v2.cli.common import (
    MAX_DEBUG_BUNDLES,
    MAX_INSPECTIONS_PER_APPLY,
    PHASE1_LIVE_LIMIT,
    emit,
)


def login_setup(portals: list[str]) -> int:
    """Plain Brave (no Playwright/CDP/automation flags) so portals see a normal browser."""
    path = brave_profile.ensure_profile_dir()
    brave_profile.assert_profile_free(path)
    brave_profile.ensure_persistent_preferences(path)  # logins survive quitting/reopening Brave
    executable = brave_profile.brave_executable()
    if not executable.exists():
        emit({"error": f"Brave not found at {executable}"})
        return 2
    urls = [brave_profile.LOGIN_URLS[p] for p in portals]
    command = [str(executable), f"--user-data-dir={path}", "--no-first-run",
               "--no-default-browser-check", *urls]
    print(f"Opening plain Brave on {path}\nLog in to: {', '.join(portals)}.\n"
          "When finished, quit Brave with Cmd+Q (not just closing the window) so cookies are saved.")
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    code = process.wait()
    exit_type = brave_profile.last_exit_type(path)
    emit({"profile_dir": str(path), "brave_exit_code": code, "profile_exit_type": exit_type,
          "saved": exit_type == "Normal",
          "next": "run check-session --portal naukri --restart" if exit_type == "Normal"
          else "Brave did not exit cleanly; reopen login-setup and quit with Cmd+Q"})
    return 0 if exit_type == "Normal" else 1


async def debug_bundle(service: Any, portal: str) -> dict[str, Any]:
    """Phase 6B --debug-selectors: scrubbed DOM probe + screenshot of the current worker tab."""
    from backend.app.browser_v2.diagnostics import capture_bundle

    if not service.manager.running:
        return {"skipped": "browser_not_running (API/feed-only path)"}
    try:
        profile, _ = await service.store.load_profile()
        return await capture_bundle(await service.manager.page(), portal, service.adapters.get(portal),
                                    dry_run=True, profile=profile)
    except Exception as exc:  # noqa: BLE001 - diagnostics never break the run
        return {"error": type(exc).__name__}


async def check_session(portal: str, restart: bool, debug_selectors: bool = False) -> int:
    from backend.app.browser_v2.service import build_service

    service, backend = await build_service(require_db=False)
    try:
        first = await service.check_portal_session(portal)
        result: dict[str, Any] = {"store": backend, "first": first}
        if debug_selectors:
            result["diagnostics"] = [await debug_bundle(service, portal)]
        if restart:
            await service.manager.close()
            result["after_restart"] = await service.check_portal_session(portal)
        emit(result)
        final = result.get("after_restart", first)
        return 0 if final["status"] == "OK" else 1
    finally:
        await service.manager.close()
        await service.store.close()


async def default_query(service: Any) -> str:
    profile, _ = await service.store.load_profile()
    roles = (profile.get("preferences") or {}).get("target_roles") or []
    return roles[0] if roles else "software engineer"


SYNTHETIC_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def synthetic_profile() -> dict[str, Any]:
    """Fictional identity for dry-run form calibration only (example.com, placeholder PDF, never submitted)."""
    folder = brave_profile.runtime_dir() / "receipts" / "diagnostics"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    resume = folder / "synthetic-resume.pdf"
    resume.write_bytes(SYNTHETIC_PDF)
    return {"full_name": "Test Candidate", "email": "candidate@example.com", "phone": "+910000000000",
            "linkedin_url": "https://www.linkedin.com/in/example", "verified_skills": ["Python", "FastAPI"],
            "preferences": {"current_location": "Bengaluru", "total_experience_years": 2, "notice_period_days": 30,
                            "willing_to_relocate": True, "resume_files": {"backend": str(resume)},
                            "target_roles": ["software engineer", "backend engineer", "engineer"]}}


async def test_apply(portal: str, live: bool, limit: int, query: str | None, url: str | None,
                     assume_yes: bool, boards: list[str] | None = None, debug_selectors: bool = False,
                     synthetic: bool = False) -> int:
    from backend.app.browser_v2.service import build_service
    from backend.app.browser_v2.state import NEVER_REPLAY

    if live and debug_selectors:
        emit({"error": "--debug-selectors is allowed only with --dry-run (never on a live submit)"})
        return 2
    if live and synthetic:
        emit({"error": "--synthetic-profile is allowed only with --dry-run"})
        return 2
    if live and limit > PHASE1_LIVE_LIMIT:
        emit({"error": f"Phase 1 allows at most {PHASE1_LIVE_LIMIT} watched live apply per run"})
        return 2
    service, backend = await build_service(require_db=live)
    results: list[dict[str, Any]] = []
    calibration: str | None = None
    try:
        from backend.app.browser_v2.store import MemoryStore

        memory = service.store if isinstance(service.store, MemoryStore) else None
        if debug_selectors and not live and memory is not None:
            # Pre-migration calibration only: the throwaway MemoryStore seeds just Naukri as enabled.
            # Enable the target portal IN MEMORY so a dry-run reaches the form (never Postgres, never live).
            from dataclasses import replace as dc_replace

            current = await memory.get_rules(portal)
            if not current.enabled:
                memory.rules[portal] = dc_replace(current, enabled=True, auto_apply_enabled=True,
                                                         active_hours_start=None, active_hours_end=None)
                calibration = "memory-only: portal enabled for this dry-run calibration (DB rules untouched)"
        if synthetic:
            if memory is None or live:
                emit({"error": "--synthetic-profile needs the pre-migration memory store and --dry-run"})
                return 2
            memory.profile = synthetic_profile()
            calibration = (calibration or "memory-only") + "; synthetic example.com profile (never submitted)"
        await service.configure_adapters()
        adapter = service.adapters.get(portal)
        if boards and adapter is not None and hasattr(adapter, "boards"):
            adapter.boards.update({board: None for board in boards})
        session = await service.check_portal_session(portal)
        if session.get("status") != "OK":
            # Fail closed before discovery: never parse a login wall / challenge page as job cards.
            result: dict[str, Any] = {"store": backend, "mode": "live" if live else "dry_run", "session": session,
                                      "results": [], "stopped": "session_not_ok"}
            if debug_selectors:
                result["diagnostics"] = [await debug_bundle(service, portal)]
            emit(result)
            return 1
        if url:
            targets = [url]
        else:
            search = query or await default_query(service)
            listings = await service.discover_portal_jobs(portal, search, limit=20)
            targets = [item["url"] for item in listings if item["state"] not in NEVER_REPLAY]
        if live and not assume_yes:
            answer = input(f"LIVE apply on {portal} (store={backend}). Type APPLY to continue: ")
            if answer.strip() != "APPLY":
                emit({"aborted": True})
                return 1
        applied = 0
        for target in targets[: limit * MAX_INSPECTIONS_PER_APPLY]:
            outcome = await service.apply_to_job(portal, target, dry_run=not live)
            if debug_selectors and len(results) < MAX_DEBUG_BUNDLES:
                outcome = dict(outcome) | {"diagnostics": await debug_bundle(service, portal)}
            results.append(outcome)
            reached_apply = outcome.get("reason") in {"dry_run_stopped_before_apply_click",
                                                      "dry_run_stopped_before_submit"} or outcome.get("clicked_apply")
            if reached_apply or outcome.get("state") in {"APPLIED", "WAITING_FOR_USER",
                                                         "SUBMISSION_UNKNOWN", "QUOTA_HIT_PENDING"}:
                applied += 1
            if applied >= limit:
                break
        emit({"store": backend, "mode": "live" if live else "dry_run",
              **({"calibration_rules": calibration} if calibration else {}), "results": results})
        return 0
    finally:
        await service.manager.close()
        await service.store.close()


async def verify_submissions_command(portal: str) -> int:
    """Read-only check of the portal's history; SUBMISSION_UNKNOWN -> APPLIED only on an exact match."""
    from backend.app.browser_v2.service import build_service
    from backend.app.browser_v2.state import ApplicationState
    from backend.app.browser_v2.store import ApplicationQuery

    service, backend = await build_service(require_db=True)
    try:
        session = await service.check_portal_session(portal)
        results = await service.reconcile_submissions(portal) if session.get("status") == "OK" else []
        applied, _ = await service.store.list_applications(
            ApplicationQuery(platform=portal, state=ApplicationState.APPLIED.value, limit=20))
        emit({"store": backend, "portal": portal, "session": session.get("status"), "reconciled": results,
              "applied": [{"external_job_id": r.external_job_id, "title": r.role_title, "company": r.company_name,
                           "reason": r.reason, "receipt_source": (r.receipt or {}).get("source"),
                           "applied_at": r.applied_at} for r in applied]})
        return 0
    finally:
        await service.manager.close()
        await service.store.close()


async def apply_one_command(portal: str, url: str, confirm_live: bool, assume_yes: bool) -> int:
    from backend.app.ai_v2.router import load_env
    from backend.app.browser_v2.canary import apply_one
    from backend.app.browser_v2.worker import quota_notifier

    notify, close = quota_notifier(load_env())
    try:
        report = await apply_one(portal, url, confirm_live=confirm_live, assume_yes=assume_yes, notify=notify)
    finally:
        if close is not None:
            await close()
    emit(report)
    return 0 if report.get("ok") else 1
