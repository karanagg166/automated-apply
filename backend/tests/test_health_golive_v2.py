"""Phase 8 go-live prerequisites in `cli health-check` (pure evaluators, no DB/launchctl)."""

from __future__ import annotations

from pathlib import Path

from backend.app.browser_v2.health import (
    FAIL,
    OK,
    WARN,
    check_launchd_plists,
    check_telegram_config,
    db_checks,
    evaluate_fences,
    evaluate_live_mode,
    evaluate_portal_sessions,
)

TOKEN = "123456789:TEST_FAKE_TOKEN_ONLY_abcdefghijklmnop"


def test_fences_ok_when_migrated_rows_exist():
    check = evaluate_fences({"migrated_historical_quarantine_never_replay": 3,
                             "migrated_receipt_fence_never_replay": 1}, 4)
    assert check.status == OK and "4 migrated" in check.detail
    assert evaluate_fences({}, 0).status == WARN


def test_portal_sessions_flag_enabled_login_portals_only():
    rows = [{"platform": "naukri", "enabled": True, "auto_apply_enabled": True, "auth_status": "AUTH_REQUIRED"},
            {"platform": "greenhouse", "enabled": True, "auto_apply_enabled": False, "auth_status": "UNKNOWN"},
            {"platform": "instahyre", "enabled": False, "auto_apply_enabled": False, "auth_status": "AUTH_REQUIRED"}]
    check = evaluate_portal_sessions(rows)
    assert check.status == WARN and check.data["login_needed"] == ["naukri"]
    assert check.data["auto_apply"] == ["naukri"]
    rows[0]["auth_status"] = "OK"
    assert evaluate_portal_sessions(rows).status == OK
    assert evaluate_portal_sessions([]).status == WARN


def test_telegram_config_never_prints_the_token():
    ok = check_telegram_config({"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_OWNER_CHAT_ID": "4242"})
    assert ok.status == OK and TOKEN not in str(ok.data) and ok.data["owner_chat_id"] == "•242"
    missing = check_telegram_config({})
    assert missing.status == WARN and "TELEGRAM_BOT_TOKEN" in missing.detail


def test_launchd_plists_presence(tmp_path: Path):
    assert check_launchd_plists(tmp_path).status == WARN
    for label in ("api-v2", "worker-v2", "frontend-v2"):
        (tmp_path / f"com.automated-apply.{label}.plist").write_text("<plist/>")
    assert check_launchd_plists(tmp_path).status == OK


def test_live_mode_flags_dry_run_and_no_auto_apply():
    portals = [{"platform": "naukri", "enabled": True, "auto_apply_enabled": False}]
    assert evaluate_live_mode(True, portals).status == WARN
    off = evaluate_live_mode(False, portals)
    assert off.status == WARN and "auto-apply is off" in off.detail
    portals[0]["auto_apply_enabled"] = True
    live = evaluate_live_mode(False, portals)
    assert live.status == OK and live.data["auto_apply_portals"] == ["naukri"]


def test_db_checks_include_fences_and_sessions():
    snapshot = {"tables": {"applications": True}, "other_connections": 1,
                "never_replay": {"migrated_historical_submitted_never_replay": 2}, "never_replay_total": 2,
                "portals": [{"platform": "naukri", "enabled": True, "auth_status": "OK"}]}
    names = {c.name: c.status for c in db_checks(snapshot)}
    assert names["never_replay_fences"] == OK and names["portal_sessions"] == OK
    assert db_checks(None, "OSError")[0].status == FAIL


def test_sleep_assertion_held_by_caffeinate_on_behalf_of_the_worker_pid():
    from backend.app.browser_v2.health import evaluate_sleep, parse_pmset_assertions

    text = ("Assertion status system-wide:\n   PreventUserIdleSystemSleep     1\nListed by owning process:\n"
            '   pid 37020(caffeinate): [0x1] 00:00:48 PreventUserIdleSystemSleep named: "caffeinate command-line tool"\n'
            "\tDetails: caffeinate asserting on behalf of '/x/venv/bin/python' (pid 37017)\n")
    assertions = parse_pmset_assertions(text)
    assert evaluate_sleep(assertions, {"com.automated-apply.worker-v2": {"pid": 37017}}).status == OK
    assert evaluate_sleep(assertions, {"com.automated-apply.worker-v2": {"pid": 99}}).status == WARN
