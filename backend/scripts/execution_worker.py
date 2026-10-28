"""Explicit local worker; installing/running against live data needs owner approval."""

import argparse
import asyncio
import signal

from backend.app.operations.configuration import load_settings


async def main(env_file):
    from backend.app.core.config import configure_operator

    configure_operator(load_settings(env_file))
    from backend.app.core.config import get_settings
    from backend.app.db.session import close_db_engine, get_engine, get_session_factory
    from backend.app.execution.worker import serve
    from backend.app.operations.health import database_health

    await database_health(get_engine(), get_settings())
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    try:
        await serve(get_session_factory(), stop)
    finally:
        await close_db_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True)
    asyncio.run(main(parser.parse_args().env_file))
