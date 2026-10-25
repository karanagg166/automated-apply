"""Isolated official CLI account setup. No SQL, token arguments or global logout."""
import argparse
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

PROJECT = "luvdmwnlwaqgvfwlmlom"
PROFILE = {"name": "automated-apply", "api_url": "https://api.supabase.com",
    "dashboard_url": "https://supabase.com/dashboard", "docs_url": "https://supabase.com/docs",
    "project_host": "supabase.co", "pooler_host": "supabase.com"}


def require_project(projects, confirmation):
    if confirmation != PROJECT:
        raise ValueError("wrong_supabase_project")
    matches = [row for row in projects if isinstance(row, dict) and row.get("id") == PROJECT]
    if len(matches) != 1:
        raise ValueError("target_not_visible_in_cli_account")
    return matches[0]


def prepare_profile(base):
    if base.is_symlink():
        raise ValueError("private_cli_directory_required")
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    if base.stat().st_mode & 0o077:
        raise ValueError("private_cli_directory_required")
    path = base / "automated-apply.json"
    if path.exists():
        if path.is_symlink() or path.stat().st_mode & 0o077 or json.loads(path.read_text()) != PROFILE:
            raise ValueError("existing_profile_preserved_review_required")
    else:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as file:
            json.dump(PROFILE, file)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "login", "check"])
    args = parser.parse_args()
    base = Path.home() / "Library/Application Support/Automated Apply/supabase-cli"
    try:
        profile = prepare_profile(base)
        env = dict(os.environ, SUPABASE_HOME=str(base))
        env.pop("SUPABASE_ACCESS_TOKEN", None)
        common = ["--profile", str(profile), "--agent", "no", "--output-format", "text"]
        if args.action == "login":
            # Run this in the owner's own terminal for the browser verification code.
            raise SystemExit(subprocess.run(["supabase", "login", "--name", "automated-apply-phase1", *common], env=env, check=False).returncode)
        if args.action == "check":
            result = subprocess.run(["supabase", "projects", "list", "--output", "json", *common],
                env=env, capture_output=True, text=True, timeout=30, check=False)
            if result.returncode:
                raise ValueError("cli_account_authorization_required")
            project = require_project(json.loads(result.stdout), PROJECT)
            evidence = {"project_ref": PROJECT, "cli_account_access_verified": True,
                "status": project.get("status"), "region": project.get("region"),
                "postgresql_authenticated": False, "linked": False,
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "evidence_type": "actual_isolated_cli_project_list"}
            output = Path(__file__).resolve().parents[3] / "reports/phase1/supabase-cli.private.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
            with os.fdopen(descriptor, "w") as file:
                json.dump(evidence, file, indent=2)
            output.chmod(0o600)
            print(json.dumps(evidence))
        else:
            print("isolated_profile_prepared_existing_default_preserved")
    except (ValueError, OSError, subprocess.TimeoutExpired):
        # Do not print CLI stderr, credential paths/values or upstream account details.
        print("supabase_cli_setup_incomplete_check_private_configuration_or_finish_browser_login")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
