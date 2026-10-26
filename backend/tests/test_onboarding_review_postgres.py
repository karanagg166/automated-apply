"""Disposable PostgreSQL verification; the real profile database is never accepted."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.environ.get("PROFILE_TEST_DATABASE_URL"),
    reason="Requires disposable local PostgreSQL 17",
)
def test_onboarding_review_postgres():
    script = Path(__file__).resolve().parents[1] / "scripts/verify_onboarding_review.py"
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=90
    )
    assert result.returncode == 0, result.stdout + result.stderr
