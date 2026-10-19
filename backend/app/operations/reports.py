"""Private runtime artifacts, written atomically; no profile or contact bodies."""

import json
import os
import shutil

# Fixed local command with no user-controlled arguments.
import subprocess  # nosec B404
from datetime import datetime, timezone
from pathlib import Path


def execution_metadata(mode, environment):
    git = shutil.which("git")
    sha = os.environ.get("SOURCE_REVISION", "")
    if git and not sha:
        # Fixed command with an absolute executable; no shell or user input.
        sha = subprocess.run(  # nosec B603
            [git, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        ).stdout.strip()
    return dict(
        executed_at=datetime.now(timezone.utc).isoformat(),
        git_commit=sha or "unavailable",
        mode=mode,
        environment=environment,
        production_ready=False,
        real_pilot_verified=False,
    )


def write_report(output, report):
    directory = Path(output)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    for suffix, text in (
        ("json", json.dumps(report, indent=2, default=str) + "\n"),
        (
            "md",
            "# Phase 6B pilot execution\n\n```json\n"
            + json.dumps(report, indent=2, default=str)
            + "\n```\n",
        ),
    ):
        target = directory / ("phase6b-pilot-summary." + suffix)
        temporary = directory / (target.name + ".tmp")
        # Refuse symlinks and truncate only files opened with private permissions.
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600
        )
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except BaseException:
            raise
