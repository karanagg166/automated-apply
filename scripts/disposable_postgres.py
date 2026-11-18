"""Owned, native PostgreSQL 17 cluster for fictional local acceptance only."""

import os
import secrets
import shutil
import signal
import socket
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

POSTGRES_BIN = Path("/opt/homebrew/opt/postgresql@17/bin")


def fixture_environment():
    # Never forward account/provider keys, DB URLs, PG options or Python injection.
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(Path.home()),
        "LANG": "C",
        "LC_ALL": "C",
        "PYTHONNOUSERSITE": "1",
        "ENVIRONMENT": "testing",
        "PGPASSFILE": "/dev/null",
        "PGSERVICEFILE": "/dev/null",
    }


@contextmanager
def native_postgres():
    """No caller-supplied URL/database/directory; this invocation owns every byte."""
    binary = POSTGRES_BIN
    for name in ("initdb", "pg_ctl", "createdb"):
        if not (binary / name).is_file():
            raise RuntimeError("native_postgresql17_tools_required")
    base = Path(tempfile.mkdtemp(prefix="automated-apply-fictional-pg-"))
    base.chmod(0o700)
    data = base / "data"
    password = secrets.token_urlsafe(32)
    environment = fixture_environment()
    attempted = False
    stopped = True

    def interrupted(_signal, _frame):
        raise SystemExit(143)

    previous = signal.signal(signal.SIGTERM, interrupted)
    try:
        with (base / "setup.private.log").open("xb") as log:
            log_path = Path(log.name)
            log_path.chmod(0o600)

            def run(arguments, *, authenticated=False):
                subprocess.run(
                    arguments,
                    env={**environment, "PGPASSWORD": password}
                    if authenticated
                    else environment,
                    stdout=log,
                    stderr=log,
                    check=True,
                    timeout=30,
                )

            with tempfile.NamedTemporaryFile(mode="w", dir=base) as password_file:
                password_file.write(password + "\n")
                password_file.flush()
                run(
                    [
                        str(binary / "initdb"),
                        "-D",
                        str(data),
                        "-U",
                        "postgres",
                        "--no-locale",
                        "-E",
                        "UTF8",
                        "--auth=scram-sha-256",
                        "--pwfile",
                        password_file.name,
                    ]
                )
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            options = (
                f"-h 127.0.0.1 -p {port} -k {base} -c shared_buffers=16MB "
                "-c max_connections=40 -c work_mem=1MB"
            )
            attempted = True
            stopped = False
            run(
                [
                    str(binary / "pg_ctl"),
                    "-D",
                    str(data),
                    "-l",
                    str(base / "postgres.private.log"),
                    "-w",
                    "-t",
                    "15",
                    "-o",
                    options,
                    "start",
                ]
            )
            run(
                [
                    str(binary / "createdb"),
                    "-h",
                    "127.0.0.1",
                    "-p",
                    str(port),
                    "-U",
                    "postgres",
                    "candidate_profile_test",
                ],
                authenticated=True,
            )
        yield f"postgresql://postgres:{password}@127.0.0.1:{port}/candidate_profile_test"
    finally:
        # Keep the parent's timeout cleanup window long enough for this shutdown.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            if attempted:
                try:
                    result = subprocess.run(
                        [
                            str(binary / "pg_ctl"),
                            "-D",
                            str(data),
                            "-w",
                            "-t",
                            "15",
                            "-m",
                            "fast",
                            "stop",
                        ],
                        env=environment,
                        capture_output=True,
                        timeout=17,
                    )
                    stopped = result.returncode == 0
                    if not stopped:
                        status = subprocess.run(
                            [str(binary / "pg_ctl"), "-D", str(data), "status"],
                            env=environment,
                            capture_output=True,
                            timeout=2,
                        )
                        stopped = status.returncode == 3  # Documented no-server status.
                except (OSError, subprocess.TimeoutExpired):
                    stopped = False
            if stopped:
                # Only this invocation's fictional temporary cluster, never project/runtime data.
                shutil.rmtree(base)
            else:
                print(f"fixture_shutdown_failed_preserved:{base}", flush=True)
                raise RuntimeError("fixture_postgres_shutdown_failed")
        finally:
            signal.signal(signal.SIGTERM, previous)
