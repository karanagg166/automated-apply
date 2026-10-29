"""Synthetic OS telemetry only; these cases prove no locked-screen execution."""

import os
import subprocess
import sys
from pathlib import Path

from backend.scripts.monitor_naukri_acceptance import lock_observation


def test_lock_monitor_requires_unambiguous_owner_session():
    assert (
        lock_observation(
            [
                {
                    "IOConsoleUsers": [
                        {"kCGSSessionUserIDKey": 501, "CGSSessionScreenIsLocked": True}
                    ]
                }
            ],
            501,
        )
        == "LOCKED"
    )
    assert (
        lock_observation(
            [
                {
                    "IOConsoleUsers": [
                        {"kCGSSessionUserIDKey": 501, "CGSSessionScreenIsLocked": False}
                    ]
                }
            ],
            501,
        )
        == "UNLOCKED"
    )
    for document in [
        {},
        [
            {
                "IOConsoleUsers": [
                    {"kCGSSessionUserIDKey": 502, "CGSSessionScreenIsLocked": True}
                ]
            }
        ],
        [{"IOConsoleUsers": [{"kCGSSessionUserIDKey": 501}]}],
    ]:
        assert lock_observation(document, 501) == "UNKNOWN"


def test_monitor_file_entrypoint_reaches_configuration_from_outside_checkout(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/monitor_naukri_acceptance.py"
    output = tmp_path / "must-not-be-created.jsonl"
    env = {**os.environ, "ENVIRONMENT": "invalid_monitor_test_environment"}
    env.pop("PYTHONPATH", None)
    # Reject fictional configuration before any API, database or OS telemetry
    # access. This exercises the same absolute-file invocation as release tools.
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--env-file", str(tmp_path / "absent.env"),
            "--output", str(output),
            "--duration-seconds", "30",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode != 0
    assert "invalid_configuration_fields:ENVIRONMENT" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr
    assert not output.exists()
