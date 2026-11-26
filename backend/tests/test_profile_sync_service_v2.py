"""Phase 9D ProfileSyncService with fake page/adapter/manager (never a real browser or portal)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar

from backend.app.browser_v2.adapters.base import AuthStatus, SessionCheck
from backend.app.browser_v2.adapters.naukri.profile_updater import NaukriProfileUpdater
from backend.app.browser_v2.profile_sync.adapters import default_profile_adapters
from backend.app.browser_v2.profile_sync.models import FieldStatus, FieldValue
from backend.app.browser_v2.profile_sync.runs import MemoryProfileSyncRuns, runs_for
from backend.app.browser_v2.profile_sync.service import ProfileSyncService
from backend.app.browser_v2.store import MemoryStore

S = FieldStatus
NOON_IST = datetime(2026, 11, 27, 6, 30, tzinfo=UTC)  # 12:00 Asia/Kolkata: inside 08:00-23:30
MIDNIGHT_IST = datetime(2026, 11, 27, 20, 0, tzinfo=UTC)  # 01:30 Asia/Kolkata: outside


class TouchlessPage:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"page touched: {name}")


class FakeManager:
    def __init__(self, page: Any = None) -> None:
        self.page = page or object()
        self.jobs = 0

    @asynccontextmanager
    async def job(self):
        self.jobs += 1
        yield self.page


class FakeSession:
    def __init__(self, status: str = "OK") -> None:
        self.status = status

    async def check_session(self, page: Any) -> SessionCheck:
        return SessionCheck(AuthStatus(self.status))


class FakeReceipts:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.labels: list[str] = []

    async def capture(self, page: Any, platform: str, job_id: str, label: str) -> str:
        path = self.folder / f"{platform}-{label}.png"
        path.write_bytes(b"png")
        self.labels.append(label)
        return str(path)


class FakeAdapter:
    platform = "naukri"
    supported_fields = frozenset({"resume_headline", "profile_summary", "key_skills", "notice_period",
                                  "current_ctc", "expected_ctc", "preferred_locations", "resume_pdf"})
    calibrated = True
    calibrated_fields = supported_fields - {"resume_pdf"}
    freshness_touch = True
    selectors: ClassVar[dict[str, str | None]] = {}
    profile_url = None

    def __init__(self, portal: dict[str, Any], *, save_ok: bool = True, garble: frozenset[str] = frozenset(),
                 raise_on: frozenset[str] = frozenset()) -> None:
        self.portal = dict(portal)
        self.save_ok, self.garble, self.raise_on = save_ok, garble, raise_on
        self.writes: list[tuple[str, Any]] = []
        self.touches: list[str | None] = []

    async def read(self, page: Any) -> dict[str, FieldValue]:
        out = {f: FieldValue(self.portal.get(f)) for f in self.supported_fields if f != "resume_pdf"}
        out["resume_pdf"] = FieldValue(status=S.SKIPPED_NOT_CALIBRATED, reason="not_observable")
        return out

    async def write(self, page: Any, field: str, value: Any) -> bool:
        self.writes.append((field, value))
        if field in self.raise_on:
            raise RuntimeError("selector vanished")
        if not self.save_ok:
            return False
        if field in self.garble:
            self.portal[field] = "garbled"
        elif field == "key_skills":
            self.portal[field] = [*self.portal.get(field, []), *value]
        else:
            self.portal[field] = value
        return True

    async def touch(self, page: Any, resume_path: str | None = None) -> bool:
        self.touches.append(resume_path)
        return True


def make_store(tmp_path: Path, *, live: bool = False, **prefs: Any) -> MemoryStore:
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4 resume")
    base = {"headline": "Backend Engineer", "summary": "Builds reliable APIs", "tech_stack": ["Python", "FastAPI"],
            "notice_period_days": 30, "current_ctc": 12.5, "expected_ctc": 18,
            "preferred_locations": ["Bengaluru"], "resume_files": {"default": str(pdf)}}
    if live:
        base["profile_sync"] = {"naukri": {"live": True}}
    return MemoryStore(profile={"preferences": base | prefs})


PORTAL = {"resume_headline": "Backend Engineer", "profile_summary": "Old summary", "key_skills": ["Python"],
          "notice_period": "1 Month", "current_ctc": "12.5 Lacs", "expected_ctc": "15 LPA",
          "preferred_locations": ["bengaluru"]}


def service_for(store, adapter, tmp_path, *, session="OK", now=NOON_IST, runs=None, page=None):
    receipts = FakeReceipts(tmp_path)
    runs = runs or MemoryProfileSyncRuns(clock=lambda: now)
    svc = ProfileSyncService(store, FakeManager(page), {"naukri": adapter}, runs, lambda: now, receipts,
                             session_adapters={"naukri": FakeSession(session)})
    return svc, runs, receipts


async def test_dry_run_reports_diffs_and_writes_nothing(tmp_path):
    adapter = FakeAdapter(PORTAL)
    svc, runs, _ = service_for(make_store(tmp_path, live=True), adapter, tmp_path)
    report = await svc.sync("naukri", dry_run=True, trigger="cli")
    assert adapter.writes == [] and adapter.touches == []
    st = {k: v.status for k, v in report.statuses.items()}
    assert st["profile_summary"] is S.WOULD_UPDATE and st["expected_ctc"] is S.WOULD_UPDATE
    assert st["key_skills"] is S.WOULD_UPDATE and report.statuses["key_skills"].additions == ("FastAPI",)
    assert st["resume_headline"] is S.UNCHANGED and st["current_ctc"] is S.UNCHANGED
    assert st["current_location"] is S.SKIPPED_UNSUPPORTED and st["resume_pdf"] is S.SKIPPED_NOT_CALIBRATED
    assert report.dry_run and report.status == "ok" and report.receipt["freshness_due"] is True
    row = await runs.last("naukri")
    assert row["status"] == "ok" and row["dry_run"] is True and row["trigger"] == "cli"
    assert row["fields"]["profile_summary"]["status"] == "would_update"
    assert "Builds reliable" not in repr(row) and "Old summary" not in repr(row)  # SHA-256 refs only


async def test_live_flag_off_means_no_writes(tmp_path):
    adapter = FakeAdapter(PORTAL)
    svc, runs, _ = service_for(make_store(tmp_path, live=False), adapter, tmp_path)
    report = await svc.sync("naukri", dry_run=False, trigger="telegram")
    assert adapter.writes == [] and adapter.touches == []
    assert report.dry_run and report.receipt["live_blocked"] == "profile_sync_live_flag_off"
    assert (await runs.last("naukri"))["dry_run"] is True


async def test_live_writes_one_field_at_a_time_and_verifies(tmp_path):
    adapter = FakeAdapter(PORTAL)
    svc, runs, _ = service_for(make_store(tmp_path, live=True), adapter, tmp_path)
    report = await svc.sync("naukri", dry_run=False, trigger="cli")
    written = dict(adapter.writes)
    assert set(written) == {"profile_summary", "expected_ctc", "key_skills"}
    assert written["key_skills"] == ["FastAPI"]  # add-only: only the additions are sent
    assert all(report.statuses[f].status is S.UPDATED for f in written)
    assert report.status == "ok" and not report.dry_run
    assert not list(tmp_path.glob("*-pre.png"))  # pre screenshots of successful saves are discarded
    assert report.receipt["freshness_touched"] is True and adapter.touches == [str(tmp_path / "resume.pdf")]
    assert await runs.last_freshness_touch("naukri") == NOON_IST


async def test_never_empty_rule_in_live_mode(tmp_path):
    adapter = FakeAdapter(PORTAL)
    svc, _, _ = service_for(make_store(tmp_path, live=True, summary=None, headline=None), adapter, tmp_path)
    report = await svc.sync("naukri", dry_run=False, trigger="cli")
    assert "profile_summary" not in dict(adapter.writes) and "resume_headline" not in dict(adapter.writes)
    assert report.statuses["profile_summary"].status is S.SKIPPED_EMPTY_SOURCE


async def test_verify_failed_and_failed_save_is_never_retried(tmp_path):
    adapter = FakeAdapter(PORTAL, garble=frozenset({"profile_summary"}), raise_on=frozenset({"expected_ctc"}))
    svc, runs, receipts = service_for(make_store(tmp_path, live=True), adapter, tmp_path)
    report = await svc.sync("naukri", dry_run=False, trigger="cli")
    assert report.statuses["profile_summary"].status is S.VERIFY_FAILED
    assert report.statuses["expected_ctc"].status is S.ERROR
    assert report.statuses["expected_ctc"].reason == "write_error:RuntimeError"
    assert report.statuses["key_skills"].status is S.UPDATED
    assert [f for f, _ in adapter.writes].count("expected_ctc") == 1
    assert report.status == "partial" and (await runs.last("naukri"))["status"] == "partial"
    assert {"profile_summary-pre", "profile_summary-post", "expected_ctc-pre", "expected_ctc-post"} <= set(
        receipts.labels)
    assert len(report.receipt["screenshots"]) == 4


async def test_save_not_confirmed_is_error(tmp_path):
    adapter = FakeAdapter(PORTAL, save_ok=False)
    svc, _, _ = service_for(make_store(tmp_path, live=True), adapter, tmp_path)
    report = await svc.sync("naukri", dry_run=False, trigger="cli")
    assert report.statuses["profile_summary"].status is S.ERROR and report.status == "failed"


async def test_auth_required_stops_before_any_read_or_write(tmp_path):
    adapter = FakeAdapter(PORTAL)
    svc, runs, _ = service_for(make_store(tmp_path, live=True), adapter, tmp_path, session="AUTH_REQUIRED")
    report = await svc.sync("naukri", dry_run=False, trigger="schedule")
    assert report.status == "auth_required" and adapter.writes == [] and report.statuses == {}
    assert (await runs.last("naukri"))["status"] == "auth_required"


async def test_uncalibrated_adapters_never_touch_the_page_or_open_the_browser(tmp_path):
    store = make_store(tmp_path, live=True)
    runs = MemoryProfileSyncRuns()
    manager = FakeManager(TouchlessPage())
    svc = ProfileSyncService(store, manager, default_profile_adapters(), runs, receipts=FakeReceipts(tmp_path))
    for platform in ("naukri", "instahyre", "internshala", "wellfound", "work_at_a_startup"):
        report = await svc.sync(platform, dry_run=False, trigger="cli")
        assert report.status == "skipped" and report.receipt["calibrated"] is False
        assert {d.status for d in report.statuses.values()} <= {S.SKIPPED_NOT_CALIBRATED, S.SKIPPED_UNSUPPORTED}
    assert manager.jobs == 0
    updater = NaukriProfileUpdater()
    assert not updater.calibrated
    assert {v.status for v in (await updater.read(TouchlessPage())).values()} == {S.SKIPPED_NOT_CALIBRATED}
    assert await updater.write(TouchlessPage(), "profile_summary", "x") is False
    assert await updater.touch(TouchlessPage(), "/tmp/x.pdf") is False


async def test_freshness_touch_due_and_not_due(tmp_path):
    store = make_store(tmp_path, live=True)
    runs = MemoryProfileSyncRuns(clock=lambda: NOON_IST)
    unchanged = {**PORTAL, "profile_summary": "Builds reliable APIs", "expected_ctc": 18,
                 "key_skills": ["Python", "FastAPI"]}
    adapter = FakeAdapter(unchanged)
    svc, _, _ = service_for(store, adapter, tmp_path, runs=runs)
    first = await svc.sync("naukri", dry_run=False, trigger="schedule")
    assert adapter.writes == [] and first.receipt["freshness_touched"] is True and first.status == "ok"
    second = await svc.sync("naukri", dry_run=False, trigger="schedule")  # < 24 h since the touch
    assert second.receipt["freshness_due"] is False and len(adapter.touches) == 1
    later = NOON_IST + timedelta(hours=25)
    svc.clock = runs.clock = lambda: later
    assert (await svc.sync("naukri", dry_run=False, trigger="schedule")).receipt["freshness_touched"] is True
    night, _, _ = service_for(store, FakeAdapter(unchanged), tmp_path, now=MIDNIGHT_IST)
    assert (await night.sync("naukri", dry_run=False, trigger="schedule")).receipt["freshness_due"] is False
    dry = FakeAdapter(unchanged)
    dry_svc, _, _ = service_for(store, dry, tmp_path)
    assert (await dry_svc.sync("naukri", dry_run=True)).receipt["freshness_due"] is True and dry.touches == []


async def test_runs_for_picks_memory_per_store_and_postgres_on_connection():
    store = MemoryStore()
    assert runs_for(store) is runs_for(store)

    class PgLike:
        connection = object()

    assert type(runs_for(PgLike())).__name__ == "PostgresProfileSyncRuns"
