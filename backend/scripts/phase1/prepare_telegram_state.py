"""Explicitly replace this suite's completed simulated polling identity locally.

No administrator credentials, DELETE, remote database, live-state override or
webhook changes. A private recovery snapshot preserves the simulated state.
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def validate_rebind(settings, state, deliveries, me, updates):
    from sqlalchemy.engine import make_url

    from backend.app.local_agent.telegram import TelegramError, authorized
    target = make_url(settings.DATABASE_URL)
    if (settings.ENVIRONMENT not in {"development", "testing"} or settings.DB_REMOTE_ONLY
            or settings.DATABASE_SCHEMA != "public"
            or target.host != "127.0.0.1" or target.database != "candidate_profile_test"):
        raise TelegramError("disposable_local_database_required")
    if not state or state.evidence_type != "simulated_transport" or state.bot_id != "999999":
        raise TelegramError("completed_simulated_fixture_required")
    if any(row.state != "sent" for row in deliveries):
        raise TelegramError("unresolved_simulated_outbox_preserved")
    if (not isinstance(updates, list) or not updates
            or any(not isinstance(row, dict) or type(row.get("update_id")) is not int for row in updates)
            or not any(isinstance(row.get("message"), dict) and authorized(row["message"], settings) for row in updates)):
        raise TelegramError("bound_owner_update_required")
    if min(row["update_id"] for row in updates) <= max((row.update_id for row in deliveries), default=-1):
        raise TelegramError("update_identity_collision_preserved")
    if str(me["id"]) == state.bot_id:
        raise TelegramError("verified_distinct_live_bot_required")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--replace-completed-simulated-state", action="store_true", required=True)
    args = parser.parse_args()
    from sqlalchemy import select

    from backend.app.core.config import configure_operator
    from backend.app.operations.configuration import load_settings
    settings = load_settings(args.env_file)
    configure_operator(settings)
    from backend.app.db.session import close_db_engine, get_session_factory
    from backend.app.local_agent.models import TelegramDelivery, TelegramState
    from backend.app.local_agent.telegram import BotAPI
    api = BotAPI(settings)
    me = await api.verify()
    updates = await api.call("getUpdates", {"timeout": 0, "limit": 100, "allowed_updates": ["message"]})
    try:
        async with get_session_factory()() as session:
            state = await session.get(TelegramState, "primary", with_for_update=True)
            deliveries = (await session.scalars(select(TelegramDelivery))).all()
            validate_rebind(settings, state, deliveries, me, updates)
            snapshot = {"evidence_type": state.evidence_type, "bot_id": state.bot_id,
                        "next_update_id": state.next_update_id,
                        "last_poll_at": state.last_poll_at.isoformat() if state.last_poll_at else None,
                        "outbox_completed_preserved": len(deliveries),
                        "prepared_at": datetime.now(timezone.utc).isoformat()}
            path = ROOT / "reports/phase1/telegram-simulation-recovery.private.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x") as file:
                path.chmod(0o600)
                file.write(json.dumps(snapshot, indent=2) + "\n")
            state.bot_id, state.next_update_id = str(me["id"]), 0
            state.last_poll_at, state.last_error = None, None
            state.evidence_type = "owner_binding_verified"
            await session.commit()
        print("simulated_poll_state_rebound; completed outbox, previews and policies preserved; no live poll claimed")
    finally:
        await close_db_engine()


if __name__ == "__main__":
    from backend.app.local_agent.telegram import TelegramError
    try:
        asyncio.run(main())
    except TelegramError as exc:
        raise SystemExit(exc.code) from None
