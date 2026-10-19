"""Run real PostgreSQL migrations, triggers, roles and independent-worker send races."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.environ.get("PROFILE_TEST_DATABASE_URL"),
    reason="Set disposable local PROFILE_TEST_DATABASE_URL",
)
def test_phase4b_postgres_migration_and_concurrency():
    script = Path(__file__).resolve().parents[1] / "scripts/verify_phase4b_migration.py"
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr
