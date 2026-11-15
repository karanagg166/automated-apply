"""Acceptance orchestration must never turn skipped work or failures into success."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location("acceptance_runner", Path(__file__).resolve().parents[1] / "scripts/run_acceptance.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_first_failure_stops_later_stages_and_persists_truthful_results(tmp_path):
    calls = []
    def invoke(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=7 if command == ["fail"] else 0)
    assert not runner.run_stages((("one", ("ok",)), ("two", ("fail",)), ("three", ("never",))), tmp_path, invoke)
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
