"""Real transactional races are verified only against disposable local PostgreSQL."""

import os
import subprocess
import sys

import pytest


def test_resume_sync_postgres():
    if not os.environ.get("PROFILE_TEST_DATABASE_URL"):
        pytest.skip("Set PROFILE_TEST_DATABASE_URL to disposable localhost PostgreSQL")
    result = subprocess.run([sys.executable, "backend/scripts/verify_resume_sync_migration.py"], capture_output=True, text=True, timeout=90, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Resume sync PostgreSQL PASS" in result.stdout
