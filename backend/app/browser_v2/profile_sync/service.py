"""ProfileSyncService: canonical profile -> one portal profile, dry-run by default.

``sync(platform, dry_run=True, trigger=...)``:
1. canonical ProfileSnapshot (candidate_profiles + active resume);
2. an uncalibrated adapter ends here: every field ``skipped_not_calibrated``, the browser is
   never opened;
3. otherwise the single Brave tab via ``BraveBrowserManager.job()`` -> portal session check
   (AUTH_REQUIRED -> run ``auth_required``, no reads or writes) -> ``adapter.read`` -> diff;
4. dry-run (or live requested while ``preferences.profile_sync.<platform>.live`` is not true):
   report only. Live: one field at a time, re-read to verify (``verify_failed`` on mismatch);
   a failed save is never retried in the same run; pre/post screenshots on failure;
5. Naukri freshness touch (identical PDF re-upload) when live, due (> 24 h since the last
   touch) and inside the portal's active hours, even if nothing changed;
6. the run row (statuses + SHA-256 references only) is persisted in ``profile_sync_runs``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.app.browser_v2.profile_sync.adapters import (
    ProfileAdapter,
    can_write,
    not_calibrated,
)
from backend.app.browser_v2.profile_sync.canonical import build_snapshot
from backend.app.browser_v2.profile_sync.diff import compute_diff, values_match
from backend.app.browser_v2.profile_sync.models import (
    FieldDiff,
    FieldStatus,
    ProfileSnapshot,
    SyncReport,
    profile_sync_live,
    run_status,
)
from backend.app.browser_v2.profile_sync.runs import ProfileSyncRuns
from backend.app.browser_v2.rules import within_active_hours

logger = logging.getLogger(__name__)
FRESHNESS_INTERVAL = timedelta(hours=24)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {str(exc)[:200]}"


class ProfileSyncService:
    def __init__(self, store: Any, manager: Any, adapters: Mapping[str, ProfileAdapter], runs: ProfileSyncRuns,
                 clock: Callable[[], datetime] | None = None, receipts: Any = None, *,
                 session_adapters: Mapping[str, Any] | None = None, fallback_resume_path: str | None = None,
                 freshness_interval: timedelta = FRESHNESS_INTERVAL, check_files: bool = True) -> None:
        self.store = store
        self.manager = manager
        self.adapters = dict(adapters)
        self.runs = runs
        self.clock = clock or _utcnow
        if receipts is None:
            from backend.app.browser_v2 import receipts as receipts_module

            receipts = receipts_module
        self.receipts = receipts
        self.session_adapters = dict(session_adapters or {})
        self.fallback_resume_path = fallback_resume_path
        self.freshness_interval = freshness_interval
        self.check_files = check_files

    def adapter(self, platform: str) -> ProfileAdapter:
        try:
            return self.adapters[platform]
        except KeyError:
            raise ValueError(f"unsupported_profile_portal:{platform}") from None

    async def sync(self, platform: str, *, dry_run: bool = True, trigger: str = "cli") -> SyncReport:
        adapter = self.adapter(platform)
        snapshot = await build_snapshot(self.store, fallback_resume_path=self.fallback_resume_path,
                                        check_files=self.check_files)
        live = not dry_run and profile_sync_live(snapshot.preferences, platform)
        report = SyncReport(platform, dry_run=not live, trigger=trigger)
        if not dry_run and not live:
            report.receipt["live_blocked"] = "profile_sync_live_flag_off"
        report.run_id = await self.runs.start(platform, trigger, not live)
        try:
            if not adapter.calibrated:
                # Never touches the page (nor opens the browser) for an uncalibrated adapter.
                self._record(report, compute_diff(snapshot.values, not_calibrated(adapter.supported_fields),
                                                  adapter.supported_fields))
                report.receipt["calibrated"] = False
            else:
                async with self.manager.job() as page:
                    await self._sync_page(page, adapter, snapshot, report, live=live)
            if report.status == "running":
                report.status = run_status(report)
        except Exception as exc:  # noqa: BLE001 - one failed run never stops the worker
            logger.warning("profile sync %s failed: %s", platform, type(exc).__name__)
            report.status, report.error = "failed", _error(exc)
        finally:
            await self.runs.finish(str(report.run_id), report.status if report.status != "running" else "failed",
                                   report.fields_public(), report.error, report.receipt)
        return report

    def _record(self, report: SyncReport, diffs: list[FieldDiff]) -> None:
        for diff in diffs:
            report.statuses[diff.field] = diff

    async def _session(self, platform: str, page: Any) -> str:
        checker = self.session_adapters.get(platform)
        if checker is None:
            return "UNKNOWN"
        result = await checker.check_session(page)
        status = getattr(result, "status", result)
        return str(getattr(status, "value", status))

    async def _sync_page(self, page: Any, adapter: ProfileAdapter, snapshot: ProfileSnapshot,
                         report: SyncReport, *, live: bool) -> None:
        session = await self._session(adapter.platform, page)
        report.receipt["session"] = session
        if session == "AUTH_REQUIRED":
            report.status, report.error = "auth_required", "portal_login_required"
            return
        if session != "OK":
            report.status, report.error = "failed", f"session_{session.lower()}"
            return
        portal = await adapter.read(page)
        self._record(report, compute_diff(snapshot.values, portal, adapter.supported_fields))
        if live:
            for diff in list(report.statuses.values()):
                if diff.status is FieldStatus.WOULD_UPDATE:
                    report.statuses[diff.field] = await self._write(page, adapter, diff, report)
        await self._freshness(page, adapter, snapshot, report, live=live)

    async def _shot(self, page: Any, report: SyncReport, label: str) -> str | None:
        try:
            path = await self.receipts.capture(page, report.platform, f"profile-sync-{report.run_id}", label)
        except Exception:  # noqa: BLE001 - evidence is best effort
            return None
        return str(path) if path else None

    async def _write(self, page: Any, adapter: ProfileAdapter, diff: FieldDiff, report: SyncReport) -> FieldDiff:
        if not can_write(adapter, diff.field):
            return diff.with_status(FieldStatus.SKIPPED_NOT_CALIBRATED, "write_not_calibrated")
        value = list(diff.additions) if diff.field == "key_skills" else diff.proposed
        pre = await self._shot(page, report, f"{diff.field}-pre")
        try:
            saved = await adapter.write(page, diff.field, value)
            reason = None if saved else "save_not_confirmed"
        except Exception as exc:  # noqa: BLE001 - a failed save is never retried in the same run
            saved, reason = False, f"write_error:{type(exc).__name__}"
        result = diff.with_status(FieldStatus.ERROR, reason)
        if saved:
            try:
                after = (await adapter.read(page)).get(diff.field)
            except Exception as exc:  # noqa: BLE001
                after, reason = None, f"verify_read_error:{type(exc).__name__}"
            if after is not None and after.status is None and values_match(diff.field, diff.proposed, after.value):
                if pre:
                    Path(pre).unlink(missing_ok=True)
                return diff.with_status(FieldStatus.UPDATED)
            result = diff.with_status(FieldStatus.VERIFY_FAILED, reason or "value_mismatch_after_save")
        post = await self._shot(page, report, f"{diff.field}-post")
        report.receipt.setdefault("screenshots", []).extend(p for p in (pre, post) if p)
        return result

    async def freshness_due(self, adapter: ProfileAdapter, snapshot: ProfileSnapshot) -> bool:
        if not adapter.freshness_touch or not snapshot.resume_path:
            return False
        now = self.clock()
        last = await self.runs.last_freshness_touch(adapter.platform)
        if last is not None and now - last < self.freshness_interval:
            return False
        try:
            rules = await self.store.get_rules(adapter.platform)
        except Exception:  # noqa: BLE001 - unknown rules: default to "not now"
            return False
        return within_active_hours(rules, now)

    async def _freshness(self, page: Any, adapter: ProfileAdapter, snapshot: ProfileSnapshot,
                         report: SyncReport, *, live: bool) -> None:
        if not adapter.freshness_touch:
            return
        resume = report.statuses.get("resume_pdf")
        if resume is not None and resume.status is FieldStatus.UPDATED:
            report.receipt["freshness_touched"] = True  # the upload itself bumped "last updated"
            return
        due = await self.freshness_due(adapter, snapshot)
        report.receipt["freshness_due"] = due
        if not (live and due):
            return
        try:
            touched = await adapter.touch(page, snapshot.resume_path)
        except Exception as exc:  # noqa: BLE001
            touched = False
            report.receipt["freshness_error"] = type(exc).__name__
        report.receipt["freshness_touched"] = bool(touched)
        if not touched:
            shot = await self._shot(page, report, "freshness-post")
            if shot:
                report.receipt.setdefault("screenshots", []).append(shot)
