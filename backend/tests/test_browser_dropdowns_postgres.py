"""Actual isolated PostgreSQL persistence for transient and manually loaded choices."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.environ.get("PROFILE_TEST_DATABASE_URL"),
    reason="Set disposable local PROFILE_TEST_DATABASE_URL",
)
def test_transient_choices_manual_source_and_review_postgres():
    script = Path(__file__).resolve().parents[1] / "scripts/verify_browser_dropdowns.py"
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: PG17 + TCP FastAPI + Chromium transient dropdown" in result.stdout
