"""Optional-provider budgets reuse protected owner storage; no schema/ACL changes.

Ollama has no paid usage; Cohere trial requests are reserved durably before transport.
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend.app.ai.base import ProviderError
from backend.app.ai.schemas import ProviderAnswer
from backend.app.ai.usage import concurrency_limiter
from backend.app.dashboard.models import OwnerPreference


class OptionalUsageManager:
    def __init__(self, factory, settings):
        self.factory, self.settings = factory, settings

    async def reserve(self):
        settings = self.settings
        if settings.LLM_MONTHLY_MAX_REQUESTS == 0:
            raise ProviderError("monthly_request_limit")
        key = (
            "ai:"
            + settings.LLM_PROVIDER
            + ":"
            + datetime.now(timezone.utc).strftime("%Y-%m")
        )
        async with self.factory() as session:
            insert = (
                pg_insert
                if session.get_bind().dialect.name == "postgresql"
                else sqlite_insert
            )
            await session.execute(
                insert(OwnerPreference)
                .values(key=key, value={"requests": 0, "cooldown": 0})
                .on_conflict_do_nothing()
            )
            row = await session.scalar(
                select(OwnerPreference)
                .where(OwnerPreference.key == key)
                .with_for_update()
            )
            if row.value.get("cooldown", 0) > datetime.now(timezone.utc).timestamp():
                raise ProviderError("rate_limited", retry_after=60)
            if row.value["requests"] >= min(settings.LLM_MONTHLY_MAX_REQUESTS, 1000):
                raise ProviderError("monthly_request_limit")
            row.value = {**row.value, "requests": row.value["requests"] + 1}
            await session.commit()
        return key

    async def generate(self, provider, question, context, instructions):
        key = None
        try:
            async with asyncio.timeout(self.settings.LLM_TIMEOUT_SECONDS):
                async with concurrency_limiter(self.settings.LLM_MAX_CONCURRENCY):
                    key = await self.reserve()
                    return ProviderAnswer.model_validate(
                        await provider.generate_structured_answer(
                            question, context, instructions
                        )
                    )
        except ProviderError as error:
            error.attempted = key is not None
            if key and error.code == "rate_limited":
                async with self.factory() as session:
                    row = await session.scalar(
                        select(OwnerPreference)
                        .where(OwnerPreference.key == key)
                        .with_for_update()
                    )
                    row.value = {
                        **row.value,
                        "cooldown": datetime.now(timezone.utc).timestamp() + 60,
                    }
                    await session.commit()
            raise
        except TimeoutError:
            error = ProviderError("timeout")
            error.attempted = key is not None
            raise error from None
