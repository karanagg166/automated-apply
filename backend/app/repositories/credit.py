"""Repository for API Key Pool and Credit Budget accounting."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.credit import ApiKeyPool, ProviderUsageLog
from backend.app.repositories.base import BaseRepository


class CreditRepository(BaseRepository[ApiKeyPool]):
    """Data access repository for API keys and credit tracking."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(ApiKeyPool, session)

    async def get_active_key(self, provider: str) -> ApiKeyPool | None:
        """Retrieve an active, non-cooled-down API key with remaining credits for a provider."""
        cleaned_provider = provider.strip().lower()
        now = datetime.now(timezone.utc)
        stmt = (
            select(ApiKeyPool)
            .where(
                ApiKeyPool.provider == cleaned_provider,
                ApiKeyPool.is_active == True,
                ApiKeyPool.credits_remaining > 0,
            )
            .order_by(ApiKeyPool.credits_remaining.desc())
        )
        result = await self.session.execute(stmt)
        keys = result.scalars().all()

        for key in keys:
            # Check cooldown status
            if key.cooldown_until:
                # Ensure timezone-aware comparison
                cooldown_time = key.cooldown_until
                if cooldown_time.tzinfo is None:
                    cooldown_time = cooldown_time.replace(tzinfo=timezone.utc)
                if cooldown_time > now:
                    continue
            return key
        return None

    async def record_usage(
        self,
        provider: str,
        credits_consumed: int,
        endpoint: str | None = None,
        status_code: int | None = None,
        is_success: bool = True,
        error_message: str | None = None,
        key_id: UUID | None = None,
    ) -> ProviderUsageLog:
        """Deduct credits from key (with floor at 0) and record audit log."""
        cleaned_provider = provider.strip().lower()

        # Deduct from key if specified
        if key_id and credits_consumed > 0:
            stmt = (
                update(ApiKeyPool)
                .where(ApiKeyPool.id == key_id)
                .values(
                    credits_remaining=ApiKeyPool.credits_remaining - credits_consumed,
                    last_used_at=datetime.now(timezone.utc),
                )
            )
            await self.session.execute(stmt)

        # Create usage audit log
        log_entry = ProviderUsageLog(
            provider=cleaned_provider,
            endpoint=endpoint,
            credits_consumed=credits_consumed,
            status_code=status_code,
            is_success=is_success,
            error_message=error_message,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(log_entry)
        await self.session.flush()
        return log_entry

    async def mark_provider_unavailable(
        self,
        key_id: UUID,
        error_code: int,
        cooldown_seconds: int = 300,
    ) -> None:
        """Place key in temporary cooldown upon 429 rate limit or error."""
        cooldown_time = datetime.now(timezone.utc) + timedelta(seconds=cooldown_seconds)
        stmt = (
            update(ApiKeyPool)
            .where(ApiKeyPool.id == key_id)
            .values(
                cooldown_until=cooldown_time,
                last_error_code=error_code,
                # If 401/403 authentication failure, deactivate key permanently until user reviews
                is_active=False if error_code in (401, 403) else ApiKeyPool.is_active,
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def get_all_provider_keys(self) -> list[ApiKeyPool]:
        """Fetch all configured API keys for budget status reporting."""
        stmt = select(ApiKeyPool).order_by(ApiKeyPool.provider, ApiKeyPool.account_label)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
