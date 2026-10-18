"""All DDL runs only inside a uniquely named disposable local database."""
import os
from pathlib import Path
import subprocess
import sys
import pytest


@pytest.mark.skipif(not os.environ.get("PROFILE_TEST_DATABASE_URL"), reason="Set PROFILE_TEST_DATABASE_URL to an isolated local PostgreSQL server")
def test_phase2a_migration_and_concurrency():
    script = Path(__file__).resolve().parents[1] / "scripts/verify_phase2a_migration.py"
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
