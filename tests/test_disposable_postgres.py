"""Harness lifecycle proofs; subprocesses are fictional stubs, never a real DB."""

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location(
    "fixture_postgres",
    Path(__file__).resolve().parents[1] / "scripts/disposable_postgres.py",
)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def setup_fake_cluster(tmp_path, monkeypatch, *, stopped=True):
    binary = tmp_path / "bin"
    binary.mkdir()
    for name in ("initdb", "pg_ctl", "createdb"):
        (binary / name).write_text("fictional tool; never executed")
    base = tmp_path / "automated-apply-fictional-pg-test"
    base.mkdir()
    monkeypatch.setattr(fixture, "POSTGRES_BIN", binary)
    monkeypatch.setattr(fixture.tempfile, "mkdtemp", lambda **_kwargs: str(base))
    calls = []

    def invoke(command, **kwargs):
        calls.append(command)
        assert "DATABASE_URL" not in kwargs["env"]
        assert "PGHOST" not in kwargs["env"]
        assert kwargs["env"]["PGPASSFILE"] == "/dev/null"
        if Path(command[0]).name == "initdb":
            (base / "data").mkdir()
        if command[-1] in {"stop", "status"} and not stopped:
            return SimpleNamespace(returncode=4)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(fixture.subprocess, "run", invoke)
    return base, calls


def test_owned_cluster_stops_and_is_removed_when_fixture_body_fails(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("DATABASE_URL", "fictional-owner-dsn-must-not-forward")
    monkeypatch.setenv("PGHOST", "private-owner-host.invalid")
    base, calls = setup_fake_cluster(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="fictional body failure"):
        with fixture.native_postgres() as url:
            assert url.startswith("postgresql://postgres@127.0.0.1:")
            assert url.endswith("/candidate_profile_test")
            assert base.stat().st_mode & 0o077 == 0
            raise ValueError("fictional body failure")
    assert calls[-1][-1] == "stop"
    assert not base.exists()


def test_uncertain_shutdown_preserves_cluster_and_fails_stage(tmp_path, monkeypatch):
    base, calls = setup_fake_cluster(tmp_path, monkeypatch, stopped=False)
    with pytest.raises(RuntimeError, match="fixture_postgres_shutdown_failed"):
        with fixture.native_postgres():
            pass
    assert calls[-1][-1] == "status"
    assert base.exists()
    assert (base / "data").is_dir()


def test_start_failure_still_attempts_owned_cluster_shutdown(tmp_path, monkeypatch):
    base, calls = setup_fake_cluster(tmp_path, monkeypatch)
    initial = fixture.subprocess.run

    def invoke(command, **kwargs):
        result = initial(command, **kwargs)
        if command[-1] == "start":
            raise subprocess.TimeoutExpired(command, 30)
        return result

    monkeypatch.setattr(fixture.subprocess, "run", invoke)
    with pytest.raises(subprocess.TimeoutExpired):
        with fixture.native_postgres():
            pytest.fail("failed startup must not yield a fixture URL")
    assert calls[-1][-1] == "stop"
    assert not base.exists()


def test_fixture_environment_drops_ambient_keys_and_python_injection(monkeypatch):
    for name in (
        "DATABASE_URL",
        "GEMINI_API_KEY",
        "APIFY_API_TOKEN",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PGOPTIONS",
    ):
        monkeypatch.setenv(name, "fictional-canary-must-not-forward")
    environment = fixture.fixture_environment()
    assert all("fictional-canary" not in value for value in environment.values())
    assert environment["PYTHONNOUSERSITE"] == "1"
