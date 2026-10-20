"""The CI watchdog must preserve failures and bound subprocess descendants."""

import subprocess
import sys
import time

import pytest

SCRIPT = "backend/scripts/run_backend_ci.py"


@pytest.mark.parametrize("code", [0, 7])
def test_supervisor_preserves_command_result_and_log(tmp_path, code):
    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--output",
            str(tmp_path),
            sys.executable,
            "-c",
            f"print('fictional test output', flush=True); raise SystemExit({code})",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == code
    assert "fictional test output" in result.stdout
    assert "fictional test output" in (tmp_path / "pytest.log").read_text()
    assert f"exit_code={code}" in (tmp_path / "supervisor.txt").read_text()


def test_supervisor_does_not_wait_for_inherited_child_stdout(tmp_path):
    # A pipe/tee implementation can wait 60s for this descendant's inherited FD.
    command = "import subprocess, sys; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); print('parent exited', flush=True)"
    started = time.monotonic()
    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--output",
            str(tmp_path),
            sys.executable,
            "-c",
            command,
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0 and "parent exited" in result.stdout
    assert time.monotonic() - started < 15


def test_supervisor_timeout_is_a_failure(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            SCRIPT,
            "--output",
            str(tmp_path),
            "--seconds",
            "0.5",
            sys.executable,
            "-c",
            "import time; print('started', flush=True); time.sleep(60)",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 124
    assert "started" in (tmp_path / "pytest.log").read_text()
    assert "exit_code=124" in (tmp_path / "supervisor.txt").read_text()
