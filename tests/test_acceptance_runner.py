"""Acceptance orchestration must never turn skipped work or failures into success."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "acceptance_runner",
    Path(__file__).resolve().parents[1] / "scripts/run_acceptance.py",
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_final_postgres_gate_includes_native_browser_after_brave_build():
    stages = dict(runner.STAGES)
    assert list(stages).index("extension-brave-final") < list(stages).index("rust-postgres")
    assert stages["rust-postgres"][-1] == "--with-browser"


def test_first_failure_stops_later_stages_and_persists_truthful_results(tmp_path):
    calls = []

    def invoke(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=7 if command == ["fail"] else 0)

    assert not runner.run_stages(
        (("one", ("ok",)), ("two", ("fail",)), ("three", ("never",))), tmp_path, invoke
    )
    assert calls == [["ok"], ["fail"]]
    rows = json.loads((tmp_path / "results.json").read_text())["stages"]
    assert [row["status"] for row in rows] == ["PASS", "FAIL", "NOT TESTED"]
    assert rows[1]["exit_code"] == 7
    assert not (tmp_path / "three.private.log").exists()
    assert (tmp_path / "results.json").stat().st_mode & 0o077 == 0


def test_unavailable_command_fails_without_leaking_exception_details(tmp_path):
    def invoke(*_args, **_kwargs):
        raise OSError("fictional-secret-canary")

    assert not runner.run_stages((("missing", ("missing",)),), tmp_path, invoke)
    report = (tmp_path / "results.json").read_text()
    assert "fictional-secret-canary" not in report
    assert json.loads(report)["stages"][0]["exit_code"] == 127


def test_timeout_is_a_failure_and_never_replays_or_runs_the_next_stage(tmp_path):
    calls = []

    def invoke(command, **kwargs):
        calls.append(command)
        assert kwargs["timeout"] == 2700
        raise runner.subprocess.TimeoutExpired(command, 2700, output="fictional-secret")

    assert not runner.run_stages(
        (("slow", ("slow",)), ("next", ("never",))), tmp_path, invoke
    )
    assert calls == [["slow"]]
    raw = (tmp_path / "results.json").read_text()
    assert "fictional-secret" not in raw
    rows = json.loads(raw)["stages"]
    assert rows[0]["exit_code"] == 124
    assert rows[1]["status"] == "NOT TESTED"


def test_real_command_timeout_terminates_the_owned_process_group(tmp_path):
    with (tmp_path / "private.log").open("wb") as log:
        with pytest.raises(subprocess.TimeoutExpired):
            runner.bounded_run(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                cwd=tmp_path,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=0.05,
            )


def test_complete_stack_harness_owns_its_lock_without_outer_double_acquisition(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        runner, "bounded_run", lambda command, **kwargs: calls.append(command)
    )
    monkeypatch.setattr(
        runner.fcntl,
        "flock",
        lambda *_args: pytest.fail("nested heavy lock would deadlock"),
    )
    command = ["uv", "run", "python", "scripts/run_fixture_stage.py", "extension-stack"]
    runner.coordinated_run(command)
    assert calls == [command]


def test_heavy_lock_contention_cannot_start_another_stage(monkeypatch):
    def locked(*_args):
        raise BlockingIOError()

    monkeypatch.setattr(runner.fcntl, "flock", locked)
    monkeypatch.setattr(
        runner,
        "bounded_run",
        lambda *_args, **_kwargs: pytest.fail("another heavy owner is active"),
    )
    with pytest.raises(OSError, match="local_heavy_test_lock_busy"):
        runner.coordinated_run(["fictional-fixture"])


def test_timeout_process_selection_excludes_owner_and_reused_process_ids(monkeypatch):
    initial = {
        1: (0, "system"),
        10: (1, "fixture-root"),
        11: (10, "fixture-child"),
        12: (11, "fixture-detached-browser"),
        20: (1, "owner-browser"),
    }
    owned = runner.owned_descendants(10, initial)
    assert owned == {11: "fixture-child", 12: "fixture-detached-browser"}
    now = {**initial, 12: (1, "different-process-reused-pid")}
    signals = []
    monkeypatch.setattr(runner.os, "kill", lambda pid, sig: signals.append(pid))
    runner.signal_owned(owned, runner.signal.SIGTERM, now)
    assert signals == [11]
