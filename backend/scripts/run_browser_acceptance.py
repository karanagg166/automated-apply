"""Run real Chrome tests with the shared heavy-test lock and fictional fixtures."""

import fcntl
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
with open("/tmp/automated-apply-heavy-tests.lock", "a") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    raise SystemExit(
        subprocess.call(
            [
                sys.executable,
                "-m",
                "pytest",
                "backend/tests/browser_acceptance.py",
                "backend/tests/submission_acceptance.py",
                "-q",
                "--junitxml=reports/browser-acceptance.xml",
            ],
            cwd=root,
        )
    )
