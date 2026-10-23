"""Explicit local-model acceptance with fictional facts and a disposable PG17 child.

The operator installs/pulls a local model separately. This command never installs,
signs in, enables cloud inference, loads private environment files or submits forms.
It is intentionally outside automated CI, which keeps deterministic injected models.
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def main(model):
    from backend.app.ai.providers.optional import OptionalProvider
    from backend.app.core.config import Settings
    from backend.scripts.browser_mock_demo import run

    started = time.monotonic()
    settings = Settings(
        _env_file=None, LLM_PROVIDER="ollama", OLLAMA_ENABLED=True, OLLAMA_MODEL=model
    )
    async with httpx.AsyncClient(
        timeout=10, trust_env=False, follow_redirects=False
    ) as client:
        await OptionalProvider(settings)._local_metadata(client)
    await run(
        os.environ["PROFILE_TEST_DATABASE_URL"],
        opportunity_demo=True,
        live_ollama_model=model,
    )
    print(
        f"Live local acceptance elapsed seconds: {time.monotonic() - started:.1f}",
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    asyncio.run(main(args.model))
