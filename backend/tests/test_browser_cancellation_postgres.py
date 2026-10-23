"""Independent PG17 sessions and real TCP/browser cancellation, never live employers."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.environ.get("PROFILE_TEST_DATABASE_URL"),
    reason="Set disposable local PROFILE_TEST_DATABASE_URL",
)
@pytest.mark.parametrize("after_dispatch", [False, True])
def test_cancellation_during_browser_io_and_dispatch_persists_unknown_outcome(
    after_dispatch,
):
    script = (
        Path(__file__).resolve().parents[1] / "scripts/verify_browser_cancellation.py"
    )
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            *(["--after-dispatch"] if after_dispatch else []),
        ],
        capture_output=True,
        text=True,
        timeout=150,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Future exception was never retrieved" not in result.stderr
    assert "PASS: PG17 + TCP FastAPI + Chromium cancellation" in result.stdout
