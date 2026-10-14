"""API Credit and Budget Management Service."""

import time
from datetime import datetime, timezone
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.core.config import get_settings
from backend.app.core.logging import logger
from backend.app.models.credit import ApiKeyPool
from backend.app.repositories.credit import CreditRepository
from backend.app.schemas.credit import CreditBudgetStatus, ProviderBudgetSummary


class CreditBudgetExhaustedError(Exception):
    """Raised when an API provider has zero remaining credits or has exceeded budget."""
    pass


class CreditManager:
    """Manages API credits, enforces provider budgets, and caches negative lookups."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = CreditRepository(session)
        self.settings = get_settings()

    # Negative lookup cache shared across instances: (provider, query_key) -> expiration_epoch
    _negative_cache: dict[str, float] = {}

    @classmethod
    def check_negative_cache(cls, provider: str, query_key: str) -> bool:
        """Check if a query was recently confirmed to have no result."""
        cache_key = f"{provider.lower()}:{query_key.lower()}"
        expiry = cls._negative_cache.get(cache_key)
        if expiry and expiry > time.time():
            logger.info(f"Negative cache hit for {cache_key} - skipping external lookup to conserve credits.")
            return True
        return False

    @classmethod
    def record_negative_cache(cls, provider: str, query_key: str, ttl_seconds: int = 86400) -> None:
        """Store a negative lookup result to avoid repeated failed queries."""
        cache_key = f"{provider.lower()}:{query_key.lower()}"
        cls._negative_cache[cache_key] = time.time() + ttl_seconds

    async def get_active_key(self, provider: str, estimated_cost: int = 1) -> ApiKeyPool:
        """Retrieve an active key with sufficient credits.
        Raises CreditBudgetExhaustedError if quota is depleted or key is unavailable.
        """
        key = await self.repository.get_active_key(provider)
        if not key or key.credits_remaining < estimated_cost:
            raise CreditBudgetExhaustedError(
                f"Credit budget exhausted or provider '{provider}' is unavailable / cooling down."
            )
        return key

    async def record_usage(
        self,
        provider: str,
        credits_consumed: int,
        endpoint: str | None = None,
        status_code: int | None = None,
        is_success: bool = True,
        error_message: str | None = None,
        key: ApiKeyPool | None = None,
    ) -> None:
        """Record credit expenditure and create an audit log entry."""
        key_id = key.id if key else None
        await self.repository.record_usage(
            provider=provider,
            credits_consumed=credits_consumed,
            endpoint=endpoint,
            status_code=status_code,
            is_success=is_success,
            error_message=error_message,
            key_id=key_id,
        )
        logger.info(
            f"API Provider '{provider}' used {credits_consumed} credits. Success: {is_success}. Code: {status_code}"
        )

    async def handle_provider_error(
        self,
        provider: str,
        key: ApiKeyPool,
        status_code: int,
        retry_after: int = 300,
    ) -> None:
        """Handle HTTP errors such as 429 (rate-limit) or 401/403 (auth failure)."""
        logger.warning(
            f"Provider '{provider}' returned HTTP error {status_code}. Setting cooldown {retry_after}s."
        )
        await self.repository.mark_provider_unavailable(
            key_id=key.id,
            error_code=status_code,
            cooldown_seconds=retry_after,
        )

    async def get_credit_status(self) -> CreditBudgetStatus:
        """Generate comprehensive budget status across all providers."""
        keys = await self.repository.get_all_provider_keys()
        now = datetime.now(timezone.utc)
        summaries: list[ProviderBudgetSummary] = []
        total_credits = 0

        for k in keys:
            in_cooldown = False
            if k.cooldown_until:
                cooldown_time = k.cooldown_until
                if cooldown_time.tzinfo is None:
                    cooldown_time = cooldown_time.replace(tzinfo=timezone.utc)
                in_cooldown = cooldown_time > now

            summaries.append(
                ProviderBudgetSummary(
                    provider=k.provider,
                    is_active=k.is_active,
                    credits_remaining=k.credits_remaining,
                    monthly_limit=k.monthly_limit,
                    reset_at=k.reset_at,
                    in_cooldown=in_cooldown,
                    cooldown_until=k.cooldown_until,
                )
            )
            if k.is_active and not in_cooldown:
                total_credits += k.credits_remaining

        return CreditBudgetStatus(
            timestamp=datetime.now(timezone.utc),
            providers=summaries,
            total_credits_remaining=total_credits,
        )
