"""Disposable PG17 verifies real scheduler transactions, transport fixtures only."""

import os
import subprocess
import sys

import pytest


def test_automation_postgres():
    if not os.environ.get("PROFILE_TEST_DATABASE_URL"):
        pytest.skip(
            "Set PROFILE_TEST_DATABASE_URL to disposable localhost PostgreSQL 17"
        )
    result = subprocess.run(
        [sys.executable, "backend/scripts/verify_automation_postgres.py"],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Automation PostgreSQL PASS" in result.stdout
