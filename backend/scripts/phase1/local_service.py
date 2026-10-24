"""Explicit loopback services. No hidden API-startup workers."""
import argparse
import asyncio
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("service", choices=["api", "telegram", "preflight", "status"])
    parser.add_argument("--env-file", required=True)
    args = parser.parse_args()
    from backend.app.core.config import configure_operator
    from backend.app.operations.configuration import load_settings
    settings = load_settings(args.env_file)
    configure_operator(settings)
    if settings.GMAIL_SENDING_ENABLED or settings.AUTOMATION_EXECUTION_ENABLED:
        raise SystemExit("phase1_execution_gates_must_be_disabled")
    if args.service == "api":
        from urllib.parse import urlsplit

        import uvicorn
        endpoint = urlsplit(settings.LOCAL_AGENT_ENDPOINT)
        uvicorn.run("backend.app.main:app", host="127.0.0.1", port=endpoint.port,
                    access_log=False, proxy_headers=False)
    else:
        asyncio.run(run(args.service, settings))


async def run(service, settings):
    import json

    from backend.app.db.session import close_db_engine, get_engine, get_session_factory
    from backend.app.operations.health import database_health
    try:
        if service in {"preflight", "status"}:
            from backend.app.operations.readiness import environment_readiness
            output = environment_readiness(settings).model_dump(mode="json")
            try:
                output["database_probe"] = await database_health(get_engine(), settings)
            except Exception:
                output["database_probe"] = {"state": "disconnected", "error": "database_not_ready"}
            print(json.dumps(output, indent=2))
            return
        await database_health(get_engine(), settings)
        from backend.app.local_agent.telegram import (
            TelegramError,
            run_worker,
            worker_lock,
        )
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for name in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(name, stop.set)
        try:
            async with worker_lock(settings):
                await run_worker(settings, get_session_factory(), stop=stop)
        except TelegramError as exc:
            raise SystemExit(exc.code) from None
    finally:
        await close_db_engine()


if __name__ == "__main__":
    main()
