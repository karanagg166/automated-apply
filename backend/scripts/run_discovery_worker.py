"""Explicit worker entrypoint. Deployment and owner gates both default to off."""

import asyncio
import signal

from backend.app.automation.worker import serve
from backend.app.core.config import get_settings
from backend.app.db.session import close_db_engine, get_engine, get_session_factory
from backend.app.local_agent.process_lock import process_lock
from backend.app.operations.health import database_health


async def main():
    settings = get_settings()
    if not settings.AUTOMATION_EXECUTION_ENABLED:
        raise SystemExit(
            "Automation is disabled; separate operational authorization is required"
        )
    await database_health(get_engine(), settings)
    stop = asyncio.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(name, stop.set)
    try:
        async with process_lock(settings, "discovery"):
            await serve(get_session_factory(), settings, stop)
    finally:
        await close_db_engine()


if __name__ == "__main__":
    asyncio.run(main())
