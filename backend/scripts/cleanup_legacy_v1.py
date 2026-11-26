"""Staged, guarded cleanup of the legacy v1 (Rust / extension / native host) footprint.

    backend/venv/bin/python -m backend.scripts.cleanup_legacy_v1            # --plan (default, read-only)
    backend/venv/bin/python -m backend.scripts.cleanup_legacy_v1 --plan --json
    backend/venv/bin/python -m backend.scripts.cleanup_legacy_v1 --execute --group A \
        --i-tagged-backup [--yes]

Three independent opt-in groups:
  A  local disk bloat (untracked): target/, old release folders + recovery dumps under .local/,
     old reports/ dumps;
  B  frozen legacy code (tracked): rust/, extension/, Cargo.*, .cargo/, rust-ci.yml, legacy
     Python packages/scripts and extension-era screenshots;
  C  disabled legacy LaunchAgents + stale native-messaging host manifests.

`--execute` is refused unless `--i-tagged-backup` is passed AND a local git tag
`archive/pre-v2-cleanup-*` resolves to a commit. Extra refusals: group A while the legacy
Rust/frontend agents (which run from .local releases) are loaded; group B while any kept
file still imports a group-B module, or when the tag does not contain the path.
Never targeted (checked on the resolved path of every target): ~/Library/Application
Support/automated-apply/ (Brave profile, receipts), phase1.private.env, frontend.private.env,
plist-backups/, reports/v2-migration/ and .git/. Note that
~/Library/Application Support/Automated Apply is a symlink into .local/runtime-support/.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TAG_PATTERN = "archive/pre-v2-cleanup-*"
CONFIRM_WORD = "DELETE"
LEGACY_RUNNING_LABELS = ("com.automated-apply.rust", "com.automated-apply.frontend")

GROUP_A_REPO = ("target", ".local/runtime-support/releases", ".local/runtime-support/release-candidates")
GROUP_A_GLOBS = (".local/runtime-recovery-*", ".local/interrupted-release-target.*")
REPORTS_KEEP = frozenset({"v2-migration", "phase7-openapi.json"})

GROUP_B_PATHS = ("rust", "extension", "Cargo.toml", "Cargo.lock", ".cargo", ".github/workflows/rust-ci.yml",
                 "backend/app/mcp_server.py", "backend/app/agent", "backend/app/browser", "backend/app/execution",
                 "backend/scripts/phase1", "backend/scripts/browser_mock_demo.py")
GROUP_B_GLOBS = ("backend/scripts/verify_phase*.py",)
GROUP_B_SCREENSHOT_DIRS = ("docs/acceptance", "docs/phase52/screenshots", "docs/phase53/screenshots")

GROUP_C_AGENT_LABELS = ("api", "execution", "telegram", "rust", "frontend")
NATIVE_HOST_DIRS = ("Library/Application Support/BraveSoftware/Brave-Browser/NativeMessagingHosts",
                    "Library/Application Support/Google/Chrome/NativeMessagingHosts",
                    "Library/Application Support/Chromium/NativeMessagingHosts",
                    "Library/Application Support/Microsoft Edge/NativeMessagingHosts")
NATIVE_HOST_NAMES = ("com.automated_apply.brave", "com.automated_apply.edge", "com.automated_apply.agent")

Git = Callable[[Sequence[str]], tuple[int, str]]


def git(args: Sequence[str], repo: Path = ROOT) -> tuple[int, str]:
    try:
        done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=120,
                              check=False)
        return done.returncode, done.stdout
    except (OSError, subprocess.SubprocessError):
        return 127, ""


@dataclass
class Target:
    group: str
    path: str
    tracked: bool
    files: int = 0
    bytes: int = 0
    referenced_by: list[str] = field(default_factory=list)
    note: str | None = None


@dataclass
class Group:
    name: str
    title: str
    targets: list[Target]

    def totals(self) -> dict[str, Any]:
        size = sum(t.bytes for t in self.targets)
        return {"group": self.name, "title": self.title, "targets": len(self.targets),
                "files": sum(t.files for t in self.targets), "bytes": size, "human": human(size),
                "referenced_targets": sum(bool(t.referenced_by) for t in self.targets)}


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}" if unit in {"GB", "TB"} else f"{value:.0f} {unit}"
        value /= 1024
    return f"{size} B"


# --- protection ------------------------------------------------------------------------------------
# Folders whose *contents* may be cleaned (only the folder itself / an ancestor is protected).
CONTAINER_ROOTS = ("backend", "frontend")


def protected_paths(repo: Path = ROOT, home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    support = home / "Library/Application Support/Automated Apply"
    items = [home / "Library/Application Support/automated-apply", support / "phase1.private.env",
             support / "frontend.private.env", support / "plist-backups", repo / "backend/frontend.private.env",
             repo / "reports/v2-migration", repo / ".git", repo / "backend", repo / "frontend",
             repo / ".local/runtime-support/phase1.private.env",
             repo / ".local/runtime-support/frontend.private.env"]
    return [Path(os.path.realpath(p)) for p in items]


def is_protected(path: Path, protected: Iterable[Path], repo: Path = ROOT) -> bool:
    """True when deleting `path` would delete, or reach inside, a protected location."""
    resolved = Path(os.path.realpath(path))
    containers = {Path(os.path.realpath(repo / name)) for name in CONTAINER_ROOTS}
    for item in protected:
        if resolved == item or resolved in item.parents:
            return True  # the protected path itself, or an ancestor that contains it
        if item in resolved.parents and item not in containers:
            return True  # inside a protected tree
    return False


def assert_deletable(path: Path, protected: Iterable[Path], repo: Path = ROOT) -> None:
    if is_protected(path, protected, repo):
        raise PermissionError(f"refusing protected path: {path}")


# --- measurement -----------------------------------------------------------------------------------
def measure(path: Path) -> tuple[int, int]:
    """(files, bytes on disk) without following symlinks."""
    try:
        info = path.lstat()
    except OSError:
        return 0, 0
    if not path.is_dir() or path.is_symlink():
        return 1, info.st_blocks * 512
    files, size = 0, 0
    for base, dirs, names in os.walk(path, followlinks=False):
        for name in names + [d for d in dirs if os.path.islink(os.path.join(base, d))]:
            try:
                files += 1
                size += os.lstat(os.path.join(base, name)).st_blocks * 512
            except OSError:
                continue
    return files, size


def tracked_files(paths: Sequence[str], run_git: Git) -> list[str]:
    code, out = run_git(["ls-files", "-z", "--", *paths])
    return [p for p in out.split("\0") if p] if code == 0 else []


# --- groups ----------------------------------------------------------------------------------------
def group_a(repo: Path, protected: list[Path]) -> Group:
    targets = []
    candidates = [repo / p for p in GROUP_A_REPO]
    for pattern in GROUP_A_GLOBS:
        candidates.extend(sorted(repo.glob(pattern)))
    reports = repo / "reports"
    if reports.is_dir():
        candidates.extend(sorted(p for p in reports.iterdir() if p.name not in REPORTS_KEEP))
    for path in candidates:
        if not (path.exists() or path.is_symlink()) or is_protected(path, protected, repo):
            continue
        files, size = measure(path)
        targets.append(Target("A", str(path.relative_to(repo)), False, files, size))
    return Group("A", "Local disk bloat (untracked)", targets)


def module_pattern(relative: str) -> str | None:
    """Extended regex matching imports of a legacy Python module/package."""
    path = Path(relative)
    if relative.startswith("backend/app/") and (path.suffix == ".py" or "." not in path.name):
        dotted = ".".join(path.with_suffix("").parts)
        return dotted.replace(".", "[./]") + "([^_a-zA-Z0-9]|$)"
    if relative.startswith("backend/scripts/") and path.suffix == ".py":
        return "[^a-zA-Z0-9_]" + path.stem + "([^_a-zA-Z0-9]|$)"
    if relative == "backend/scripts/phase1":
        return "backend[./]scripts[./]phase1[./]"
    return None


def references(relative: str, excluded: Sequence[str], run_git: Git) -> list[str]:
    pattern = module_pattern(relative)
    if pattern is None:
        return []
    specs = ["--", "*.py", "*.yml", "*.yaml", "*.toml", "*.ini", "Dockerfile", "*.json",
             *[f":(exclude){p}" for p in excluded]]
    code, out = run_git(["grep", "-l", "-E", pattern, *specs])
    return sorted(set(out.split())) if code == 0 else []


def group_b(repo: Path, run_git: Git, *, check_references: bool = True) -> Group:
    paths = list(GROUP_B_PATHS)
    for pattern in GROUP_B_GLOBS:
        paths.extend(str(p.relative_to(repo)) for p in sorted(repo.glob(pattern)))
    shots = [p for p in tracked_files(GROUP_B_SCREENSHOT_DIRS, run_git) if p.endswith((".png", ".jpg", ".jpeg"))]
    targets = []
    for relative in paths + shots:
        tracked = tracked_files([relative], run_git)
        if not tracked:
            continue
        size = sum((repo / f).lstat().st_blocks * 512 for f in tracked if (repo / f).exists())
        target = Target("B", relative, True, len(tracked), size)
        if check_references:
            target.referenced_by = references(relative, paths + shots, run_git)[:20]
        targets.append(target)
    return Group("B", "Frozen legacy code (tracked)", targets)


def group_c(home: Path) -> Group:
    targets = []
    agents = home / "Library/LaunchAgents"
    for name in GROUP_C_AGENT_LABELS:
        for path in sorted(agents.glob(f"com.automated-apply.{name}.plist.disabled*")):
            files, size = measure(path)
            targets.append(Target("C", str(path), False, files, size))
    for folder in NATIVE_HOST_DIRS:
        base = home / folder
        for host in NATIVE_HOST_NAMES:
            for path in sorted(base.glob(f"{host}.json*")):
                files, size = measure(path)
                targets.append(Target("C", str(path), False, files, size, note="native messaging manifest"))
    return Group("C", "Disabled legacy LaunchAgents + native host manifests", targets)


def build_plan(repo: Path = ROOT, home: Path | None = None, run_git: Git | None = None,
               groups: Sequence[str] = ("A", "B", "C")) -> dict[str, Any]:
    home = home or Path.home()
    runner = run_git or (lambda args: git(args, repo))
    protected = protected_paths(repo, home)
    built = []
    if "A" in groups:
        built.append(group_a(repo, protected))
    if "B" in groups:
        built.append(group_b(repo, runner))
    if "C" in groups:
        built.append(group_c(home))
    total = sum(g.totals()["bytes"] for g in built)
    return {"mode": "plan", "deleted": 0, "groups": [g.totals() for g in built],
            "targets": [asdict(t) for g in built for t in g.targets], "total_bytes": total,
            "total_human": human(total), "protected": [str(p) for p in protected]}


# --- execute guard ---------------------------------------------------------------------------------
def verified_backup_tags(run_git: Git) -> list[str]:
    code, out = run_git(["tag", "-l", TAG_PATTERN])
    tags = [t.strip() for t in out.splitlines() if fnmatch.fnmatchcase(t.strip(), TAG_PATTERN)] if code == 0 else []
    return [t for t in tags if run_git(["rev-parse", "--verify", "--quiet", f"{t}^{{commit}}"])[0] == 0]


def legacy_agents_loaded(runner: Callable[[Sequence[str]], str] | None = None) -> list[str]:
    def default(command: Sequence[str]) -> str:
        try:
            return subprocess.run(list(command), capture_output=True, text=True, timeout=10, check=False).stdout
        except (OSError, subprocess.SubprocessError):
            return ""

    text = (runner or default)(["/bin/launchctl", "list"])
    labels = {line.split("\t")[-1].strip() for line in text.splitlines()}
    return [label for label in LEGACY_RUNNING_LABELS if label in labels]


def execute_refusals(groups: Sequence[str], *, tagged_flag: bool, run_git: Git,
                     loaded_legacy: Sequence[str], plan: dict[str, Any]) -> list[str]:
    reasons = []
    if not groups:
        reasons.append("choose at least one --group A|B|C")
    if not tagged_flag:
        reasons.append("--i-tagged-backup is required")
    tags = verified_backup_tags(run_git)
    if not tags:
        reasons.append(f"no local git tag matching {TAG_PATTERN} resolves to a commit "
                       "(git tag archive/pre-v2-cleanup-YYYYMMDD after committing)")
    if "A" in groups and loaded_legacy:
        reasons.append(f"group A: legacy agents still loaded ({', '.join(loaded_legacy)}); they run from "
                       ".local releases. Run cutover_v2.py apply first.")
    if "B" in groups:
        referenced = [t["path"] for t in plan["targets"] if t["group"] == "B" and t["referenced_by"]]
        if referenced:
            reasons.append(f"group B: {len(referenced)} target(s) still imported by kept files "
                           f"(e.g. {', '.join(referenced[:3])})")
        if tags:
            missing = [t["path"] for t in plan["targets"] if t["group"] == "B"
                       and run_git(["cat-file", "-e", f"{tags[-1]}:{t['path']}"])[0] != 0]
            if missing:
                reasons.append(f"group B: backup tag {tags[-1]} lacks {len(missing)} path(s), "
                               f"e.g. {missing[0]}")
    return reasons


def delete_targets(plan: dict[str, Any], groups: Sequence[str], repo: Path, protected: list[Path]) -> dict[str, Any]:
    deleted, freed = [], 0
    for target in plan["targets"]:
        if target["group"] not in groups:
            continue
        path = Path(target["path"]) if target["group"] == "C" else repo / target["path"]
        assert_deletable(path, protected, repo)
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()
        deleted.append(target["path"])
        freed += int(target["bytes"])
    return {"deleted": len(deleted), "freed_bytes": freed, "freed_human": human(freed), "paths": deleted}


def render_table(plan: dict[str, Any]) -> str:
    lines = ["Group | Title | Targets | Files | Size | Still referenced", "---|---|---|---|---|---"]
    for g in plan["groups"]:
        lines.append(f"{g['group']} | {g['title']} | {g['targets']} | {g['files']} | {g['human']} | "
                     f"{g['referenced_targets']}")
    lines.append(f"**Total** | | | | **{plan['total_human']}** |")
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, repo: Path = ROOT, home: Path | None = None,
         run_git: Git | None = None, launchctl: Callable[[Sequence[str]], str] | None = None,
         prompt: Callable[[str], str] = input) -> int:
    parser = argparse.ArgumentParser(prog="cleanup_legacy_v1", description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="read-only report (default)")
    mode.add_argument("--execute", action="store_true", help="delete the selected groups (guarded)")
    parser.add_argument("--group", action="append", choices=["A", "B", "C"], default=[],
                        help="repeatable; plan defaults to all groups, execute requires an explicit choice")
    parser.add_argument("--i-tagged-backup", action="store_true",
                        help="confirm you created a local archive/pre-v2-cleanup-* tag")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--yes", action="store_true", help="skip the typed confirmation")
    args = parser.parse_args(argv)
    home = home or Path.home()
    runner = run_git or (lambda a: git(a, repo))
    groups = sorted(set(args.group))
    if not args.execute:
        plan = build_plan(repo, home, runner, groups or ("A", "B", "C"))
        print(json.dumps(plan, indent=2) if args.json else render_table(plan))
        return 0
    plan = build_plan(repo, home, runner, groups or ())
    refusals = execute_refusals(groups, tagged_flag=args.i_tagged_backup, run_git=runner,
                                loaded_legacy=legacy_agents_loaded(launchctl), plan=plan)
    if refusals:
        print(json.dumps({"mode": "execute", "refused": True, "reasons": refusals, "deleted": 0}, indent=2))
        return 2
    if not args.yes and prompt(f"Delete groups {groups} ({plan['total_human']})? Type {CONFIRM_WORD}: ").strip() \
            != CONFIRM_WORD:
        print(json.dumps({"mode": "execute", "refused": True, "reasons": ["not_confirmed"], "deleted": 0}))
        return 1
    result = delete_targets(plan, groups, repo, protected_paths(repo, home))
    print(json.dumps({"mode": "execute", "groups": groups, **result}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
