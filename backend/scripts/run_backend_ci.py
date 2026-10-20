"""Bound the full regression process tree and retain fictional CI diagnostics.

Children write to a regular file, so an inherited stdout pipe cannot keep a tee
pipeline open after pytest exits. Never dump environment values or process args.
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


def stop_group(pid, sig):
    try:
        os.killpg(pid, sig)
    except ProcessLookupError:
        pass


def snapshot(directory):
    with (directory / "processes.log").open("a") as output:
        output.write(f"\n{datetime.now(timezone.utc).isoformat()}\n")
        output.flush()
        try:
            subprocess.run(
                ["ps", "-eo", "pid,ppid,pgid,sid,stat,wchan:32,comm"],
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            output.write(f"Process snapshot unavailable: {type(exc).__name__}\n")


def run(directory, seconds, command):
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    cancelled = None

    def cancel(signum, _frame):
        nonlocal cancelled
        cancelled = signum

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, cancel)
    with (directory / "pytest.log").open("wb") as output:
        process = subprocess.Popen(
            command, stdout=output, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            with (directory / "pytest.log").open() as reader:
                next_snapshot = started
                while process.poll() is None:
                    now = time.monotonic()
                    sys.stdout.write(reader.read())
                    sys.stdout.flush()
                    if now >= next_snapshot:
                        snapshot(directory)
                        print(
                            f"CI supervisor: {int(now - started)}s, pytest PID {process.pid}",
                            flush=True,
                        )
                        next_snapshot = now + 30
                    if cancelled or now - started >= seconds:
                        snapshot(directory)
                        stop_group(process.pid, signal.SIGTERM)
                        try:
                            process.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            stop_group(process.pid, signal.SIGKILL)
                            process.wait(timeout=5)
                        result = 128 + cancelled if cancelled else 124
                        break
                    time.sleep(0.25)
                else:
                    result = process.returncode
                sys.stdout.write(reader.read())
        finally:
            # Also reap descendants if pytest exits before its children do.
            stop_group(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
    summary = f"exit_code={result}\nelapsed_seconds={time.monotonic() - started:.2f}\n"
    (directory / "supervisor.txt").write_text(summary)
    print(summary, flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=360)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not args.command:
        parser.error("a command is required")
    sys.exit(run(args.output, args.seconds, args.command))
