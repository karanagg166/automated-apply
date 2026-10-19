"""Explicit operator retention maintenance; no scheduling or migration execution."""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app.core.config import get_settings
from backend.app.db.session import close_db_engine, get_db_context
from backend.app.services.contact_enrichment.retention import prune_provider_data


async def main():
    try:
        async with get_db_context() as session:
            print(
                await prune_provider_data(
                    session, get_settings().CONTACT_RETENTION_DAYS
                )
            )
    finally:
        await close_db_engine()


if __name__ == "__main__":
    asyncio.run(main())
