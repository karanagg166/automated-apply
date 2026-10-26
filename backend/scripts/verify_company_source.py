"""Disposable PG17 + actual TCP API/Chromium public source through mock receipt."""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.scripts.browser_mock_demo import run

if __name__ == "__main__":
    asyncio.run(run(os.environ["PROFILE_TEST_DATABASE_URL"], company_source_demo=True))
