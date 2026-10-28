"""No live DDL: uniquely named disposable local PostgreSQL 17 databases only."""

import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(
    not os.environ.get("PROFILE_TEST_DATABASE_URL"),
    reason="Disposable localhost PostgreSQL 17 required",
)
def test_phase3_readonly_schema_security_and_recovery():
    result = subprocess.run(
        [sys.executable, "backend/scripts/verify_phase3_integrations_postgres.py"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
