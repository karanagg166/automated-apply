"""PostgreSQL migration and independent transaction races; never production."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.environ.get("PROFILE_TEST_DATABASE_URL"),
    reason="Set local PROFILE_TEST_DATABASE_URL",
)
def test_phase3_postgres_migration_and_concurrency():
    script = Path(__file__).resolve().parents[1] / "scripts/verify_phase3_migration.py"
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr
