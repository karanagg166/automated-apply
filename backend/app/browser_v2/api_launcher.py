"""launchd entry for `com.automated-apply.api-v2`.

Rotates the API logs, then `exec`s uvicorn bound to 127.0.0.1:8000 with the private
env file passed as `--env-file` (so no secret ever lives in the plist). `exec` keeps
one PID, so launchd's KeepAlive and SIGTERM reach uvicorn directly.

    backend/venv/bin/python -m backend.app.browser_v2.api_launcher [--check]
"""

from __future__ import annotations

import argparse
import os
import sys

from backend.app.browser_v2.config import env_file
from backend.app.browser_v2.logrotate import rotate_service_logs

HOST = "127.0.0.1"
PORT = 8000
SERVICE = "api-v2"


def uvicorn_argv(env_path: str) -> list[str]:
    return [sys.executable, "-m", "uvicorn", "backend.app.main:app", "--host", HOST, "--port", str(PORT),
            "--env-file", env_path, "--no-proxy-headers", "--timeout-keep-alive", "5",
            "--timeout-graceful-shutdown", "30", "--no-access-log"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="api_launcher")
    parser.add_argument("--check", action="store_true", help="print the resolved command and exit")
    args = parser.parse_args(argv)
    path = env_file()
    if path is None:
        sys.stderr.write("api_v2_env_file_missing: <repo>/.env not found\n")
        return 78  # EX_CONFIG: launchd throttles restarts instead of hot-looping
    command = uvicorn_argv(str(path))
    if args.check:
        print(" ".join(command))
        return 0
    rotate_service_logs(SERVICE)
    # Pool size comes from the env file; backend.app.db.session clamps it to <= 2 + 1 overflow.
    os.execv(sys.executable, command)
    return 0  # pragma: no cover - execv does not return


if __name__ == "__main__":
    sys.exit(main())
