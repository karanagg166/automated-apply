"""Read-only owner-assisted lock test: observe a new sent pong while locked.

Never locks the screen, changes power settings, sends messages, or prints IDs.
An absent lock observation or reply remains unverified, not a passing test.
"""
import argparse
import asyncio
import json
import os
import plistlib

# Fixed read-only OS metadata query; no shell or user-supplied executable.
import subprocess  # nosec B404
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def screen_locked():
    # All arguments are constants; this does not execute page or message text.
    result = subprocess.run(["/usr/sbin/ioreg", "-a", "-n", "Root", "-d", "1"],
                            capture_output=True, check=True, timeout=5)  # nosec B603
    records = plistlib.loads(result.stdout)
    locks, current_console = [], False
    def walk(value):
        nonlocal current_console
        if isinstance(value, dict):
            if type(value.get("IOConsoleLocked")) is bool:
                locks.append(value["IOConsoleLocked"])
            for user in value.get("IOConsoleUsers", []):
                if user.get("kCGSSessionUserIDKey") == os.getuid() and user.get("kCGSSessionOnConsoleKey"):
                    current_console = True
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk(records)
    return locks[0] if current_console and locks and all(item == locks[0] for item in locks) else None


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--seconds", type=int, default=300)
    args = parser.parse_args()
    if sys.platform != "darwin" or not 30 <= args.seconds <= 600:
        raise SystemExit("macos_and_30_to_600_seconds_required")
    from sqlalchemy import select

    from backend.app.core.config import configure_operator
    from backend.app.operations.configuration import load_settings
    configure_operator(load_settings(args.env_file))
    from backend.app.db.session import close_db_engine, get_session_factory
    from backend.app.local_agent.models import TelegramDelivery, TelegramState
    output = ROOT / "reports/phase1/locked-worker.private.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"state": "pending_owner_action", "evidence_type": "actual_macOS_lock_property_and_PostgreSQL_live_worker",
              "started_at": datetime.now(timezone.utc).isoformat(), "screen_lock_observed": False,
              "new_pong_sent_while_locked": False, "live_poll_while_locked": False}
    with output.open("x") as file:
        output.chmod(0o600)
        file.write(json.dumps(report, indent=2) + "\n")
    loop = asyncio.get_running_loop()
    deadline, previously_locked, locked_since, baseline = loop.time() + args.seconds, None, None, set()
    try:
        while loop.time() < deadline:
            before = screen_locked()
            async with get_session_factory()() as session:
                state = await session.get(TelegramState, "primary")
                sent = set((await session.scalars(select(TelegramDelivery.update_id).where(
                    TelegramDelivery.state == "sent", TelegramDelivery.reply.like("pong%")))).all())
            after = screen_locked()
            if before is True and after is True:
                report["screen_lock_observed"] = True
                if previously_locked is not True:
                    locked_since, baseline = datetime.now(timezone.utc), sent
                if state and state.evidence_type == "live_poll" and not state.last_error and state.last_poll_at:
                    poll = state.last_poll_at.replace(tzinfo=timezone.utc)
                    report["live_poll_while_locked"] |= poll >= locked_since
                    report["last_poll_at"] = poll.isoformat()
                    if sent - baseline and poll >= locked_since:
                        report.update(state="passed", new_pong_sent_while_locked=True,
                                      verified_at=datetime.now(timezone.utc).isoformat())
            previously_locked = before if before == after else None
            report["last_checked_at"] = datetime.now(timezone.utc).isoformat()
            output.write_text(json.dumps(report, indent=2) + "\n")
            if report["state"] == "passed":
                break
            await asyncio.sleep(2)
        if report["state"] != "passed":
            report["blocker"] = "owner_screen_lock_and_new_phone_ping_not_verified_before_deadline"
            output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        await close_db_engine()


if __name__ == "__main__":
    asyncio.run(main())
