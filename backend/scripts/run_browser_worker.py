#!/usr/bin/env python3
"""Explicit opt-in dedicated Chrome worker; never run in the Telegram process."""

import argparse
import asyncio
import signal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.app.browser.worker import BrowserWorker, ChromeDriver
from backend.app.core.config import get_settings
from backend.app.db.session import close_db_engine, get_engine, get_session_factory
from backend.app.operations.health import database_health


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-parent", type=Path, required=True)
    parser.add_argument(
        "--sign-in", help="Owner-operated sign-in only; no agent inspection or filling"
    )
    args = parser.parse_args()
    settings = get_settings()
    if not settings.BROWSER_AUTOMATION_ENABLED:
        raise SystemExit("BROWSER_AUTOMATION_ENABLED must be explicitly enabled")
    await database_health(get_engine(), settings)
    stop = asyncio.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(name, stop.set)
    driver = ChromeDriver(args.profile_parent.resolve() / "automated-apply-automation")
    if args.sign_in:
        from backend.app.browser.service import target

        url = target(args.sign_in, settings)
        result = await driver.call(
            "sign_in", url=url, profile=driver.profile, headless=False
        )
        if result.get("state") != "manual_sign_in":
            await driver.close()
            raise SystemExit("Dedicated sign-in browser unavailable")
        try:
            await asyncio.to_thread(
                input,
                "Finish signing in yourself in the dedicated Chrome window, then press Enter here to close it. No agent actions run in this mode. ",
            )
        finally:
            await driver.close()
            await close_db_engine()
        return
    worker = BrowserWorker(get_session_factory(), settings, driver)
    try:
        while not stop.is_set():
            await worker.run_once()
            try:
                await asyncio.wait_for(stop.wait(), 2)
            except TimeoutError:
                pass
    finally:
        await driver.close()
        await close_db_engine()


if __name__ == "__main__":
    asyncio.run(main())
