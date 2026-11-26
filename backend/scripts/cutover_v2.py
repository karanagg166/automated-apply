"""Phase 6B launchd cutover + rollback kit for the 24/7 MacBook Air M1 runtime.

    backend/venv/bin/python -m backend.scripts.cutover_v2 plan            # default, read-only
    backend/venv/bin/python -m backend.scripts.cutover_v2 apply [--skip-preflight-migration] [--yes]
    backend/venv/bin/python -m backend.scripts.cutover_v2 rollback <backup-dir> [--yes]
    backend/venv/bin/python -m backend.scripts.cutover_v2 status

`apply` (owner-triggered only):
  1. snapshots every ~/Library/LaunchAgents/com.automated-apply.* file into
     ~/Library/Application Support/Automated Apply/plist-backups/<UTC ts>/ (+ manifest.json);
  2. `launchctl bootout`s and renames to `.plist.disabled` the legacy
     com.automated-apply.rust (ends Telegram HTTP 409) and old com.automated-apply.frontend;
  3. renders deploy/launchd_v2/*.plist (api-v2, worker-v2 under caffeinate -i, frontend-v2)
     into ~/Library/LaunchAgents and `launchctl bootstrap`s them;
  4. waits for :8000/health and runs `cli health-check`.
No plist contains a secret: services read the 0600 private env files at start.
Unrelated agents (e.g. com.automated-apply.codex-history) are never touched.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "deploy/launchd_v2"
V2_LABELS = ("com.automated-apply.api-v2", "com.automated-apply.worker-v2", "com.automated-apply.frontend-v2")
SERVICE_NAMES = {"com.automated-apply.api-v2": "api-v2", "com.automated-apply.worker-v2": "worker-v2",
                 "com.automated-apply.frontend-v2": "frontend-v2"}
LEGACY_RETIRE = ("com.automated-apply.rust", "com.automated-apply.frontend")
PREFIX = "com.automated-apply."
LEGACY_BACKEND_PORT = "8011"
SECRET_KEYS = ("JOB_AGENT_API_TOKEN", "TELEGRAM_BOT_TOKEN", "DATABASE_URL", "SECRET_KEY", "FRONTEND_SESSION_SECRET",
               "FRONTEND_PASSWORD_HASH", "GMAIL_CLIENT_SECRET", "RESUME_ENCRYPTION_KEY", "OAUTH_ENCRYPTION_KEYS",
               "BROWSER_OWNER_APPROVAL_KEY")
CONFIRM_WORD = "CUTOVER"

Runner = Callable[[Sequence[str]], "Result"]


@dataclass
class Result:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def run(command: Sequence[str]) -> Result:
    try:
        done = subprocess.run(list(command), capture_output=True, text=True, timeout=60, check=False)
        return Result(done.returncode, done.stdout, done.stderr)
    except (OSError, subprocess.SubprocessError) as exc:
        return Result(127, "", type(exc).__name__)


@dataclass
class Paths:
    repo: Path
    home: Path
    python: Path
    node: Path
    uid: int

    @property
    def launch_agents(self) -> Path:
        return self.home / "Library/LaunchAgents"

    @property
    def support_dir(self) -> Path:
        return self.home / "Library/Application Support/Automated Apply"

    @property
    def env_file(self) -> Path:
        """Owner rule (2026-11-26): the single project env file lives in the repository."""
        return self.repo / ".env"

    @property
    def frontend_env_file(self) -> Path:
        return self.repo / "frontend/.env.local"

    @property
    def log_dir(self) -> Path:
        return self.home / "Library/Logs/automated-apply"

    @property
    def backup_root(self) -> Path:
        return self.support_dir / "plist-backups"

    @property
    def profile_dir(self) -> Path:
        raw = os.environ.get("AUTOMATED_APPLY_BRAVE_PROFILE_DIR")
        return Path(raw).expanduser() if raw else self.home / "Library/Application Support/automated-apply/brave"

    def domain(self) -> str:
        return f"gui/{self.uid}"


def default_paths() -> Paths:
    node = shutil.which("node") or "/opt/homebrew/bin/node"
    return Paths(repo=ROOT, home=Path.home(), python=ROOT / "backend/venv/bin/python", node=Path(node),
                 uid=os.getuid())


# --- rendering ----------------------------------------------------------------------------------
def substitutions(paths: Paths) -> dict[str, str]:
    return {"__REPO__": str(paths.repo), "__PYTHON__": str(paths.python), "__NODE__": str(paths.node),
            "__LOG_DIR__": str(paths.log_dir), "__ENV_FILE__": str(paths.env_file),
            "__FRONTEND_ENV_FILE__": str(paths.frontend_env_file)}


def render_plist(label: str, paths: Paths, template_dir: Path = TEMPLATE_DIR) -> bytes:
    text = (template_dir / f"{label}.plist").read_text(encoding="utf-8")
    for key, value in substitutions(paths).items():
        text = text.replace(key, escape(value))
    data = text.encode("utf-8")
    parsed = plistlib.loads(data)  # validates XML + plist structure
    if parsed.get("Label") != label or "__" in json.dumps(parsed.get("ProgramArguments")):
        raise ValueError(f"render_failed:{label}")
    return data


def secret_values(*files: Path) -> list[str]:
    """Values of known secret keys (only used to assert none leaks into a rendered plist)."""
    values = []
    for path in files:
        for key, value in read_env_values(path).items():
            if key in SECRET_KEYS and len(value) >= 8:
                values.append(value)
    return values


def read_env_values(path: Path) -> dict[str, str]:
    try:
        from dotenv import dotenv_values

        return {k: v for k, v in dotenv_values(path).items() if isinstance(v, str)}
    except (OSError, ImportError):
        return {}


def env_keys(path: Path) -> set[str]:
    return set(read_env_values(path))


# --- launchctl inspection -----------------------------------------------------------------------
def loaded_agents(runner: Runner) -> dict[str, dict[str, Any]]:
    from backend.app.browser_v2.health import parse_launchctl_list

    rows = parse_launchctl_list(runner(["/bin/launchctl", "list"]).stdout)
    return {label: row for label, row in rows.items() if label.startswith(PREFIX)}


def agent_files(paths: Paths) -> list[Path]:
    if not paths.launch_agents.is_dir():
        return []
    return sorted(p for p in paths.launch_agents.iterdir() if p.name.startswith(PREFIX) and p.is_file())


# --- prerequisites ------------------------------------------------------------------------------
@dataclass
class Prereq:
    name: str
    ok: bool
    detail: str
    blocking: bool = True


def private_file(path: Path) -> tuple[bool, str]:
    try:
        info = path.stat()
    except OSError:
        return False, f"missing: {path}"
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        return False, f"must be owned by you with mode 0600: {path}"
    return True, str(path)


def migration_applied(paths: Paths, runner: Runner) -> tuple[bool, str]:
    """Read-only: `migrate_v2_core check` reports per-table presence."""
    result = runner([str(paths.python), "-m", "backend.scripts.migrate_v2_core", "check"])
    if result.returncode != 0:
        return False, f"migrate_v2_core check failed (exit {result.returncode})"
    try:
        report = json.loads(result.stdout)
    except ValueError:
        return False, "migrate_v2_core check output unreadable"
    from backend.app.operations.v2_schema import TABLES

    missing = sorted(TABLES - set(report.get("v2_tables_present") or []))
    if not missing:
        return True, f"all {len(TABLES)} v2 tables present"
    return False, f"migration 004 not applied ({len(missing)}/{len(TABLES)} v2 tables missing)"


def frontend_build_state(repo: Path) -> tuple[bool, str, bool]:
    """(present, detail, stale) for frontend/.next standalone production build."""
    build_id = repo / "frontend/.next/BUILD_ID"
    server = repo / "frontend/.next/standalone/server.js"
    if not (build_id.is_file() and server.is_file()):
        return False, "frontend/.next standalone build missing: run pnpm -C frontend build", False
    built = build_id.stat().st_mtime
    newest = max((p.stat().st_mtime for p in (repo / "frontend/src").rglob("*") if p.is_file()), default=0)
    stale = newest > built
    return True, "frontend/.next/standalone present" + (" (older than frontend/src: rebuild)" if stale else ""), stale


def prerequisites(paths: Paths, runner: Runner, *, check_migration: bool = True) -> list[Prereq]:
    items = []
    ok, detail = private_file(paths.env_file)
    items.append(Prereq("project_env", ok, detail))
    if ok:
        missing = sorted({"DATABASE_URL", "JOB_AGENT_API_TOKEN"} - env_keys(paths.env_file))
        items.append(Prereq("project_env_keys", not missing,
                            "DATABASE_URL + JOB_AGENT_API_TOKEN present" if not missing
                            else f"missing keys: {', '.join(missing)}"))
    ok, detail = private_file(paths.frontend_env_file)
    items.append(Prereq("frontend_env", ok, detail))
    present, detail, stale = frontend_build_state(paths.repo)
    items.append(Prereq("frontend_build", present, detail))
    if stale:
        items.append(Prereq("frontend_build_fresh", False, "rebuild: pnpm -C frontend build", blocking=False))
    items.append(Prereq("venv_python", paths.python.exists(), str(paths.python)))
    items.append(Prereq("node", paths.node.exists(), str(paths.node)))
    items.append(Prereq("caffeinate", Path("/usr/bin/caffeinate").exists(), "/usr/bin/caffeinate"))
    profile_ok = (paths.profile_dir / "Default").is_dir()
    items.append(Prereq("brave_profile", profile_ok, str(paths.profile_dir) if profile_ok else
                        f"no logged-in profile at {paths.profile_dir}: run cli login-setup first"))
    if check_migration:
        ok, detail = migration_applied(paths, runner)
        items.append(Prereq("migration_004", ok, detail))
    desktop = paths.home / "Desktop"
    if desktop in paths.repo.parents:
        items.append(Prereq("macos_tcc", False, "repo lives under ~/Desktop: if a service log shows "
                            "'Operation not permitted', allow the venv python + node in System Settings > "
                            "Privacy & Security > Files and Folders (or Full Disk Access)", blocking=False))
    return items


# --- plan -----------------------------------------------------------------------------------------
@dataclass
class Plan:
    loaded: dict[str, Any]
    prerequisites: list[Prereq]
    actions: list[str] = field(default_factory=list)
    untouched: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return all(p.ok for p in self.prerequisites if p.blocking)

    def public(self) -> dict[str, Any]:
        return {"ready": self.ready, "loaded_agents": self.loaded,
                "prerequisites": [asdict(p) for p in self.prerequisites], "actions": self.actions,
                "untouched_agents": self.untouched}


def build_plan(paths: Paths, runner: Runner, *, check_migration: bool = True) -> Plan:
    loaded = loaded_agents(runner)
    plan = Plan(loaded, prerequisites(paths, runner, check_migration=check_migration))
    plan.actions.append(f"snapshot {len(agent_files(paths))} {PREFIX}* file(s) -> {paths.backup_root}/<UTC ts>/")
    for label in LEGACY_RETIRE:
        file = paths.launch_agents / f"{label}.plist"
        if label in loaded:
            plan.actions.append(f"launchctl bootout {paths.domain()}/{label}")
        if file.exists():
            plan.actions.append(f"rename {file.name} -> {disabled_name(file).name}")
    for label in V2_LABELS:
        if label in loaded:
            plan.actions.append(f"launchctl bootout {paths.domain()}/{label} (re-install)")
        plan.actions.append(f"install {paths.launch_agents / (label + '.plist')} + launchctl bootstrap")
    plan.actions.append("wait for http://127.0.0.1:8000/health, then run cli health-check")
    plan.untouched = sorted(label for label in loaded if label not in (*LEGACY_RETIRE, *V2_LABELS))
    return plan


def disabled_name(file: Path, stamp: str | None = None) -> Path:
    target = file.with_name(file.name + ".disabled")
    if not target.exists():
        return target
    return file.with_name(f"{file.name}.disabled-{stamp or utc_stamp()}")


def utc_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


# --- apply / rollback -------------------------------------------------------------------------------
def snapshot(paths: Paths, loaded: dict[str, Any], stamp: str) -> Path:
    folder = paths.backup_root / stamp
    folder.mkdir(parents=True, exist_ok=False, mode=0o700)
    files = agent_files(paths)
    for file in files:
        shutil.copy2(file, folder / file.name)
    manifest = {"created_at": stamp, "loaded_labels": sorted(loaded), "files": [f.name for f in files],
                "renamed": {}, "installed": []}
    write_manifest(folder, manifest)
    return folder


def write_manifest(folder: Path, manifest: dict[str, Any]) -> None:
    path = folder / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def bootout(paths: Paths, label: str, runner: Runner) -> Result:
    return runner(["/bin/launchctl", "bootout", f"{paths.domain()}/{label}"])


def bootstrap(paths: Paths, plist: Path, runner: Runner) -> Result:
    return runner(["/bin/launchctl", "bootstrap", paths.domain(), str(plist)])


def install_v2(paths: Paths, runner: Runner, loaded: dict[str, Any]) -> list[dict[str, Any]]:
    paths.log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    secrets = secret_values(paths.env_file, paths.frontend_env_file)
    outcomes = []
    for label in V2_LABELS:
        data = render_plist(label, paths)
        text = data.decode("utf-8")
        if any(value in text for value in secrets):
            raise RuntimeError(f"refusing: a secret value would be written into {label}.plist")
        if label in loaded:
            bootout(paths, label, runner)
        target = paths.launch_agents / f"{label}.plist"
        target.write_bytes(data)
        os.chmod(target, 0o600)
        result = bootstrap(paths, target, runner)
        outcomes.append({"label": label, "plist": str(target), "bootstrap_exit": result.returncode,
                         "error": result.stderr.strip()[:200] or None})
    return outcomes


def wait_for_api(fetch: Callable[[str], int], timeout: float = 45.0, sleep: Callable[[float], None] = time.sleep,
                 url: str = "http://127.0.0.1:8000/health") -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if 200 <= fetch(url) < 300:
            return True
        sleep(1.5)
    return False


def post_health(paths: Paths, runner: Runner) -> dict[str, Any]:
    result = runner([str(paths.python), "-m", "backend.app.browser_v2.cli", "health-check", "--json"])
    try:
        report = json.loads(result.stdout)
        return {"status": report.get("status"), "counts": report.get("counts"),
                "failing": [c["name"] for c in report.get("checks", []) if c.get("status") == "fail"]}
    except ValueError:
        return {"status": "unknown", "exit": result.returncode}


def apply_cutover(paths: Paths, runner: Runner, *, skip_migration: bool = False,
                  fetch: Callable[[str], int] | None = None, wait: bool = True) -> dict[str, Any]:
    plan = build_plan(paths, runner, check_migration=not skip_migration)
    if not plan.ready:
        return {"applied": False, "reason": "prerequisites_failed", **plan.public()}
    stamp = utc_stamp()
    folder = snapshot(paths, plan.loaded, stamp)
    manifest = json.loads((folder / "manifest.json").read_text())
    retired = []
    for label in LEGACY_RETIRE:
        if label in plan.loaded:
            result = bootout(paths, label, runner)
            retired.append({"label": label, "bootout_exit": result.returncode})
        file = paths.launch_agents / f"{label}.plist"
        if file.exists():
            target = disabled_name(file, stamp)
            file.rename(target)
            manifest["renamed"][file.name] = target.name
    manifest["installed"] = list(V2_LABELS)
    write_manifest(folder, manifest)
    installed = install_v2(paths, runner, plan.loaded)
    report: dict[str, Any] = {"applied": True, "backup_dir": str(folder), "retired": retired,
                              "renamed": manifest["renamed"], "installed": installed,
                              "rollback": f"backend/venv/bin/python -m backend.scripts.cutover_v2 rollback {folder}"}
    if wait:
        from backend.app.browser_v2.health import default_fetch

        report["api_ready"] = wait_for_api(fetch or default_fetch)
        report["health"] = post_health(paths, runner)
    return report


def rollback(paths: Paths, backup_dir: Path, runner: Runner) -> dict[str, Any]:
    backup_dir = backup_dir.expanduser().resolve()
    root = paths.backup_root.resolve()
    if root not in backup_dir.parents or not (backup_dir / "manifest.json").is_file():
        raise ValueError(f"not a cutover backup folder under {paths.backup_root}: {backup_dir}")
    manifest = json.loads((backup_dir / "manifest.json").read_text())
    removed_dir = backup_dir / f"rolled-back-v2-{utc_stamp()}"
    removed_dir.mkdir(mode=0o700)
    steps = []
    for label in V2_LABELS:
        steps.append({"bootout": label, "exit": bootout(paths, label, runner).returncode})
        file = paths.launch_agents / f"{label}.plist"
        if file.exists() and f"{label}.plist" not in manifest["files"]:
            shutil.move(str(file), removed_dir / file.name)  # kept for inspection, not deleted
    for original, renamed in manifest.get("renamed", {}).items():
        disabled = paths.launch_agents / renamed
        if disabled.exists() and not (paths.launch_agents / original).exists():
            disabled.rename(paths.launch_agents / original)
    for name in manifest["files"]:
        source = backup_dir / name
        if source.is_file():
            shutil.copy2(source, paths.launch_agents / name)
    for label in manifest.get("loaded_labels", []):
        if label not in LEGACY_RETIRE:
            continue  # only re-load what apply unloaded; other agents were never touched
        plist = paths.launch_agents / f"{label}.plist"
        if plist.is_file():
            steps.append({"bootstrap": label, "exit": bootstrap(paths, plist, runner).returncode})
    return {"rolled_back": True, "backup_dir": str(backup_dir), "v2_plists_moved_to": str(removed_dir),
            "steps": steps}


def status(paths: Paths, runner: Runner) -> dict[str, Any]:
    from backend.app.browser_v2.health import parse_pmset_assertions

    loaded = loaded_agents(runner)
    services = {}
    for label in V2_LABELS:
        name = SERVICE_NAMES[label]
        logs = {kind: paths.log_dir / f"{name}.{kind}.log" for kind in ("out", "err")}
        row = loaded.get(label)
        services[label] = {"loaded": row is not None, "pid": (row or {}).get("pid"),
                           "last_exit": (row or {}).get("last_exit"),
                           "logs": {k: {"path": str(p), "bytes": p.stat().st_size if p.exists() else None}
                                    for k, p in logs.items()}}
    assertions = parse_pmset_assertions(runner(["/usr/bin/pmset", "-g", "assertions"]).stdout)
    worker_pid = services["com.automated-apply.worker-v2"]["pid"]
    return {"services": services, "legacy_loaded": sorted(set(loaded) & set(LEGACY_RETIRE)),
            "sleep_prevention": {**assertions, "worker_holds_assertion": bool(worker_pid)
                                 and worker_pid in assertions["caffeinate_pids"]}}


def confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    return input(f"{prompt} Type {CONFIRM_WORD} to continue: ").strip() == CONFIRM_WORD


def main(argv: list[str] | None = None, *, paths: Paths | None = None, runner: Runner = run) -> int:
    parser = argparse.ArgumentParser(prog="cutover_v2", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("plan", help="read-only: inspect agents + prerequisites, print actions")
    apply = commands.add_parser("apply", help="snapshot, retire legacy agents, install + bootstrap v2")
    apply.add_argument("--skip-preflight-migration", action="store_true",
                       help="do not require migration 004 (only if you just applied it and check is flaky)")
    apply.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    back = commands.add_parser("rollback", help="unload v2 agents and restore a snapshot")
    back.add_argument("backup_dir")
    back.add_argument("--yes", action="store_true")
    commands.add_parser("status", help="PID, exit status, logs and caffeinate assertion for v2 agents")
    args = parser.parse_args(argv)
    paths = paths or default_paths()
    command = args.command or "plan"
    if command == "plan":
        print(json.dumps(build_plan(paths, runner).public(), indent=2))
        return 0
    if command == "status":
        print(json.dumps(status(paths, runner), indent=2))
        return 0
    if command == "apply":
        if not confirm("This unloads com.automated-apply.rust/frontend and installs the 3 v2 agents.", args.yes):
            print(json.dumps({"applied": False, "reason": "not_confirmed"}))
            return 1
        report = apply_cutover(paths, runner, skip_migration=args.skip_preflight_migration)
        print(json.dumps(report, indent=2))
        return 0 if report.get("applied") else 1
    if not confirm(f"Roll back to {args.backup_dir}?", args.yes):
        print(json.dumps({"rolled_back": False, "reason": "not_confirmed"}))
        return 1
    print(json.dumps(rollback(paths, Path(args.backup_dir), runner), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
