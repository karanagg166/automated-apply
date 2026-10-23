"""One complete generation-to-receipt flow and separate-worker recovery on local PG17."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not os.environ.get("PROFILE_TEST_DATABASE_URL"),
    reason="Set disposable local PROFILE_TEST_DATABASE_URL",
)
@pytest.mark.parametrize("mode", ["valid", "wrong", "multiline"])
def test_complete_narrative_application_postgres(mode):
    script = (
        Path(__file__).resolve().parents[1] / "scripts/verify_complete_application.py"
    )
    result = subprocess.run(
        [sys.executable, str(script), "--multiline-answer"]
        if mode == "multiline"
        else [sys.executable, str(script), "--receipt-mode", mode],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: PG17 + TCP FastAPI + Chromium complete application" in result.stdout


def test_mock_receiver_contract_in_isolated_loopback_subprocess():
    script = (
        Path(__file__).resolve().parents[1] / "scripts/verify_complete_application.py"
    )
    result = subprocess.run(
        [sys.executable, str(script), "--receiver-contract"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: independent V2 receiver" in result.stdout
