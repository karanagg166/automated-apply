"""Durable owner-reviewed step progression on disposable PostgreSQL 17 only."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.environ.get("PROFILE_TEST_DATABASE_URL"),
    reason="Set disposable local PROFILE_TEST_DATABASE_URL",
)
def test_owner_reviewed_steps_and_custom_controls_postgres():
    script = Path(__file__).resolve().parents[1] / "scripts/verify_browser_steps.py"
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: PG17 + FastAPI + Chromium radio/custom dropdown/date" in result.stdout
