import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select
from backend.app.models.base import Base
from backend.app.models.discovery import DiscoveryMonthlyBudget, DiscoveryReservation
from backend.app.services.discovery_budget import DiscoveryBudget
from backend.app.schemas.discovery import DiscoveryError


@pytest_asyncio.fixture
async def budget_store(tmp_path):
    engine = create_async_engine("sqlite+aiosqlite:///" + str(tmp_path / "budget.db"))
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory, DiscoveryBudget(factory)
    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_atomic_reservations(budget_store):
    import asyncio

    factory, budget = budget_store

    async def reserve(i):
        try:
            await budget.reserve("apify", str(i), 0.1, 0.3)
            return "ok"
        except DiscoveryError as exc:
            return str(exc.status)

    statuses = await asyncio.gather(*(reserve(i) for i in range(12)))
    assert statuses.count("ok") == 3 and statuses.count("budget_exhausted") == 9
    async with factory() as session:
        assert (
            float(await session.scalar(select(DiscoveryMonthlyBudget.reserved))) == 0.3
        )


@pytest.mark.asyncio
async def test_idempotent_accounting_cooldown_and_uncertain_charges(budget_store):
    factory, budget = budget_store
    await budget.reserve("apify", "one", 0.1, 1)
    with pytest.raises(DiscoveryError):
        await budget.reserve("apify", "one", 0.1, 1)
    await budget.finish("one", "success", 0.02)
    await budget.finish("one", "success", 0.04)
    async with factory() as session:
        record = await session.get(DiscoveryReservation, "one")
        assert float(record.reported_actual) == 0.02
        assert (
            float(await session.scalar(select(DiscoveryMonthlyBudget.reserved))) == 0.1
        )
    await budget.cooldown("apify")
    with pytest.raises(DiscoveryError) as exc:
        await budget.reserve("apify", "two", 0.1, 1)
    assert exc.value.status == "rate_limited"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "amount,maximum",
    [(0, 1), (-1, 1), (1, 0), (2, 1), (float("nan"), 1), (1, float("inf"))],
)
async def test_invalid_budgets_fail_closed(budget_store, amount, maximum):
    _, budget = budget_store
    with pytest.raises(DiscoveryError):
        await budget.reserve("apify", "bad", amount, maximum)
