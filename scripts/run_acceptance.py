"""Sequential local acceptance; never deploys, migrates production, sends or submits."""
import argparse
import json
import os
import signal
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ("uv", "run", "--no-project", "--python", str(ROOT / ".venv/bin/python"), "python")
STAGES = (
    ("policy-drift", (*PYTHON, "scripts/sync_http_security.py", "--check")),
    ("rust-format", ("cargo", "fmt", "--all", "--", "--check")),
    ("rust-tests", ("cargo", "test", "--locked", "--workspace")),
    ("rust-postgres", (*PYTHON, "-m", "rust.scripts.run_postgres_tests")),
    ("rust-clippy", ("cargo", "clippy", "--locked", "--workspace", "--all-targets", "--", "-D", "warnings")),
    ("backend", (*PYTHON, "-m", "pytest", "backend/tests", "-q", "--durations=12")),
    ("frontend-tests", ("pnpm", "-C", "frontend", "test")),
    ("frontend-types", ("pnpm", "-C", "frontend", "typecheck")),
    ("frontend-format", ("pnpm", "-C", "frontend", "format:check")),
    ("frontend-build", ("pnpm", "-C", "frontend", "build")),
    ("extension-tests", ("pnpm", "-C", "extension", "test")),
    ("extension-brave", ("pnpm", "-C", "extension", "build", "--browser=brave")),
    ("extension-edge", ("pnpm", "-C", "extension", "build", "--browser=edge")),
    ("extension-brave-final", ("pnpm", "-C", "extension", "build", "--browser=brave")),
    ("browser-guards", ("node", "--test", "tests/brave_setup_policy.test.mjs")),
    ("continuity", (*PYTHON, "-m", "pytest", "tests/test_project_continuity.py", "-q")),
    ("diff", ("git", "diff", "--check")),
)


def bounded_run(command, *, cwd, stdout, stderr, check, timeout):
    # Own the complete test process group, including uv/cargo/browser descendants.
    with subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=stderr,
                          start_new_session=True) as child:
        try:
            return subprocess.CompletedProcess(command, child.wait(timeout=timeout))
        except subprocess.TimeoutExpired:
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(child.pid, sig)
                except ProcessLookupError:
                    break
                if sig == signal.SIGTERM:
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
            child.wait()
            raise


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
                    result = invoke(list(command), cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=False, timeout=2700)
                    code = result.returncode
                except subprocess.TimeoutExpired:
                    code = 124
                except OSError:
                    code = 127
            row.update(status="PASS" if code == 0 else "FAIL", exit_code=code,
                       seconds=round((datetime.now(timezone.utc) - started).total_seconds(), 3))
            failed = code != 0
        rows.append(row)
        report = {"scope": "local_fixture_acceptance_not_live_platform_acceptance", "stages": rows}
        report["stages"] = rows + [{"name": pending, "status": "NOT TESTED"} for pending, _ in stages[len(rows):]]
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
        print(json.dumps({"stages": [{"name": name, "command": list(command)} for name, command in STAGES], "live_actions": False}, indent=2))
        return
    if not (ROOT / ".venv/bin/python").is_file():
        raise SystemExit("canonical_uv_environment_required")
    label = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex
    output = ROOT / ".local/acceptance" / label
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    print(json.dumps({"private_run": label, "live_actions": False}), flush=True)
    if not run_stages(STAGES, output):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
