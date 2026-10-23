"""Asset-loaded forms against actual TCP API and disposable PostgreSQL 17."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.environ.get("PROFILE_TEST_DATABASE_URL"),
    reason="Set disposable local PROFILE_TEST_DATABASE_URL",
)
def test_public_asset_bootstrap_postgres():
    script = Path(__file__).resolve().parents[1] / "scripts/verify_browser_assets.py"
    result = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: PG17 + TCP FastAPI + Chromium approved public JS/CSS" in result.stdout
