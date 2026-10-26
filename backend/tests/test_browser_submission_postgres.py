"""Proposed extension lifecycle on disposable PostgreSQL 17 only; no live destinations."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.environ.get("PROFILE_TEST_DATABASE_URL"),
    reason="Set disposable local PROFILE_TEST_DATABASE_URL",
)
def test_mock_submission_postgres_restart_and_unknown_recovery():
    script = (
        Path(__file__).resolve().parents[1] / "scripts/verify_browser_submission.py"
    )
    result = subprocess.run(
        [sys.executable, str(script), "--receipt-mode", "wrong"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: PG17 durable owner grant" in result.stdout
