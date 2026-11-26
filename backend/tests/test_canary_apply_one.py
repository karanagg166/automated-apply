"""Phase 8 `cli apply-one` canary guardrails (never touches a real portal or DB)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.canary import CanaryRefused, apply_one, preflight, summary
from backend.app.browser_v2.cli import main
from backend.app.browser_v2.rules import PortalRules
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore

GH_URL = "https://job-boards.greenhouse.io/acme/jobs/4012345"


class FakeManager:
    running = False

    @asynccontextmanager
    async def job(self):
        yield object()

    async def close(self) -> None:
        self.closed = True


class FakeService:
    def __init__(self, store: MemoryStore, *, session: str = "OK", outcome: dict[str, Any] | None = None) -> None:
        self.store = store
        self.manager = FakeManager()
        self.session = session
        self.outcome = outcome or {"state": "SCORED", "reason": "dry_run_stopped_before_submit"}
        self.calls: list[tuple[str, str, bool]] = []

    async def configure_adapters(self) -> None:
        return None

    async def check_portal_session(self, platform: str) -> dict[str, Any]:
        return {"status": self.session, "reason": None if self.session == "OK" else "login"}

    async def quota_block(self, platform: str, rules: Any = None) -> str | None:
        return None

    async def apply_to_job(self, platform: str, url: str, *, dry_run: bool) -> dict[str, Any]:
        self.calls.append((platform, url, dry_run))
        return self.outcome


def factory_for(service: FakeService, backend: str = "postgres"):
    async def factory(*, require_db: bool):
        factory.require_db = require_db  # type: ignore[attr-defined]
        return service, backend
    return factory


def store() -> MemoryStore:
    return MemoryStore(rules={"greenhouse": PortalRules(platform="greenhouse", enabled=True)})


def test_preflight_rules():
    assert preflight("greenhouse", GH_URL, live=False, confirm_live=False, backend="memory") == "4012345"
    with pytest.raises(CanaryRefused, match="confirm-live"):
        preflight("greenhouse", GH_URL, live=True, confirm_live=False, backend="postgres")
    with pytest.raises(CanaryRefused, match="postgres"):
        preflight("greenhouse", GH_URL, live=True, confirm_live=True, backend="memory")
    with pytest.raises(CanaryRefused, match="unrecognized"):
        preflight("greenhouse", "https://example.com/not-a-job", live=False, confirm_live=False, backend="memory")


async def test_default_is_dry_run_and_never_requires_db(tmp_path):
    service = FakeService(store())
    factory = factory_for(service, "memory")
    report = await apply_one("greenhouse", GH_URL, confirm_live=False, service_factory=factory,
                             evidence_dir=tmp_path)
    assert report["ok"] and report["mode"] == "dry_run" and factory.require_db is False
    assert service.calls == [("greenhouse", GH_URL, True)]
    assert (tmp_path / report["evidence"].rsplit("/", 1)[-1]).exists()


@pytest.mark.parametrize("state", [S.APPLIED, S.SUBMISSION_UNKNOWN, S.APPLYING, S.WAITING_FOR_USER])
async def test_never_replay_and_in_flight_jobs_are_refused_before_any_click(state, tmp_path):
    memory = store()
    record = await memory.upsert_discovered(JobListing(platform="greenhouse", external_job_id="4012345", url=GH_URL))
    record = await memory.transition(record, S.APPLYING, "apply_started")
    if state is not S.APPLYING:
        await memory.transition(record, state, "x")
    service = FakeService(memory)
    report = await apply_one("greenhouse", GH_URL, confirm_live=True, assume_yes=True,
                             service_factory=factory_for(service), evidence_dir=tmp_path)
    assert not report["ok"] and "never_replay_or_in_flight" in report["refused"] and service.calls == []


async def test_live_needs_typed_confirmation_and_a_terminal(tmp_path):
    service = FakeService(store())
    report = await apply_one("greenhouse", GH_URL, confirm_live=True, service_factory=factory_for(service),
                             is_tty=False, evidence_dir=tmp_path)
    assert report["refused"].startswith("live_needs_typed_confirmation") and service.calls == []
    report = await apply_one("greenhouse", GH_URL, confirm_live=True, service_factory=factory_for(service),
                             is_tty=True, input_fn=lambda _prompt: "yes", evidence_dir=tmp_path)
    assert report["refused"] == "confirmation_mismatch" and service.calls == []
    service.outcome = {"state": "APPLIED", "reason": "confirmed", "receipt": {"source": "success_text"}}
    report = await apply_one("greenhouse", GH_URL, confirm_live=True, service_factory=factory_for(service),
                             is_tty=True, input_fn=lambda _prompt: "APPLY greenhouse", evidence_dir=tmp_path)
    assert report["ok"] and service.calls == [("greenhouse", GH_URL, False)]


async def test_live_refuses_memory_store_and_bad_session(tmp_path):
    service = FakeService(store())
    report = await apply_one("greenhouse", GH_URL, confirm_live=True, assume_yes=True,
                             service_factory=factory_for(service, "memory (OSError: no db)"), evidence_dir=tmp_path)
    assert "postgres" in report["refused"]
    service = FakeService(store(), session="AUTH_REQUIRED")
    report = await apply_one("greenhouse", GH_URL, confirm_live=False, service_factory=factory_for(service),
                             evidence_dir=tmp_path)
    assert report["refused"].startswith("session_not_ok") and service.calls == []


async def test_telegram_summary_is_sent_and_failures_are_contained(tmp_path):
    sent: list[str] = []

    async def notify(text: str) -> None:
        sent.append(text)

    service = FakeService(store())
    report = await apply_one("greenhouse", GH_URL, confirm_live=False, service_factory=factory_for(service),
                             notify=notify, evidence_dir=tmp_path)
    assert sent and sent[0].startswith("🧪 Canary dry-run greenhouse") and report["ok"]
    assert "refused" in summary({"ok": False, "portal": "naukri", "refused": "x", "mode": "live"})


def test_cli_registers_apply_one_and_facts(capsys):
    with pytest.raises(SystemExit):
        main(["apply-one", "--help"])
    assert "--confirm-live" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["facts", "--help"])
    assert "reseed-cache" in capsys.readouterr().out
