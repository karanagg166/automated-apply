"""Real PostgreSQL queue locks/restart, never genuine applicant data."""

import os
import subprocess
import sys

import pytest


def test_execution_postgres():
    if not os.environ.get("PROFILE_TEST_DATABASE_URL"):
        pytest.skip("Requires disposable localhost PostgreSQL 17")
    result = subprocess.run(
        [sys.executable, "-m", "backend.scripts.verify_execution_postgres"],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Execution PostgreSQL PASS" in result.stdout
