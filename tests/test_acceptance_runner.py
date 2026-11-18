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
    assert list(stages).index("extension-brave-final") < list(stages).index(
        "rust-postgres"
    )
    assert stages["rust-postgres"][-1] == "--with-browser"


def test_combined_gate_rehearses_the_reviewed_schema_with_no_manifest_write():
    stages = dict(runner.STAGES)
    assert stages["rust-migration-catalog"][-2:] == (
        "-m",
        "rust.scripts.verify_live_migration",
    )


@pytest.mark.parametrize(
    ("dirty_at_start", "dirty_at_end", "changed_commit", "exit_code", "clean_pass"),
    [
        (False, False, False, 0, True),
        (True, True, False, 0, False),
        (False, True, False, 0, False),
        (False, False, True, 0, False),
        (False, False, False, 7, False),
    ],
)
@pytest.mark.parametrize("keep_going", [False, True])
def test_final_report_identifies_only_a_clean_commit_fixture_pass(
    tmp_path, dirty_at_start, dirty_at_end, changed_commit, exit_code, clean_pass, keep_going
):
    before = {"commit": "1" * 40, "clean": not dirty_at_start}
    after = {"commit": ("2" if changed_commit else "1") * 40, "clean": not dirty_at_end}
    stamps = iter((before, after))

    def invoke(command, **_kwargs):
        if command == ["first"]:
            return SimpleNamespace(returncode=0)
        intermediate = json.loads((tmp_path / "results.json").read_text())
        assert not intermediate["clean_commit_fixture_pass"]
        assert intermediate["source_after"] is None
        return SimpleNamespace(returncode=exit_code)

    assert runner.run_stages(
        (("one", ("first",)), ("two", ("second",))),
        tmp_path,
        invoke,
        capture_source=lambda: next(stamps),
        keep_going=keep_going,
    ) is (exit_code == 0)
    report = json.loads((tmp_path / "results.json").read_text())
    assert report["source_before"] == before
    assert report["source_after"] == after
    assert report["clean_commit_fixture_pass"] is clean_pass


def test_first_failure_stops_later_stages_and_persists_truthful_results(tmp_path):
    calls = []
    source = {"commit": "1" * 40, "clean": True}

    def invoke(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=7 if command == ["fail"] else 0)

    assert not runner.run_stages(
        (("one", ("ok",)), ("two", ("fail",)), ("three", ("never",))),
        tmp_path,
        invoke,
        capture_source=lambda: source,
    )
    assert calls == [["ok"], ["fail"]]
    report = json.loads((tmp_path / "results.json").read_text())
    assert report["source_after"] == source
    assert not report["clean_commit_fixture_pass"]
    rows = report["stages"]
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


def test_keep_going_runs_independent_stages_and_skips_failed_artifact_dependencies(
    tmp_path,
):
    calls = []
    source = {"commit": "1" * 40, "clean": True}

    def invoke(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=7 if command == ["build"] else 0)

    assert not runner.run_stages(
        (
            ("frontend-build", ("build",)),
            ("frontend-cutover-bundle", ("bundle",)),
            ("frontend-cutover-e2e", ("e2e",)),
            ("extension-tests", ("independent",)),
        ),
        tmp_path,
        invoke,
        capture_source=lambda: source,
        keep_going=True,
    )
    assert calls == [["build"], ["independent"]]
    report = json.loads((tmp_path / "results.json").read_text())
    assert report["source_after"] == source
    assert not report["clean_commit_fixture_pass"]
    rows = report["stages"]
    assert [row["status"] for row in rows] == ["FAIL", "NOT TESTED", "NOT TESTED", "PASS"]
    assert rows[1]["unmet_prerequisites"] == ["frontend-build"]
    assert rows[2]["unmet_prerequisites"] == ["frontend-cutover-bundle"]


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
