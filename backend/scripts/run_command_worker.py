#!/usr/bin/env python3
"""Run the shared command queue without Telegram transport. No implicit startup worker."""
import asyncio
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.agent.executor import run_worker
from backend.app.core.config import get_settings
from backend.app.db.session import close_db_engine, get_engine, get_session_factory
from backend.app.operations.health import database_health


async def main():
    settings = get_settings()
    await database_health(get_engine(), settings)
    stop = asyncio.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(name, stop.set)
    try:
        await run_worker(get_session_factory(), settings, stop)
    finally:
        await close_db_engine()


if __name__ == "__main__":
    asyncio.run(main())
