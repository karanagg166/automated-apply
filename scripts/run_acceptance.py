"""Sequential local acceptance; never deploys, migrates production, sends or submits."""

import argparse
import fcntl
import json
import os
import signal
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = (
    "uv",
    "run",
    "--no-project",
    "--python",
    str(ROOT / ".venv/bin/python"),
    "python",
)
STAGES = (
    ("policy-drift", (*PYTHON, "scripts/sync_http_security.py", "--check")),
    (
        "native-field-order",
        (*PYTHON, "-m", "rust.scripts.export_native_field_order", "--check"),
    ),
    (
        "execution-contracts",
        (*PYTHON, "-m", "rust.scripts.export_execution_contracts", "--check"),
    ),
    (
        "gmail-contracts",
        (*PYTHON, "-m", "rust.scripts.export_gmail_contracts", "--check"),
    ),
    (
        "contact-contracts",
        (*PYTHON, "-m", "rust.scripts.export_contact_contracts", "--check"),
    ),
    ("rust-format", ("cargo", "fmt", "--all", "--", "--check")),
    ("rust-tests", ("cargo", "test", "--locked", "--workspace")),
    ("rust-postgres", (*PYTHON, "-m", "rust.scripts.run_postgres_tests")),
    (
        "rust-clippy",
        (
            "cargo",
            "clippy",
            "--locked",
            "--workspace",
            "--all-targets",
            "--",
            "-D",
            "warnings",
        ),
    ),
    ("backend", (*PYTHON, "scripts/run_fixture_stage.py", "backend")),
    ("frontend-tests", ("pnpm", "-C", "frontend", "test")),
    ("frontend-types", ("pnpm", "-C", "frontend", "typecheck")),
    ("frontend-format", ("pnpm", "-C", "frontend", "format:check")),
    ("frontend-build", ("pnpm", "-C", "frontend", "build")),
    ("extension-tests", ("pnpm", "-C", "extension", "test")),
    ("extension-brave", ("pnpm", "-C", "extension", "build", "--browser=brave")),
    ("extension-edge", ("pnpm", "-C", "extension", "build", "--browser=edge")),
    ("extension-brave-final", ("pnpm", "-C", "extension", "build", "--browser=brave")),
    ("frontend-e2e", (*PYTHON, "scripts/run_fixture_stage.py", "frontend-ui")),
    (
        "frontend-browser-e2e",
        (*PYTHON, "scripts/run_fixture_stage.py", "frontend-browser"),
    ),
    (
        "frontend-extension-e2e",
        (*PYTHON, "scripts/run_fixture_stage.py", "frontend-extension"),
    ),
    (
        "frontend-naukri-e2e",
        (*PYTHON, "scripts/run_fixture_stage.py", "frontend-naukri"),
    ),
    (
        "extension-browser-e2e",
        (*PYTHON, "scripts/run_fixture_stage.py", "extension-browser"),
    ),
    (
        "extension-stack-e2e",
        (*PYTHON, "scripts/run_fixture_stage.py", "extension-stack"),
    ),
    (
        "backend-browser-e2e",
        (*PYTHON, "scripts/run_fixture_stage.py", "backend-browser"),
    ),
    ("browser-guards", ("node", "--test", "tests/brave_setup_policy.test.mjs")),
    ("tooling", (*PYTHON, "-m", "pytest", "tests", "-q")),
    ("diff", ("git", "diff", "--check")),
)


def process_inventory():
    result = subprocess.run(
        ["ps", "-axo", "pid=,ppid=,lstart="],
        capture_output=True,
        text=True,
        check=True,
        timeout=2,
    )
    rows = {}
    for line in result.stdout.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            rows[int(parts[0])] = (int(parts[1]), parts[2])
    return rows


def owned_descendants(root, inventory):
    selected = {root}
    while True:
        children = {pid for pid, (parent, _) in inventory.items() if parent in selected}
        added = children - selected
        if not added:
            return {pid: inventory[pid][1] for pid in selected - {root}}
        selected.update(added)


def signal_owned(owned, sig, inventory):
    for pid, stamp in owned.items():
        # Do not target a subsequently reused PID, ancestors or unrelated browsers.
        if pid in inventory and inventory[pid][1] == stamp:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass


def bounded_run(command, *, cwd, stdout, stderr, check, timeout):
    # Snapshot descendants before termination; Playwright may use detached groups.
    with subprocess.Popen(
        command, cwd=cwd, stdout=stdout, stderr=stderr, start_new_session=True
    ) as child:
        try:
            return subprocess.CompletedProcess(command, child.wait(timeout=timeout))
        except subprocess.TimeoutExpired:
            try:
                inventory = process_inventory()
                owned = owned_descendants(child.pid, inventory)
            except (OSError, subprocess.SubprocessError):
                owned = {}
            for sig in (signal.SIGTERM, signal.SIGKILL):
                if owned:
                    try:
                        signal_owned(owned, sig, process_inventory())
                    except (OSError, subprocess.SubprocessError):
                        pass
                try:
                    os.killpg(child.pid, sig)
                except ProcessLookupError:
                    pass
                if sig == signal.SIGTERM:
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        child.poll()
                        try:
                            active = process_inventory()
                        except (OSError, subprocess.SubprocessError):
                            break
                        if child.returncode is not None and not any(
                            pid in active and active[pid][1] == stamp
                            for pid, stamp in owned.items()
                        ):
                            break
                        time.sleep(0.05)
            child.wait()
            raise


def coordinated_run(command, **kwargs):
    # The historical complete-stack fixture takes this same advisory lock itself.
    if command[-2:] == ["scripts/run_fixture_stage.py", "extension-stack"]:
        return bounded_run(command, **kwargs)
    with open("/tmp/automated-apply-heavy-tests.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise OSError("local_heavy_test_lock_busy") from None
        return bounded_run(command, **kwargs)


def run_stages(stages, output, invoke=bounded_run):
    """Stop at first failure and distinguish unexecuted stages from passing ones."""
    rows = []
    failed = False
    for name, command in stages:
        row = {"name": name, "status": "NOT TESTED"}
        if not failed:
            started = datetime.now(timezone.utc)
            with (output / (name + ".private.log")).open("xb") as log:
                os.chmod(log.name, 0o600)
                try:
                    result = invoke(
                        list(command),
                        cwd=ROOT,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        check=False,
                        timeout=2700,
                    )
                    code = result.returncode
                except subprocess.TimeoutExpired:
                    code = 124
                except OSError:
                    code = 127
            row.update(
                status="PASS" if code == 0 else "FAIL",
                exit_code=code,
                seconds=round(
                    (datetime.now(timezone.utc) - started).total_seconds(), 3
                ),
            )
            failed = code != 0
        rows.append(row)
        report = {
            "scope": "local_fixture_acceptance_not_live_platform_acceptance",
            "stages": rows,
        }
        report["stages"] = rows + [
            {"name": pending, "status": "NOT TESTED"}
            for pending, _ in stages[len(rows) :]
        ]
        path = output / "results.json"
        temporary = output / "results.pending.json"
        temporary.write_text(json.dumps(report, indent=2) + "\n")
        temporary.chmod(0o600)
        temporary.replace(path)
        print(json.dumps(row), flush=True)
    return not failed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--run", action="store_true")
    args = parser.parse_args()
    if args.plan:
        print(
            json.dumps(
                {
                    "stages": [
                        {"name": name, "command": list(command)}
                        for name, command in STAGES
                    ],
                    "live_actions": False,
                },
                indent=2,
            )
        )
        return
    if not (ROOT / ".venv/bin/python").is_file():
        raise SystemExit("canonical_uv_environment_required")
    label = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex
    )
    output = ROOT / ".local/acceptance" / label
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    print(json.dumps({"private_run": label, "live_actions": False}), flush=True)
    # Match existing browser/PostgreSQL harness coordination. Never wait silently
    # behind another owner's heavy run or start a competing fixture cluster.
    with open("/tmp/automated-apply-combined-acceptance.lock", "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("local_heavy_test_lock_busy") from None
        if not run_stages(STAGES, output, invoke=coordinated_run):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
