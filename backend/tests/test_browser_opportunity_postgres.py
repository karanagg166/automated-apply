"""Actual backend/browser/evidence persistence on a disposable PG17 child DB."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.environ.get("PROFILE_TEST_DATABASE_URL"),
    reason="Set disposable local PROFILE_TEST_DATABASE_URL",
)
def test_reviewed_opportunity_postgres_generation_fill_and_evidence():
    script = (
        Path(__file__).resolve().parents[1] / "scripts/verify_browser_opportunity.py"
    )
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: PG17 + TCP FastAPI + Chromium capture" in result.stdout
