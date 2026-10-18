"""Runs migration checks in a fresh local PostgreSQL database, never Supabase."""
import os
import subprocess
import sys
from pathlib import Path
import pytest


@pytest.mark.skipif(not os.environ.get("PROFILE_TEST_DATABASE_URL"), reason="Set PROFILE_TEST_DATABASE_URL to an isolated local PostgreSQL server")
def test_postgres_migration_and_concurrency():
    script = Path(__file__).resolve().parents[1] / "scripts" / "verify_candidate_profile_migration.py"
    result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
