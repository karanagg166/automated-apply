"""Set selection against disposable PostgreSQL 17 only; never real applications."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.environ.get("PROFILE_TEST_DATABASE_URL"),
    reason="Set disposable local PROFILE_TEST_DATABASE_URL",
)
@pytest.mark.parametrize("without_schema", [False, True])
def test_multiple_sets_postgres_and_missing_capability(without_schema):
    script = Path(__file__).resolve().parents[1] / "scripts/verify_browser_multiple.py"
    result = subprocess.run(
        [sys.executable, str(script)]
        + (["--without-schema"] if without_schema else []),
        capture_output=True,
        text=True,
        timeout=150,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "PASS: PG17 flag alone"
        if without_schema
        else "PASS: PG17 + TCP FastAPI + Chromium native/checkbox/ARIA multiple sets"
    ) in result.stdout
