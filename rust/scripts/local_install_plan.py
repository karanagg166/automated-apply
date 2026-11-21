"""Prepare private macOS cutover definitions for a verified Rust release."""

import argparse
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from rust.scripts.local_release import (
    RELEASES,
    ROOT,
    STABLE_EXTENSION_ID,
    ReleaseError,
    acceptance_candidate,
    verify_staged,
)
from rust.scripts.local_rollback import BACKUPS, path_stamp, verify

PLANS = ROOT / ".local/runtime-support/installation-plans"
LOGS = Path.home() / "Library/Logs/Automated Apply"
NATIVE_CONFIG = "automated-apply-native.private.env"


def prepare_private_log(logs_dir, filename):
    try:
        logs = Path(logs_dir)
        if not logs.is_absolute() or logs.is_symlink():
            raise ReleaseError("private_log_path_unavailable")
        if logs.exists():
            info = logs.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
                raise ReleaseError("private_log_path_unavailable")
        else:
            logs.mkdir(mode=0o700, parents=True, exist_ok=True)
        logs.chmod(0o700)
        path = logs / filename
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK
        fd = os.open(path, flags, 0o600)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_nlink != 1
            ):
                raise ReleaseError("private_log_path_unavailable")
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        return path
    except ReleaseError:
        raise
    except OSError:
        raise ReleaseError("private_log_path_unavailable") from None


def launch_definition(label, arguments, release, logs_dir):
    return {
        "Label": f"com.automated-apply.{label}",
        "ProgramArguments": [str(argument) for argument in arguments],
        "WorkingDirectory": str(release),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 30,
        "ProcessType": "Background",
        "ExitTimeOut": 45,
        "StandardOutPath": str(logs_dir / f"{label}.out.log"),
        "StandardErrorPath": str(logs_dir / f"{label}.err.log"),
        "Umask": 0o077,
    }


def native_manifest(browser, release):
    return {
        "name": f"com.automated_apply.{browser}",
        "description": "Automated Apply local browser bridge",
        "path": str(release / "bin/automated-apply-native"),
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{STABLE_EXTENSION_ID}/"],
    }


def local_check(arguments):
    result = subprocess.run(
        [str(argument) for argument in arguments],
        env={"PATH": os.defpath},
        capture_output=True,
        check=False,
        timeout=20,
    )
    if result.returncode != 0:
        # Preserve the fixed error code without exposing any configuration values.
        token = result.stderr.decode("ascii", "ignore").strip()
        if re.fullmatch(r"[a-z][a-z_0-9]{2,90}", token):
            raise ReleaseError(token)
        raise ReleaseError("local_cutover_configuration_check_failed")
    return result.stdout


def render(
    release,
    plan,
    settings,
    node,
    port,
    logs=None,
    *,
    allow_telegram=False,
    launch_agents_dir=None,
):
    runtime, frontend = settings
    logs_dir = Path(logs) if logs is not None else LOGS
    daemon = release / "bin/automated-apply-agents"
    frontend_args = (
        node,
        release / "frontend/run-local-rust.mjs",
        "--frontend-config",
        frontend,
        "--runtime-config",
        runtime,
        "--port",
        port,
    )
    local_check((*frontend_args, "--check-config"))
    native_args = (
        daemon,
        "prepare-native-config",
        "--config",
        runtime,
        "--output-directory",
        plan,
        *(("--allow-telegram",) if allow_telegram else ()),
    )
    result = json.loads(local_check(native_args))
    if (
        result.get("extension_id") != STABLE_EXTENSION_ID
        or result.get("fixture") is not False
        or not isinstance(result.get("telegram_enabled"), bool)
        or (not allow_telegram and result["telegram_enabled"])
    ):
        raise ReleaseError("production_native_configuration_required")
    telegram_enabled = result["telegram_enabled"]
    if telegram_enabled:
        agents_dir = (
            Path(launch_agents_dir)
            if launch_agents_dir is not None
            else Path.home() / "Library/LaunchAgents"
        )
        legacy_telegram = agents_dir / "com.automated-apply.telegram.plist"
        if legacy_telegram.exists() or legacy_telegram.is_symlink():
            raise ReleaseError("legacy_telegram_service_active")
    for label, arguments in (
        ("rust", (daemon, "serve", "--config", runtime)),
        ("frontend", frontend_args),
    ):
        prepare_private_log(logs_dir, f"{label}.out.log")
        prepare_private_log(logs_dir, f"{label}.err.log")
        data = launch_definition(label, arguments, release, logs_dir)
        with (plan / f"{data['Label']}.plist").open("xb") as file:
            plistlib.dump(data, file)
    for browser in ("brave", "edge"):
        value = native_manifest(browser, release)
        write_json(plan / f"{value['name']}.json", value)
    write_json(
        plan / "mcp.local.json",
        {
            "mcpServers": {
                "automated-apply": {
                    "command": str(release / "bin/automated-apply-tools"),
                    "args": ["--config", str(runtime)],
                }
            }
        },
    )
    return telegram_enabled


def write_json(path, value):
    with path.open("x") as file:
        json.dump(value, file, indent=2)
        file.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acceptance-run", required=True)
    parser.add_argument("--rollback", required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--frontend-config", type=Path, required=True)
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--allow-telegram", action="store_true", default=False)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        tested = acceptance_candidate(args.acceptance_run)
        release = RELEASES / f"rust-{tested['commit']}"
        verify_staged(release, tested)
        if not re.fullmatch(r"rust-preinstall-[a-z0-9_]+", args.rollback):
            raise ReleaseError("exact_rollback_snapshot_required")
        backup = BACKUPS / args.rollback
        report = verify(backup, compare_installed=True)
        if report["missing_references"] != 0:
            raise ReleaseError("rollback_inputs_incomplete")
        settings = (args.runtime_config, args.frontend_config)
        if any(not path.is_absolute() or path.is_symlink() for path in settings):
            raise ReleaseError("explicit_private_configuration_required")
        expected = {str(path): path_stamp(path) for path in settings}
        node = Path(shutil.which("node") or "").resolve(strict=True)
        if not node.is_file() or not os.access(node, os.X_OK):
            raise ReleaseError("node_executable_unavailable")
        PLANS.mkdir(exist_ok=True, parents=True)
        plan = Path(tempfile.mkdtemp(prefix="rust-plan-", dir=PLANS))
        telegram_enabled = bool(
            render(
                release,
                plan,
                settings,
                node,
                args.port,
                logs=LOGS,
                allow_telegram=args.allow_telegram,
            )
        )
        if {str(path): path_stamp(path) for path in settings} != expected:
            raise ReleaseError("cutover_configuration_changed_during_planning")
        native = plan / NATIVE_CONFIG
        write_json(
            plan / "plan.json",
            {
                "commit": tested["commit"],
                "acceptance_run": args.acceptance_run,
                "rollback": args.rollback,
                "logs_directory": str(LOGS),
                "configuration": expected,
                "native_configuration": {
                    "staged": path_stamp(native),
                    "candidate_destination": str(release / "bin" / NATIVE_CONFIG),
                },
                "telegram_enabled": telegram_enabled,
                "activates_services": False,
            },
        )
        print(
            json.dumps(
                {"plan": plan.name, "commit": tested["commit"], "activated": False}
            )
        )
    except ReleaseError as error:
        raise SystemExit(str(error)) from None
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        RuntimeError,
        subprocess.SubprocessError,
    ):
        raise SystemExit("local_cutover_plan_unavailable") from None


if __name__ == "__main__":
    main()
