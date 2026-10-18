"""Atomic durable monthly caps. Reservations survive failed/cancelled draft transactions."""
import asyncio
from datetime import datetime, timezone, timedelta
import math
import weakref

from sqlalchemy import update, select, func, or_, and_, case
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend.app.ai.base import ProviderError
from backend.app.ai.schemas import ProviderAnswer
from pydantic import ValidationError
from backend.app.models.application_answer import LLMMonthlyUsage

_limiters = weakref.WeakKeyDictionary()


def concurrency_limiter(limit):
    loop = asyncio.get_running_loop()
    per_loop = _limiters.setdefault(loop, {})
    return per_loop.setdefault(limit, asyncio.Semaphore(limit))


class LLMUsageManager:
    def __init__(self, session_factory, settings):
        self.factory, self.settings = session_factory, settings

    async def check_cooldown(self, session):
        deadline = await session.scalar(select(func.max(LLMMonthlyUsage.cooldown_until)).where(
            LLMMonthlyUsage.provider == self.settings.LLM_PROVIDER))
        if deadline:
            deadline = deadline.replace(tzinfo=timezone.utc) if deadline.tzinfo is None else deadline
            remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
            if remaining > 0:
                raise ProviderError("rate_limited", retry_after=math.ceil(remaining))

    async def record_cooldown(self, month, error):
        delay = error.retry_after
        if error.code != "rate_limited" and not (error.transient and delay is not None and delay > 2):
            return
        if delay is None or not math.isfinite(delay):
            delay = 60  # Conservative pause when the provider gives no usable instruction.
        deadline = datetime.now(timezone.utc) + timedelta(seconds=min(max(0, delay), 31536000))
        async with self.factory() as session:
            await session.execute(update(LLMMonthlyUsage).where(
                LLMMonthlyUsage.provider == self.settings.LLM_PROVIDER, LLMMonthlyUsage.month == month
            ).values(cooldown_until=case(
                (or_(LLMMonthlyUsage.cooldown_until.is_(None), LLMMonthlyUsage.cooldown_until < deadline), deadline),
                else_=LLMMonthlyUsage.cooldown_until)))
            await session.commit()

    async def reserve(self):
        maximum = self.settings.LLM_MONTHLY_MAX_REQUESTS
        if maximum == 0:
            raise ProviderError("monthly_request_limit")
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        async with self.factory() as session:
            await self.check_cooldown(session)
            insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
            statement = insert(LLMMonthlyUsage).values(
                provider=self.settings.LLM_PROVIDER, month=month, requests=1,
                input_tokens=0, output_tokens=0,
            ).on_conflict_do_update(
                index_elements=[LLMMonthlyUsage.provider, LLMMonthlyUsage.month],
                set_={"requests": LLMMonthlyUsage.requests + 1, "updated_at": datetime.now(timezone.utc)},
                where=and_(LLMMonthlyUsage.requests < maximum,
                           or_(LLMMonthlyUsage.cooldown_until.is_(None),
                               LLMMonthlyUsage.cooldown_until <= datetime.now(timezone.utc))),
            ).returning(LLMMonthlyUsage.requests)
            accepted = (await session.execute(statement)).scalar_one_or_none()
            await session.commit()
            if accepted is None:
                await self.check_cooldown(session)
                raise ProviderError("monthly_request_limit")
        return month

    async def record_tokens(self, month, usage):
        if usage is None or (usage.input_tokens is None and usage.output_tokens is None):
            return
        async with self.factory() as session:
            await session.execute(update(LLMMonthlyUsage).where(
                LLMMonthlyUsage.provider == self.settings.LLM_PROVIDER, LLMMonthlyUsage.month == month
            ).values(input_tokens=LLMMonthlyUsage.input_tokens + (usage.input_tokens or 0),
                     output_tokens=LLMMonthlyUsage.output_tokens + (usage.output_tokens or 0)))
            await session.commit()

    async def generate(self, provider, question, context, instructions):
        attempts = 0
        try:
            # Includes queue time, retry delay, and provider time in a single request deadline.
            async with asyncio.timeout(self.settings.LLM_TIMEOUT_SECONDS):
                async with concurrency_limiter(self.settings.LLM_MAX_CONCURRENCY):
                    for attempt in range(2):
                        month = await self.reserve()
                        try:
                            attempts += 1
                            response = ProviderAnswer.model_validate(await provider.generate_structured_answer(question, context, instructions))
                        except ValidationError:
                            raise ProviderError("invalid_structured_response") from None
                        except ProviderError as exc:
                            await self.record_tokens(month, exc.usage)
                            await self.record_cooldown(month, exc)
                            # Do not retry 429; return Retry-After metadata without another paid call.
                            if attempt == 0 and exc.transient and (exc.retry_after is None or exc.retry_after <= 2):
                                await asyncio.sleep(max(0.2, exc.retry_after or 0))
                                continue
                            raise
                        await self.record_tokens(month, response.usage)
                        return response
        except ProviderError as exc:
            exc.attempted = attempts > 0
            raise
        except TimeoutError:
            error = ProviderError("timeout")
            error.attempted = attempts > 0
            raise error from None
