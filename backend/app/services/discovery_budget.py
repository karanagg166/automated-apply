"""Independent durable reservations, following the Phase 2A usage-manager pattern.

Reserve the entire run cap, even on timeout/cancellation. Never release uncertain costs.
Reported actuals are audit data; preliminary billing cannot weaken the safety reservation.
"""

from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend.app.models.discovery import (
    DiscoveryMonthlyBudget as Budget,
)
from backend.app.models.discovery import (
    DiscoveryReservation as Reservation,
)
from backend.app.models.discovery import (
    DiscoveryRun,
)
from backend.app.schemas.discovery import DiscoveryError
from backend.app.schemas.discovery import DiscoveryStatus as Status


def insert_for(session):
    return (
        pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    )


class DiscoveryBudget:
    def __init__(self, factory):
        self.factory = factory

    async def reserve(self, provider, reservation_id, amount, monthly_limit):
        amount, maximum = Decimal(str(amount)), Decimal(str(monthly_limit))
        if (
            not amount.is_finite()
            or not maximum.is_finite()
            or amount <= 0
            or maximum < amount
        ):
            raise DiscoveryError(
                Status.BUDGET_EXHAUSTED, "Positive bounded provider budget required"
            )
        amount = amount.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
        maximum = maximum.quantize(Decimal("0.000001"), rounding=ROUND_FLOOR)
        if amount > maximum:
            raise DiscoveryError(
                Status.BUDGET_EXHAUSTED, "Budget below accounting precision"
            )
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        now = datetime.now(timezone.utc)
        async with self.factory() as session:
            # A repeated reservation never authorizes a repeated remote execution.
            claimed = (
                await session.execute(
                    insert_for(session)(Reservation)
                    .values(
                        id=reservation_id,
                        provider=provider,
                        month=month,
                        reserved=amount,
                        state="reserved",
                    )
                    .on_conflict_do_nothing()
                    .returning(Reservation.id)
                )
            ).scalar_one_or_none()
            if claimed is None:
                raise DiscoveryError(
                    Status.UNSUPPORTED,
                    "Reservation already used; retrieve the existing run",
                )
            statement = (
                insert_for(session)(Budget)
                .values(provider=provider, month=month, reserved=amount)
                .on_conflict_do_update(
                    index_elements=[Budget.provider, Budget.month],
                    set_={"reserved": func.round(Budget.reserved + amount, 6)},
                    where=and_(
                        func.round(Budget.reserved + amount, 6) <= maximum,
                        or_(
                            Budget.cooldown_until.is_(None),
                            Budget.cooldown_until <= now,
                        ),
                    ),
                )
                .returning(Budget.reserved)
            )
            accepted = (await session.execute(statement)).scalar_one_or_none()
            if accepted is None:
                cooldown = await session.scalar(
                    select(Budget.cooldown_until).where(
                        Budget.provider == provider, Budget.month == month
                    )
                )
                raise DiscoveryError(
                    Status.RATE_LIMITED
                    if cooldown
                    and (
                        cooldown.replace(tzinfo=timezone.utc)
                        if cooldown.tzinfo is None
                        else cooldown
                    )
                    > now
                    else Status.BUDGET_EXHAUSTED,
                    "Provider cooling down or monthly budget exhausted",
                )
            await session.commit()
        return month

    async def attach_run(self, reservation_id, provider_run_id):
        from uuid import UUID

        async with self.factory() as session:
            reservation = await session.get(Reservation, reservation_id)
            if reservation is None:
                raise DiscoveryError(
                    Status.BUDGET_EXHAUSTED, "No durable provider reservation"
                )
            reservation.provider_run_id = provider_run_id
            try:
                run_id = UUID(reservation_id)
            except ValueError:
                run_id = None
            if run_id:
                await session.execute(
                    update(DiscoveryRun)
                    .where(DiscoveryRun.id == run_id)
                    .values(
                        provider_run_id=provider_run_id,
                        usage={
                            "reserved_usd": float(reservation.reserved),
                            "accounting": "full_cap_retained",
                            "billing_final": False,
                        },
                    )
                )
            await session.commit()

    async def finish(self, reservation_id, state, reported_actual=None):
        async with self.factory() as session:
            values = {"state": state}
            if reported_actual is not None:
                number = Decimal(str(reported_actual))
                if number.is_finite() and number >= 0:
                    values["reported_actual"] = number
            await session.execute(
                update(Reservation)
                .where(
                    Reservation.id == reservation_id, Reservation.state == "reserved"
                )
                .values(**values)
            )
            await session.commit()

    async def cooldown(self, provider, seconds=60):
        now = datetime.now(timezone.utc)
        deadline = now + timedelta(seconds=min(max(seconds, 1), 86400))
        async with self.factory() as session:
            await session.execute(
                update(Budget)
                .where(Budget.provider == provider)
                .values(
                    cooldown_until=case(
                        (
                            or_(
                                Budget.cooldown_until.is_(None),
                                Budget.cooldown_until < deadline,
                            ),
                            deadline,
                        ),
                        else_=Budget.cooldown_until,
                    )
                )
            )
            await session.commit()
