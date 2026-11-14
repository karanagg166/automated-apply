"""Start a disposable native PostgreSQL fixture; never use an existing DB or env file."""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def main():
    incremental = os.environ.get("CARGO_INCREMENTAL")
    if incremental is not None and incremental not in {"0", "1"}:
        raise SystemExit("invalid_fixture_incremental_setting")
    binary = Path(os.environ.get("RUST_TEST_POSTGRES_BIN", "/opt/homebrew/opt/postgresql@17/bin"))
    for name in ("initdb", "pg_ctl", "createdb"):
        if not (binary / name).is_file():
            raise SystemExit("native_postgresql17_tools_required")
    # Compile before launching the fixture so compiler contention is not measured as DB time.
    subprocess.run(["cargo", "test", "--locked", "-p", "automated-apply-agents", "--test", "postgres", "--no-run"], cwd=ROOT, check=True)
    base = Path(tempfile.mkdtemp(prefix="rust-agent-fictional-pg-"))
    data = base / "data"
    environment = {"PATH": os.environ.get("PATH", ""), "HOME": str(Path.home()), "LANG": "C", "LC_ALL": "C"}
    if incremental is not None:
        environment["CARGO_INCREMENTAL"] = incremental
    start_attempted = False
    stopped = True
    try:
        with (base / "setup.log").open("wb") as log:
            subprocess.run([str(binary / "initdb"), "-D", str(data), "-U", "rust_agent_fixture", "--no-locale", "-E", "UTF8", "--auth=trust"], env=environment, stdout=log, stderr=log, check=True)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            options = f"-h 127.0.0.1 -p {port} -k {base} -c shared_buffers=16MB -c max_connections=8 -c work_mem=1MB"
            start_attempted = True
            subprocess.run([str(binary / "pg_ctl"), "-D", str(data), "-l", str(base / "postgres.log"), "-w", "-t", "15", "-o", options, "start"], env=environment, stdout=log, stderr=log, check=True)
            stopped = False
            subprocess.run([str(binary / "createdb"), "-h", "127.0.0.1", "-p", str(port), "-U", "rust_agent_fixture", "rust_agent_fixture"], env=environment, stdout=log, stderr=log, check=True)
        test_env = {**environment, "RUST_AGENT_TEST_DATABASE_URL": f"postgresql://rust_agent_fixture@127.0.0.1:{port}/rust_agent_fixture"}
        subprocess.run(["cargo", "test", "--locked", "-p", "automated-apply-agents", "--test", "postgres", "--", "--ignored", "--test-threads=1"], env=test_env, cwd=ROOT, check=True)
    finally:
        if start_attempted:
            result = subprocess.run([str(binary / "pg_ctl"), "-D", str(data), "-w", "-t", "15", "-m", "fast", "stop"], env=environment, capture_output=True)
            stopped = result.returncode == 0
        if stopped:
            # Only this invocation's disposable fictional fixture is retired; no worktree/runtime data.
            shutil.rmtree(base)
        else:
            print(f"fixture_shutdown_failed_preserved:{base}")


if __name__ == "__main__":
    main()
