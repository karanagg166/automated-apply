"""Tests for credit budget manager, negative cache, and cooldown behavior."""

from datetime import datetime, timezone, timedelta
import pytest
from backend.app.models.credit import ApiKeyPool
from backend.app.services.credit_manager import CreditManager, CreditBudgetExhaustedError


@pytest.mark.asyncio
async def test_credit_manager_active_key_and_deduction(db_session):
    manager = CreditManager(db_session)

    # Seed an active API key
    key = ApiKeyPool(
        provider="hunter",
        account_label="primary",
        secret_reference="env:HUNTER_API_KEY",
        credits_remaining=10,
        monthly_limit=25,
        is_active=True,
    )
    db_session.add(key)
    await db_session.commit()

    # Retrieve key
    active_key = await manager.get_active_key("hunter", estimated_cost=1)
    assert active_key.id == key.id
    assert active_key.credits_remaining == 10

    # Record usage
    await manager.record_usage(
        provider="hunter",
        credits_consumed=2,
        endpoint="/v2/email-finder",
        status_code=200,
        is_success=True,
        key=active_key,
    )
    await db_session.commit()

    # Verify updated balance
    refreshed_key = await manager.get_active_key("hunter", estimated_cost=1)
    assert refreshed_key.credits_remaining == 8


@pytest.mark.asyncio
async def test_credit_budget_exhaustion(db_session):
    manager = CreditManager(db_session)

    # Seed a key with 0 credits
    key = ApiKeyPool(
        provider="apollo",
        account_label="free_tier",
        secret_reference="env:APOLLO_API_KEY",
        credits_remaining=0,
        monthly_limit=50,
        is_active=True,
    )
    db_session.add(key)
    await db_session.commit()

    with pytest.raises(CreditBudgetExhaustedError):
        await manager.get_active_key("apollo", estimated_cost=1)


@pytest.mark.asyncio
async def test_negative_cache_and_ttl():
    provider = "hunter"
    query = "nonexistent_person_stripe.com"

    # Initially not in cache
    assert not CreditManager.check_negative_cache(provider, query)

    # Record negative result with 60s TTL
    CreditManager.record_negative_cache(provider, query, ttl_seconds=60)
    assert CreditManager.check_negative_cache(provider, query)

    # Expired negative cache
    CreditManager.record_negative_cache(provider, query, ttl_seconds=-1)
    assert not CreditManager.check_negative_cache(provider, query)


@pytest.mark.asyncio
async def test_provider_error_and_cooldown(db_session):
    manager = CreditManager(db_session)

    key = ApiKeyPool(
        provider="serper",
        account_label="dev_account",
        secret_reference="env:SERPER_API_KEY",
        credits_remaining=50,
        monthly_limit=100,
        is_active=True,
    )
    db_session.add(key)
    await db_session.commit()

    # Simulate 429 rate limit
    await manager.handle_provider_error(
        provider="serper",
        key=key,
        status_code=429,
        retry_after=600,
    )
    await db_session.commit()

    # Key should now be in cooldown and thus unavailable
    with pytest.raises(CreditBudgetExhaustedError):
        await manager.get_active_key("serper", estimated_cost=1)
