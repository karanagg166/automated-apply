"""Install/test the proposed browser extension only inside disposable local PostgreSQL 17.

No production migration runner is exposed. Base Phase 9 SQL/manifest remain pinned.
"""

import argparse
import asyncio
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def verify(url, serve=False, receipt_mode="valid"):
    # Reuse the existing isolated fixture's base migrations, seeding, server and cleanup.
    from backend.scripts.browser_mock_demo import run

    await run(url, serve=serve, submission_demo=True, receipt_mode=receipt_mode)


async def recover_worker(packet_id):
    url = os.environ["BROWSER_FIXTURE_DATABASE_URL"]
    parsed = urlsplit(url)
    origin = os.environ["BROWSER_FIXTURE_ORIGIN"]
    site = urlsplit(origin)
    if (
        parsed.hostname != "127.0.0.1"
        or not re.fullmatch(
            r"/candidate_profile_test_browser_[a-f0-9]{32}", parsed.path
        )
        or parsed.query
        or parsed.fragment
        or site.scheme != "http"
        or site.hostname != "127.0.0.1"
        or site.path
        or site.query
        or site.fragment
        or site.username
        or site.password
        or site.port is None
    ):
        raise ValueError(
            "Only an isolated loopback browser fixture can be recovered by this test worker"
        )
    from backend.app.core.config import Settings, configure_operator

    configure_operator(
        Settings(
            _env_file=None,
            ENVIRONMENT="testing",
            LOG_LEVEL="WARNING",
            DATABASE_URL=url.replace("postgresql://", "postgresql+asyncpg://", 1),
            BROWSER_MOCK_SUBMISSION_ENABLED=True,
            BROWSER_ALLOWED_ORIGINS=[origin],
            GEMINI_API_KEY=None,
            COHERE_EVALUATION_ENABLED=False,
            OLLAMA_ENABLED=False,
        )
    )
    from backend.app.browser.runner import browser
    from backend.app.browser.submissions import recover
    from backend.app.db.session import close_db_engine, get_session_factory

    assert not browser.sessions
    try:
        async with get_session_factory()() as session:
            print(json.dumps(await recover(session, UUID(packet_id))))
    finally:
        await close_db_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument(
        "--receipt-mode", choices=["valid", "missing", "wrong"], default="valid"
    )
    parser.add_argument("--recover-worker")
    args = parser.parse_args()
    if args.recover_worker:
        asyncio.run(recover_worker(args.recover_worker))
    else:
        asyncio.run(
            verify(
                os.environ["PROFILE_TEST_DATABASE_URL"], args.serve, args.receipt_mode
            )
        )
