"""Phase 6B: launchd cutover kit, watchdog health-check, selector diagnostics, guarded legacy
cleanup, log rotation and MCP config sync. Fully offline: launchctl/pmset/git are faked and
every filesystem effect happens under tmp_path."""

from __future__ import annotations

import json
import os
import plistlib
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backend.app.browser_v2 import api_launcher, cli, diagnostics, health, logrotate
from backend.app.browser_v2.store import MemoryStore, WorkerState
from backend.app.operations.v2_schema import TABLES
from backend.scripts import cleanup_legacy_v1 as cleanup
from backend.scripts import cutover_v2 as cutover

REPO = Path(__file__).resolve().parents[2]
FAKE_TOKEN = "TEST_FAKE_TOKEN_ONLY_0123456789abcdef0123456789"
FAKE_DB = "TEST_FAKE_DATABASE_URL_ONLY_not_a_real_dsn"

PMSET_ACTIVE = """2026-11-26 06:17:41 +0530
Assertion status system-wide:
   BackgroundTask                 0
   UserIsActive                   1
   PreventUserIdleDisplaySleep    0
   PreventSystemSleep             0
   PreventUserIdleSystemSleep     1
Listed by owning process:
   pid 4242(caffeinate): [0x000ec04f000186f5] 00:03:02 PreventUserIdleSystemSleep named: "caffeinate command-line tool"
\tDetails: caffeinate asserting on behalf of '/repo/backend/venv/bin/python' (pid 4243)
   pid 605(powerd): [0x000ebe53000186c0] 00:11:30 PreventUserIdleSystemSleep named: "Powerd - Prevent sleep while display is on"
No kernel assertions.
"""
PMSET_NONE = """Assertion status system-wide:
   PreventUserIdleSystemSleep     0
Listed by owning process:
No kernel assertions.
"""


def launchctl_text(*rows: tuple[str, str, str]) -> str:
    return "PID\tStatus\tLabel\n" + "".join(f"{pid}\t{status}\t{label}\n" for pid, status, label in rows)


# --- fixtures: a fake $HOME + repo for the cutover kit ------------------------------------------
def private(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.chmod(path, 0o600)
    return path


class FakeLaunchd:
    """Records every launchctl/pmset/python call; `loaded` mirrors `launchctl list`."""

    def __init__(self, loaded: dict[str, int | None], tables=TABLES) -> None:
        self.loaded = dict(loaded)
        self.calls: list[list[str]] = []
        self.tables = sorted(tables)

    def __call__(self, command):
        command = [str(c) for c in command]
        self.calls.append(command)
        if command[:2] == ["/bin/launchctl", "list"]:
            rows = [("-" if pid is None else str(pid), "0", label) for label, pid in self.loaded.items()]
            return cutover.Result(0, launchctl_text(*rows))
        if command[:2] == ["/bin/launchctl", "bootout"]:
            self.loaded.pop(command[2].split("/", 2)[2], None)
            return cutover.Result(0)
        if command[:2] == ["/bin/launchctl", "bootstrap"]:
            label = plistlib.loads(Path(command[3]).read_bytes())["Label"]
            self.loaded[label] = 999
            return cutover.Result(0)
        if command[:2] == ["/usr/bin/pmset", "-g"]:
            return cutover.Result(0, PMSET_NONE)
        if "backend.scripts.migrate_v2_core" in command:
            return cutover.Result(0, json.dumps({"v2_tables_present": self.tables, "counts": {}}))
        if "health-check" in command:
            return cutover.Result(0, json.dumps({"status": "ok", "counts": {"ok": 1}, "checks": []}))
        return cutover.Result(0)

    def commands(self, verb: str) -> list[str]:
        return [c[-1] for c in self.calls if c[:2] == ["/bin/launchctl", verb]]


@pytest.fixture
def world(tmp_path, monkeypatch):
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    support = home / "Library/Application Support/Automated Apply"
    private(support / "phase1.private.env", f'DATABASE_URL="{FAKE_DB}"\nJOB_AGENT_API_TOKEN="{FAKE_TOKEN}"\n')
    private(support / "frontend.private.env", "FRONTEND_SESSION_SECRET=TEST_FAKE_SESSION_SECRET_ONLY_000000000000\n")
    for rel in ("frontend/.next/BUILD_ID", "frontend/.next/standalone/server.js"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("x")
    (repo / "frontend/src").mkdir(parents=True)
    old = (repo / "frontend/src/page.tsx")
    old.write_text("x")
    os.utime(old, (1, 1))
    python = repo / "backend/venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text("")
    profile = home / "Library/Application Support/automated-apply/brave/Default"
    profile.mkdir(parents=True)
    monkeypatch.delenv("AUTOMATED_APPLY_BRAVE_PROFILE_DIR", raising=False)
    for label in ("com.automated-apply.rust", "com.automated-apply.frontend", "com.automated-apply.codex-history"):
        (agents / f"{label}.plist").write_bytes(plistlib.dumps({"Label": label, "ProgramArguments": ["/bin/true"]}))
    (agents / "com.automated-apply.frontend.plist.disabled").write_text("old")
    paths = cutover.Paths(repo=repo, home=home, python=python, node=python, uid=501)
    launchd = FakeLaunchd({"com.automated-apply.rust": 50792, "com.automated-apply.frontend": 50794,
                           "com.automated-apply.codex-history": None})
    return paths, launchd


# --- 6B.1 plist templates -----------------------------------------------------------------------
def test_rendered_plists_are_valid_and_wire_caffeinate_loopback_and_v2_backend(world):
    paths, _ = world
    rendered = {label: plistlib.loads(cutover.render_plist(label, paths)) for label in cutover.V2_LABELS}
    worker = rendered["com.automated-apply.worker-v2"]
    assert worker["ProgramArguments"][:3] == ["/usr/bin/caffeinate", "-i", "--"]
    assert worker["ProgramArguments"][3:] == [str(paths.python), "-m", "backend.app.browser_v2.cli", "worker"]
    assert worker["ThrottleInterval"] == 30 and worker["KeepAlive"] == {"SuccessfulExit": False, "Crashed": True}
    api = rendered["com.automated-apply.api-v2"]
    assert api["ProgramArguments"] == [str(paths.python), "-m", "backend.app.browser_v2.api_launcher"]
    assert api["ThrottleInterval"] == 15 and api["ProcessType"] == "Background"
    argv = api_launcher.uvicorn_argv("/x/phase1.private.env")
    assert argv[argv.index("--host") + 1] == "127.0.0.1" and argv[argv.index("--port") + 1] == "8000"
    assert argv[argv.index("--env-file") + 1] == "/x/phase1.private.env"
    frontend = rendered["com.automated-apply.frontend-v2"]
    assert frontend["ProgramArguments"][1].endswith("frontend/run-local-python-v2.mjs")
    assert frontend["ProgramArguments"][-2:] == ["--port", "3000"]
    for label, data in rendered.items():
        assert data["Label"] == label and data["RunAtLoad"] is True
        assert data["StandardOutPath"].startswith(str(paths.log_dir))
        assert "8011" not in json.dumps(data)
    launcher = (REPO / "frontend/run-local-python-v2.mjs").read_text()
    assert 'PYTHON_V2_BACKEND = "http://127.0.0.1:8000"' in launcher
    assert "BACKEND_ORIGIN: PYTHON_V2_BACKEND" in launcher and "RUST_AGENT_URL: PYTHON_V2_BACKEND" in launcher
    assert "RUST_AGENT_LISTEN" not in launcher and "127.0.0.1:8011" not in launcher.split("PYTHON_V2_BACKEND =")[1]


def test_rendered_plists_contain_zero_secrets(world):
    paths, _ = world
    secrets = cutover.secret_values(paths.env_file, paths.frontend_env_file)
    assert FAKE_TOKEN in secrets and FAKE_DB in secrets
    for label in cutover.V2_LABELS:
        text = cutover.render_plist(label, paths).decode()
        assert not any(value in text for value in secrets)
        for key in ("JOB_AGENT_API_TOKEN", "TELEGRAM_BOT_TOKEN", "DATABASE_URL", "PASSWORD", "SECRET"):
            assert key not in text


def test_install_refuses_when_a_secret_would_leak_into_a_plist(world):
    paths, launchd = world
    leaky = cutover.Paths(repo=Path(f"/tmp/{FAKE_TOKEN}"), home=paths.home, python=paths.python,
                          node=paths.node, uid=501)
    with pytest.raises(RuntimeError, match="secret value"):
        cutover.install_v2(leaky, launchd, {})
    assert not list((paths.home / "Library/LaunchAgents").glob("*-v2.plist"))


# --- 6B.1 cutover plan / apply / rollback --------------------------------------------------------
def test_plan_is_read_only_and_retires_rust(world):
    paths, launchd = world
    before = sorted(p.name for p in paths.launch_agents.iterdir())
    plan = cutover.build_plan(paths, launchd)
    assert plan.ready, [p for p in plan.prerequisites if not p.ok]
    assert "launchctl bootout gui/501/com.automated-apply.rust" in plan.actions
    assert any("com.automated-apply.frontend.plist.disabled-" in a for a in plan.actions)  # no clobbering
    assert plan.untouched == ["com.automated-apply.codex-history"]
    assert sorted(p.name for p in paths.launch_agents.iterdir()) == before
    assert not launchd.commands("bootout") and not launchd.commands("bootstrap")


def test_plan_blocks_apply_when_migration_004_missing(world):
    paths, _ = world
    launchd = FakeLaunchd({"com.automated-apply.rust": 1}, tables=[])
    report = cutover.apply_cutover(paths, launchd, wait=False)
    assert report["applied"] is False and report["reason"] == "prerequisites_failed"
    assert (paths.launch_agents / "com.automated-apply.rust.plist").exists()
    assert not launchd.commands("bootout") and not paths.backup_root.exists()


def test_apply_snapshot_then_rollback_round_trip(world):
    paths, launchd = world
    original = (paths.launch_agents / "com.automated-apply.rust.plist").read_bytes()
    report = cutover.apply_cutover(paths, launchd, wait=False)
    assert report["applied"] is True
    backup = Path(report["backup_dir"])
    manifest = json.loads((backup / "manifest.json").read_text())
    assert set(manifest["files"]) >= {"com.automated-apply.rust.plist", "com.automated-apply.frontend.plist"}
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700
    # Legacy Rust is retired: unloaded + renamed so RunAtLoad can never revive the 409 poller.
    assert "gui/501/com.automated-apply.rust" in launchd.commands("bootout")
    assert "com.automated-apply.rust" not in launchd.loaded
    assert not (paths.launch_agents / "com.automated-apply.rust.plist").exists()
    assert (paths.launch_agents / "com.automated-apply.rust.plist.disabled").exists()
    assert (paths.launch_agents / "com.automated-apply.frontend.plist.disabled").read_text() == "old"
    for label in cutover.V2_LABELS:
        assert (paths.launch_agents / f"{label}.plist").exists() and launchd.loaded[label] == 999
    assert (paths.launch_agents / "com.automated-apply.codex-history.plist").exists()
    assert "gui/501/com.automated-apply.codex-history" not in launchd.commands("bootout")

    result = cutover.rollback(paths, backup, launchd)
    assert result["rolled_back"] is True
    assert (paths.launch_agents / "com.automated-apply.rust.plist").read_bytes() == original
    assert not (paths.launch_agents / "com.automated-apply.rust.plist.disabled").exists()
    for label in cutover.V2_LABELS:
        assert not (paths.launch_agents / f"{label}.plist").exists() and label not in launchd.loaded
        assert (Path(result["v2_plists_moved_to"]) / f"{label}.plist").exists()  # moved, not deleted
    assert {"com.automated-apply.rust", "com.automated-apply.frontend"} <= set(launchd.loaded)


def test_rollback_refuses_folders_outside_the_backup_root(world, tmp_path):
    paths, launchd = world
    rogue = tmp_path / "rogue"
    rogue.mkdir()
    (rogue / "manifest.json").write_text("{}")
    with pytest.raises(ValueError, match="not a cutover backup"):
        cutover.rollback(paths, rogue, launchd)


def test_apply_requires_typed_confirmation(world, monkeypatch, capsys):
    paths, launchd = world
    monkeypatch.setattr("builtins.input", lambda prompt: "yes please")
    assert cutover.main(["apply"], paths=paths, runner=launchd) == 1
    assert json.loads(capsys.readouterr().out)["reason"] == "not_confirmed"
    assert not launchd.commands("bootout")


def test_status_reports_pid_logs_and_sleep_assertion(world):
    paths, launchd = world
    launchd.loaded["com.automated-apply.worker-v2"] = 4243
    report = cutover.status(paths, launchd)
    worker = report["services"]["com.automated-apply.worker-v2"]
    assert worker["loaded"] and worker["pid"] == 4243 and worker["logs"]["out"]["path"].endswith("worker-v2.out.log")
    assert report["legacy_loaded"] == ["com.automated-apply.frontend", "com.automated-apply.rust"]
    assert report["sleep_prevention"]["worker_holds_assertion"] is False


# --- 6B.2 health parsers -------------------------------------------------------------------------
def test_pmset_parser_and_sleep_evaluation():
    active = health.parse_pmset_assertions(PMSET_ACTIVE)
    assert active["prevent_user_idle_system_sleep"] == 1 and active["caffeinate_pids"] == [4242]
    services = {"com.automated-apply.worker-v2": {"pid": 4242, "last_exit": 0}}
    assert health.evaluate_sleep(active, services).status == health.OK
    missing = health.parse_pmset_assertions(PMSET_NONE)
    assert missing["prevent_user_idle_system_sleep"] == 0 and missing["caffeinate_pids"] == []
    assert health.evaluate_sleep(missing, services).status == health.WARN
    assert health.evaluate_sleep(active, {}).status == health.WARN  # worker-v2 not loaded


@pytest.mark.parametrize(("count", "expected"), [(2, "ok"), (3, "ok"), (4, "warn"), (5, "fail"), (None, "skip")])
def test_db_connection_budget_warns_at_four(count, expected):
    assert health.evaluate_connections(count).status == expected


def test_telegram_409_and_legacy_rust_detection():
    rust = {"com.automated-apply.rust": {"pid": 1}}
    assert health.evaluate_telegram("polling", rust).status == health.FAIL
    assert health.evaluate_telegram("conflict", {}).status == health.FAIL
    assert health.evaluate_telegram("polling", {}).status == health.OK


def test_heartbeat_freshness():
    now = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
    assert health.evaluate_heartbeat(now - timedelta(minutes=2), "RUNNING", "SLEEPING", now).status == health.OK
    stale = health.evaluate_heartbeat(now - timedelta(minutes=12), "RUNNING", "SLEEPING", now)
    assert stale.status == health.FAIL and stale.data["age_sec"] == 720
    assert health.evaluate_heartbeat(now - timedelta(minutes=12), "PAUSED", "PAUSED", now).status == health.WARN
    assert health.evaluate_heartbeat(None, "RUNNING", None, now).status == health.WARN


def test_db_checks_flag_missing_migration_and_launchctl_parser():
    checks = {c.name: c for c in health.db_checks({"tables": {"applications": False, "portal_rules": True},
                                                   "other_connections": 4, "worker": None})}
    assert checks["migration_004"].status == health.FAIL and checks["db_connections"].status == health.WARN
    assert health.db_checks(None, "OSError")[0].status == health.FAIL
    rows = health.parse_launchctl_list(launchctl_text(("50792", "0", "com.automated-apply.rust"),
                                                      ("-", "1", "com.automated-apply.api-v2")))
    assert rows["com.automated-apply.rust"]["pid"] == 50792 and rows["com.automated-apply.api-v2"]["pid"] is None


async def test_run_health_is_offline_safe_with_fakes(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOMATED_APPLY_BRAVE_PROFILE_DIR", str(tmp_path / "support/brave"))
    monkeypatch.setenv(logrotate.LOG_DIR_VARIABLE, str(tmp_path / "logs"))

    def runner(command):
        if command[:2] == ["/bin/launchctl", "list"]:
            return launchctl_text(("4243", "0", "com.automated-apply.worker-v2"))
        return PMSET_NONE if "pmset" in command[0] else ""

    report = await health.run_health(include_db=False, runner=runner, fetch=lambda url: 200, env={})
    names = {c["name"]: c["status"] for c in report["checks"]}
    assert names["api_v2_http"] == "ok" and names["database"] == "skip" and names["telegram_conflict"] == "warn"
    assert names["mail_channel"] in {"ok", "warn"} and report["ok"] is True
    assert "READ_AND_DRAFT_ONLY" in json.dumps(report)


async def test_sigterm_heartbeat_never_changes_desired_running_state():
    store = MemoryStore()
    await store.set_worker_control(WorkerState.RUNNING)
    await store.worker_heartbeat("OFFLINE")  # what Worker.run writes after SIGTERM
    control = await store.get_worker_control()
    assert control.desired_state is WorkerState.RUNNING and control.observed_state == "OFFLINE"


# --- 6B.4 selector diagnostics -------------------------------------------------------------------
def raw_probe(buttons: int = 5, text: str = "Apply") -> dict:
    return {
        "url": "https://www.instahyre.com/job-123-backend/?token=SECRETQUERY&utm=x#frag",
        "title": "Backend Engineer | reach me at owner.person@gmail.com or +91 98765 43210",
        "buttons": [{"tag": "button", "text": text, "id": "b", "cls": "btn", "disabled": False,
                     "value": "should-never-persist"} for _ in range(buttons)],
        "headings": ["Backend Engineer", "Contact: owner.person@gmail.com"],
        "inputs": [{"tag": "input", "type": "tel", "name": "phone", "value": "9876543210", "required": True}],
        "modals": [{"tag": "div", "role": "dialog", "fields": 2, "buttons": 1}],
        "snippets": ["120 applicants", "2 days ago"],
        "selector_matches": {"logged_in": {"valid": True, "total": 1, "visible": 1},
                             "login_form": {"valid": True, "total": 0, "visible": 0}},
    }


def test_probe_is_scrubbed_whitelisted_and_matches_patterns():
    from backend.app.browser_v2.adapters.instahyre import InstahyreAdapter

    css, patterns = diagnostics.adapter_selectors(InstahyreAdapter(jitter=(0, 0)))
    assert "logged_in" in css and "apply_text" in patterns
    payload = diagnostics.build_probe(raw_probe(), "instahyre", patterns, secrets=("Karan Example",))
    text = json.dumps(payload)
    assert "owner.person@gmail.com" not in text and "98765 43210" not in text and "9876543210" not in text
    assert "SECRETQUERY" not in text and payload["url"] == "https://www.instahyre.com/job-123-backend/"
    assert "should-never-persist" not in text and "value" not in payload["inputs"][0]
    assert payload["selectors_missed"] == ["login_form"]
    assert payload["pattern_matches"]["apply_text"]["count"] == 5


def test_probe_is_capped_at_30_kb():
    payload = diagnostics.build_probe(raw_probe(buttons=5000, text="Apply " + "x" * 400), "naukri",
                                      diagnostics.NAUKRI_PATTERNS)
    assert len(json.dumps(payload, ensure_ascii=False).encode()) <= diagnostics.MAX_PROBE_BYTES


class FakePage:
    def __init__(self, raw):
        self.raw = raw

    async def evaluate(self, script, arg):
        assert "selector_matches" in script and "limits" in arg
        return self.raw

    async def screenshot(self, path, full_page):
        Path(path).write_bytes(b"\x89PNG fake")


async def test_capture_bundle_writes_private_files_and_refuses_live(tmp_path):
    page = FakePage(raw_probe())
    with pytest.raises(diagnostics.DiagnosticsRefused):
        await diagnostics.capture_bundle(page, "naukri", object(), dry_run=False, root=tmp_path)
    assert not any(tmp_path.iterdir())
    result = await diagnostics.capture_bundle(page, "naukri", object(), dry_run=True, root=tmp_path,
                                              profile={"email": "owner.person@gmail.com"})
    probe = Path(result["dom_probe"])
    assert probe.parent.name.startswith("naukri-") and result["bytes"] <= diagnostics.MAX_PROBE_BYTES
    assert stat.S_IMODE(probe.stat().st_mode) == 0o600 and (probe.parent / "page.png").exists()
    assert "owner.person@gmail.com" not in probe.read_text()


def test_cli_refuses_debug_selectors_on_live_submit(capsys):
    assert cli.main(["test-apply", "--portal", "naukri", "--live", "--debug-selectors"]) == 2
    assert "--debug-selectors is allowed only with --dry-run" in capsys.readouterr().out


# --- 6B.5 cleanup guardrails ---------------------------------------------------------------------
class FakeGit:
    def __init__(self, tags=()):
        self.tags = list(tags)
        self.calls = []

    def __call__(self, args):
        self.calls.append(list(args))
        if args[:2] == ["tag", "-l"]:
            return 0, "".join(f"{t}\n" for t in self.tags)
        if args[0] == "rev-parse":
            return (0, "abc\n") if any(t in args[-1] for t in self.tags) else (1, "")
        if args[0] == "cat-file":
            return 0, ""
        if args[0] == "grep":
            return 1, ""
        return 0, ""


@pytest.fixture
def cleanup_world(tmp_path):
    repo, home = tmp_path / "repo", tmp_path / "home"
    runtime = repo / ".local/runtime-support"
    (runtime / "releases/rust-1/bin").mkdir(parents=True)
    (runtime / "releases/rust-1/bin/agent").write_bytes(b"x" * 4096)
    private(runtime / "phase1.private.env", "DATABASE_URL=TEST_FAKE_ONLY\n")
    (repo / "target/debug").mkdir(parents=True)
    (repo / "target/debug/blob").write_bytes(b"y" * 8192)
    (repo / "reports/v2-migration").mkdir(parents=True)
    (repo / "reports/old-dump").mkdir()
    (repo / "reports/old-dump/a.log").write_text("z")
    support = home / "Library/Application Support"
    support.mkdir(parents=True)
    (support / "Automated Apply").symlink_to(runtime)  # mirrors the real machine
    (support / "automated-apply/brave").mkdir(parents=True)
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    (agents / "com.automated-apply.telegram.plist.disabled").write_text("old")
    (agents / "com.automated-apply.codex-history.plist").write_text("keep")
    hosts = support / "BraveSoftware/Brave-Browser/NativeMessagingHosts"
    hosts.mkdir(parents=True)
    (hosts / "com.automated_apply.brave.json").write_text("{}")
    (hosts / "org.other.json").write_text("{}")
    return repo, home


def test_cleanup_plan_is_read_only_and_never_targets_protected_paths(cleanup_world, capsys):
    repo, home = cleanup_world
    assert cleanup.main(["--plan", "--json"], repo=repo, home=home, run_git=FakeGit()) == 0
    plan = json.loads(capsys.readouterr().out)
    assert plan["deleted"] == 0
    paths = {t["path"] for t in plan["targets"]}
    assert {"target", ".local/runtime-support/releases", "reports/old-dump"} <= paths
    assert not any("v2-migration" in p or "private.env" in p or p.endswith("automated-apply/brave") for p in paths)
    assert any(p.endswith("com.automated_apply.brave.json") for p in paths)
    assert not any("codex-history" in p or "org.other" in p for p in paths)
    assert (repo / "target/debug/blob").exists() and (repo / ".local/runtime-support/releases").exists()
    protected = cleanup.protected_paths(repo, home)
    for path in (repo / ".local/runtime-support", repo / ".local", home / "Library/Application Support/Automated Apply",
                 home / "Library/Application Support/automated-apply",
                 home / "Library/Application Support/automated-apply/brave",
                 home / "Library/Application Support/Automated Apply/phase1.private.env"):
        assert cleanup.is_protected(path, protected, repo), path
        with pytest.raises(PermissionError):
            cleanup.assert_deletable(path, protected, repo)
    assert not cleanup.is_protected(repo / "target", protected, repo)
    assert not cleanup.is_protected(repo / "backend/app/agent", protected, repo)
    assert cleanup.is_protected(repo / "backend", protected, repo)


@pytest.mark.parametrize(("argv", "tags", "reason"), [
    (["--execute", "--group", "C"], ["archive/pre-v2-cleanup-20261126"], "--i-tagged-backup is required"),
    (["--execute", "--group", "C", "--i-tagged-backup"], [], "archive/pre-v2-cleanup-*"),
    (["--execute", "--group", "C", "--i-tagged-backup"], ["archive/something-else"], "archive/pre-v2-cleanup-*"),
    (["--execute", "--i-tagged-backup"], ["archive/pre-v2-cleanup-20261126"], "choose at least one --group"),
])
def test_cleanup_execute_refused_without_flag_and_verified_tag(cleanup_world, capsys, argv, tags, reason):
    repo, home = cleanup_world
    fake = FakeGit(tags)
    code = cleanup.main([*argv, "--yes"], repo=repo, home=home, run_git=fake, launchctl=lambda c: "")
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and out["refused"] and out["deleted"] == 0
    assert any(reason in r for r in out["reasons"])
    assert (home / "Library/LaunchAgents/com.automated-apply.telegram.plist.disabled").exists()


def test_cleanup_group_a_refused_while_legacy_agents_run(cleanup_world, capsys):
    repo, home = cleanup_world
    loaded = launchctl_text(("50792", "0", "com.automated-apply.rust"))
    code = cleanup.main(["--execute", "--group", "A", "--i-tagged-backup", "--yes"], repo=repo, home=home,
                        run_git=FakeGit(["archive/pre-v2-cleanup-20261126"]), launchctl=lambda c: loaded)
    assert code == 2 and "legacy agents still loaded" in json.dumps(json.loads(capsys.readouterr().out))
    assert (repo / "target/debug/blob").exists()


def test_cleanup_executes_only_the_chosen_group_with_verified_tag(cleanup_world, capsys):
    repo, home = cleanup_world
    code = cleanup.main(["--execute", "--group", "A", "--i-tagged-backup", "--yes"], repo=repo, home=home,
                        run_git=FakeGit(["archive/pre-v2-cleanup-20261126"]), launchctl=lambda c: "")
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["deleted"] >= 3
    assert not (repo / "target").exists() and not (repo / ".local/runtime-support/releases").exists()
    assert (repo / ".local/runtime-support/phase1.private.env").read_text().startswith("DATABASE_URL")
    assert (repo / "reports/v2-migration").is_dir()
    assert (home / "Library/Application Support/automated-apply/brave").is_dir()
    assert (home / "Library/LaunchAgents/com.automated-apply.telegram.plist.disabled").exists()  # group C kept


# --- 6B.1 log rotation ---------------------------------------------------------------------------
def test_log_rotation_copy_truncates_and_keeps_three_backups(tmp_path):
    log = tmp_path / "worker-v2.out.log"
    for round_ in range(5):
        log.write_bytes(str(round_).encode() * 64)
        assert logrotate.rotate_file(log, max_bytes=32, backups=3) is True
        assert log.exists() and log.stat().st_size == 0  # same inode stays valid for launchd
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "worker-v2.out.log", "worker-v2.out.log.1", "worker-v2.out.log.2", "worker-v2.out.log.3"]
    assert (tmp_path / "worker-v2.out.log.1").read_bytes() == b"4" * 64
    log.write_bytes(b"small")
    assert logrotate.rotate_file(log, max_bytes=32) is False
    assert logrotate.rotate_service_logs("worker-v2", tmp_path) == []


# --- 6B.3 MCP configs ----------------------------------------------------------------------------
@pytest.mark.parametrize(("path", "key"), [(".mcp.json", "mcpServers"), (".vscode/mcp.json", "servers")])
def test_mcp_configs_point_to_python_v2_fastmcp(path, key):
    raw = (REPO / path).read_text()
    config = json.loads(raw)
    server = config[key]["automated-apply-browser-v2"]
    assert server["type"] == "stdio" and server["command"].endswith("backend/venv/bin/python")
    assert server["args"] == ["-m", "backend.app.browser_v2.cli", "mcp"]
    assert "mcp_server.py" not in raw and "automated-apply-agents" not in raw and "8011" not in raw
