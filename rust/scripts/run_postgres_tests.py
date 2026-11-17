"""Start a disposable native PostgreSQL fixture; never use an existing DB or env file."""
import argparse
import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filter", help="Run matching Rust test names in the disposable fixture")
    parser.add_argument(
        "--with-browser",
        action="store_true",
        help="Include the headless Brave and native host fixture using the current Brave extension build",
    )
    args = parser.parse_args()
    incremental = os.environ.get("CARGO_INCREMENTAL")
    if incremental is not None and incremental not in {"0", "1"}:
        raise SystemExit("invalid_fixture_incremental_setting")
    binary = Path(os.environ.get("RUST_TEST_POSTGRES_BIN", "/opt/homebrew/opt/postgresql@17/bin"))
    for name in ("initdb", "pg_ctl", "createdb"):
        if not (binary / name).is_file():
            raise SystemExit("native_postgresql17_tools_required")
    # Compile before launching the fixture so compiler contention is not measured as DB time.
    # Match the workspace feature graph so this reuses ordinary workspace test artifacts.
    # Selecting only one package otherwise compiles a second dependency-feature variant.
    subprocess.run(["cargo", "build", "--locked", "--workspace", "--bins"], cwd=ROOT, check=True)
    subprocess.run(["cargo", "test", "--locked", "--workspace", "--test", "postgres", "--no-run"], cwd=ROOT, check=True)
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
        arguments = ["cargo", "test", "--locked", "--workspace", "--test", "postgres"]
        if args.filter:
            arguments.append(args.filter)
        flags = ["--ignored", "--test-threads=1"]
        if not args.with_browser:
            flags.extend(["--skip", "native_brave_extension_fixture"])
        subprocess.run([*arguments, "--", *flags], env=test_env, cwd=ROOT, check=True)
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
