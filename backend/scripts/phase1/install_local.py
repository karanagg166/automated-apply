"""Opt-in reversible per-user macOS installation. No changes to power settings."""
import argparse
import json
import os
import plistlib
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
NAME = "com.automated_apply.agent"
LABEL = "com.automated-apply.telegram"


def private_write(path, content):
    if path.exists():
        raise SystemExit("existing_installation_preserved:" + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as file:
        os.chmod(path, 0o600)
        file.write(content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["native-plan", "native-install", "native-uninstall", "launchd-plan", "launchd-install", "launchd-uninstall", "agy-profile-plan", "agy-profile-install", "agy-profile-uninstall"])
    parser.add_argument("--env-file")
    parser.add_argument("--extension-id")
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise SystemExit("macos_only")
    home = Path.home()
    if args.action.startswith("agy-profile"):
        from backend.app.ai.providers.agy import AGENT, answer_workspace
        profile = home / ".gemini/config/agents/automated-apply-answer.md"
        workspace = answer_workspace()
        print(json.dumps({"profile": str(profile), "workspace": str(workspace), "tools": [], "subagent": False}))
        if args.action == "agy-profile-install":
            if profile.exists():
                if profile.is_symlink() or profile.read_text() != AGENT:
                    raise SystemExit("existing_profile_preserved")
            else:
                private_write(profile, AGENT)
            if workspace.exists() and (workspace.is_symlink() or workspace.stat().st_mode & 0o077):
                raise SystemExit("private_dedicated_workspace_required")
            workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
            template = workspace / ".agents/agents/automated-apply-answer.md"
            if template.exists():
                if template.is_symlink() or template.read_text() != AGENT:
                    raise SystemExit("existing_workspace_profile_preserved")
            else:
                private_write(template, AGENT)
        elif args.action == "agy-profile-uninstall" and profile.exists():
            if profile.is_symlink() or profile.read_text() != AGENT:
                raise SystemExit("existing_profile_preserved")
            profile.unlink()
        return
    support = home / "Library/Application Support/Automated Apply"
    manifest = home / "Library/Application Support/Google/Chrome/NativeMessagingHosts" / (NAME + ".json")
    wrapper = support / "native-host"
    plist_path = home / "Library/LaunchAgents" / (LABEL + ".plist")
    if args.action.endswith("uninstall"):
        paths = [manifest, wrapper] if args.action.startswith("native") else [plist_path]
        if args.action.startswith("launchd"):
            subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], check=False, capture_output=True)
        for path in paths:
            if path.exists():
                # Never remove an unrelated file at our target path.
                if "automated-apply" not in path.read_text().lower() and NAME not in path.read_text():
                    raise SystemExit("installation_ownership_unverified")
                path.unlink()
        print("uninstalled; private configuration and logs preserved")
        return
    env = Path(args.env_file or "").expanduser().resolve()
    if not env.is_file() or env.is_symlink() or env.stat().st_mode & 0o077:
        raise SystemExit("mode_0600_private_env_file_required")
    if args.action.startswith("native"):
        if not re.fullmatch(r"[a-p]{32}", args.extension_id or ""):
            raise SystemExit("exact_extension_id_required")
        from backend.app.operations.configuration import load_settings
        settings = load_settings(str(env))
        if settings.CHROME_EXTENSION_ID != args.extension_id or not settings.CHROME_NATIVE_MESSAGING_ENABLED:
            raise SystemExit("extension_configuration_mismatch")
        document = {"name": NAME, "description": "Automated Apply local preview bridge", "path": str(wrapper),
            "type": "stdio", "allowed_origins": [f"chrome-extension://{args.extension_id}/"]}
        print(json.dumps(document, indent=2))
        if args.action.endswith("install"):
            script = "#!/bin/sh\n# automated-apply native messaging wrapper\ncd " + shlex.quote(str(ROOT)) + " || exit 1\nexec " + shlex.quote(sys.executable) + " -m backend.app.local_agent.native_host " + shlex.quote(str(env)) + ' "$@"\n'
            # Check all targets first, then write only owned new files.
            if wrapper.exists() or manifest.exists():
                raise SystemExit("existing_native_installation_preserved")
            private_write(wrapper, script)
            os.chmod(wrapper, 0o700)
            private_write(manifest, json.dumps(document, indent=2))
    else:
        log_dir = home / "Library/Logs/Automated Apply"
        document = {"Label": LABEL, "ProgramArguments": [sys.executable, str(ROOT / "backend/scripts/phase1/local_service.py"), "telegram", "--env-file", str(env)],
            "WorkingDirectory": str(ROOT), "RunAtLoad": True, "KeepAlive": {"SuccessfulExit": False},
            "ThrottleInterval": 30, "ProcessType": "Background", "ExitTimeOut": 45,
            "StandardOutPath": str(log_dir / "telegram.out.log"), "StandardErrorPath": str(log_dir / "telegram.err.log"),
            "EnvironmentVariables": {"PYTHONPATH": str(ROOT)}, "Umask": 0o077}
        print(plistlib.dumps(document).decode())
        if args.action.endswith("install"):
            log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            private_write(plist_path, plistlib.dumps(document).decode())
            subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(plist_path)], check=True)


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
