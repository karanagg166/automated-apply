"""Explicit local resume check, or deployed single-purpose resume worker.

No DDL, approval, AI calls, sends or application submissions. Output is sanitized.
"""

import argparse
import asyncio
import json
import signal

from backend.app.core.config import get_settings
from backend.app.db.session import close_db_engine, get_session_factory
from backend.app.resume_sync.scheduler import serve, tick
from backend.app.resume_sync.service import ResumeSyncService


async def run(args):
    settings = get_settings()
    factory = get_session_factory()
    try:
        if args.serve:
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, stop.set)
            await serve(factory, settings, stop)
        elif args.scheduled:
            print(json.dumps({"outcome": await tick(factory, settings), "scheduler_active": False}))
        else:
            async with factory() as session, session.begin():
                result = await ResumeSyncService(session, settings).sync()
                state = result["state"]
                print(json.dumps({"outcome": result["outcome"], "saved_encrypted_version": state.latest is not None,
                                  "pending_owner_review": state.pending_changes, "error": state.last_error,
                                  "scheduler_active": state.scheduler_active}))
    finally:
        await close_db_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--serve", action="store_true", help="Run the actual opt-in worker loop; no worker is launched by default")
    mode.add_argument("--scheduled", action="store_true", help="Check once if owner-enabled and due; does not claim a running scheduler")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception:
        # Never print a database URL, credential, PDF content or untrusted remote error.
        print(json.dumps({"outcome": "failed", "error": "resume_sync_unavailable_check_configuration_and_database"}))
        raise SystemExit(1) from None
