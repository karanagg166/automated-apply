"""Run one allowlisted final-gate stage with no ambient credentials or owner browser."""

import argparse
import subprocess
from pathlib import Path

from disposable_postgres import fixture_environment, native_postgres

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv/bin/python"
COMMANDS = {
    "backend": (
        str(PYTHON),
        "-m",
        "pytest",
        "-p",
        "backend.tests.fixture_isolation",
        "backend/tests",
        "-q",
        "--durations=12",
    ),
    "frontend-ui": ("pnpm", "-C", "frontend", "e2e"),
    "frontend-cutover": ("node", "--test", "frontend/tests/local-rust-launch.mjs"),
    "frontend-browser": ("pnpm", "-C", "frontend", "e2e:browser"),
    "frontend-extension": (
        "pnpm",
        "-C",
        "frontend",
        "exec",
        "playwright",
        "test",
        "--config",
        "playwright.extension.config.ts",
    ),
    "frontend-naukri": (
        "pnpm",
        "-C",
        "frontend",
        "exec",
        "playwright",
        "test",
        "--config",
        "playwright.naukri.config.ts",
    ),
    "extension-browser": ("node", "extension/tests/run-browser-fixtures.mjs"),
    "extension-stack": ("node", "extension/tests/chrome-e2e.mjs"),
    "backend-browser": (
        str(PYTHON),
        "-m",
        "pytest",
        "-p",
        "backend.tests.fixture_isolation",
        "backend/tests/browser_acceptance.py",
        "backend/tests/submission_acceptance.py",
        "-q",
    ),
}


def stage_environment():
    return {
        **fixture_environment(),
        "PYTHON": str(PYTHON),
        "AUTOMATED_APPLY_TEST_BROWSER": "brave",
        "AUTOMATED_APPLY_FIXTURE_ISOLATED": "1",
        "CI": "1",  # Headless fixtures and no interactive retries.
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=tuple(COMMANDS))
    selected = parser.parse_args().stage
    if not PYTHON.is_file():
        raise SystemExit("canonical_uv_environment_required")
    environment = stage_environment()
    # Backend combines unit + every PostgreSQL integration exactly once. Browser
    # workspace fixtures create child DBs under this invocation's cluster.
    if selected in {"backend", "frontend-browser"}:
        with native_postgres() as url:
            environment["PROFILE_TEST_DATABASE_URL"] = url
            code = subprocess.call(COMMANDS[selected], cwd=ROOT, env=environment)
    else:
        code = subprocess.call(COMMANDS[selected], cwd=ROOT, env=environment)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
