"""Only uniquely named disposable local PostgreSQL databases are changed."""

import os
from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.skipif(
    not os.environ.get("PROFILE_TEST_DATABASE_URL"),
    reason="Set PROFILE_TEST_DATABASE_URL to isolated local PostgreSQL",
)
def test_phase2b_postgres_migration_and_concurrency():
    script = Path(__file__).resolve().parents[1] / "scripts/verify_phase2b_migration.py"
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr
