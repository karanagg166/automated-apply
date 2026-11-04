"""Exercise real PostgreSQL owner locks in an explicitly disposable loopback DB.

Reads only PROFILE_TEST_DATABASE_URL, never application configuration/secrets.
Creates one minimal table and a unique fictional key; leaves the test data intact.
No provider requests, application jobs or production fallback are involved.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import event, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.app.core.config import Settings, configure_operator


async def verify():
    raw = os.environ.get("PROFILE_TEST_DATABASE_URL", "")
    if not raw:
        raise ValueError("explicit_disposable_database_required")
    url = make_url(raw)
    if (url.host not in {"127.0.0.1", "localhost", "::1"}
            or not (url.database or "").endswith("_owner_lock_test")
            or url.drivername not in {"postgresql", "postgresql+asyncpg"}):
        raise ValueError("loopback_owner_lock_test_database_required")
    url = url.set(drivername="postgresql+asyncpg")
    configure_operator(Settings(_env_file=None, ENVIRONMENT="testing",
                                DATABASE_URL=url.render_as_string(hide_password=False),
                                DATABASE_SCHEMA="public", DB_REQUIRE_TLS=False,
                                DB_REMOTE_ONLY=False))
    from backend.app.agent import store
    from backend.app.dashboard.models import OwnerPreference

    store.MEMORY_KEY = "fixture_owner_lock:" + uuid4().hex[:16]
    engine = create_async_engine(url, hide_parameters=True, poolclass=NullPool,
                                 connect_args={"server_settings": {
                                     "application_name": "automated-apply:owner-lock-test",
                                     "lock_timeout": "2000ms", "statement_timeout": "5000ms",
                                 }})
    factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    statements = []

    def observed(connection, cursor, statement, parameters, context, executemany):
        if "owner_preferences" in statement:
            statements.append(statement.split(None, 1)[0])

    event.listen(engine.sync_engine, "before_cursor_execute", observed)
    started = time.monotonic()
    checks = []
    try:
        async with engine.begin() as connection:
            await connection.run_sync(lambda c: OwnerPreference.__table__.create(c, checkfirst=True))
        # Two cold requests must agree on one singleton, preserving its value.
        async with factory() as first, factory() as second:
            row = await store.memory_row(first, lock=True)
            row.value = {"marker": "fictional_lock_test"}
            pending = asyncio.create_task(store.memory_row(second, lock=True))
            await asyncio.sleep(.05)
            assert not pending.done(), "cold_initializer_did_not_serialize"
            await first.commit()
            other = await asyncio.wait_for(pending, 2)
            assert other.value == {"marker": "fictional_lock_test"}
            await second.rollback()
        checks.append("concurrent_cold_initialization_preserves_one_value")

        async with factory() as hot:
            statements.clear()
            row = await store.memory_row(hot, lock=True)
            assert row.value == {"marker": "fictional_lock_test"}
            assert statements == ["SELECT"], "existing_lock_issued_initialization_write"
            await store.memory_row(hot, lock=True)
            assert statements == ["SELECT"], "held_lock_not_reused"
            await hot.rollback()
        checks.append("existing_singleton_and_nested_guards_need_one_select")

        async with factory() as holder, factory() as waiter:
            await store.memory_row(holder, lock=True)
            statements.clear()
            assert await asyncio.wait_for(store.memory_row(waiter, lock=True, skip_locked=True), 1) is None
            assert "INSERT" not in statements, "skip_locked_attempted_initialization"
            pending = asyncio.create_task(store.memory_row(waiter, lock=True))
            await asyncio.sleep(.05)
            assert not pending.done(), "real_row_lock_was_bypassed"
            await holder.rollback()
            assert (await asyncio.wait_for(pending, 2)).value == {"marker": "fictional_lock_test"}
            await waiter.rollback()
        checks.append("skip_locked_yields_and_waiting_lock_resumes_after_release")

        async with factory() as outer, factory() as competitor:
            async with outer.begin_nested() as child:
                await store.memory_row(outer, lock=True)
                await child.rollback()
            await store.memory_row(competitor, lock=True)
            pending = asyncio.create_task(store.memory_row(outer, lock=True))
            await asyncio.sleep(.05)
            assert not pending.done(), "rolled_back_child_lock_was_reused"
            await competitor.rollback()
            await asyncio.wait_for(pending, 2)
            await outer.rollback()
        checks.append("rolled_back_savepoint_lock_requires_real_reacquisition")
        async with factory() as final:
            rows = (await final.scalars(select(OwnerPreference).where(
                OwnerPreference.key == store.MEMORY_KEY,
            ))).all()
            assert len(rows) == 1 and rows[0].value == {"marker": "fictional_lock_test"}
        return {"result": "PASS", "checks": checks, "groups": len(checks),
                "actual_postgresql": True, "fictional_data_only": True,
                "production_connections": 0, "provider_requests": 0,
                "seconds": round(time.monotonic() - started, 3)}
    finally:
        await engine.dispose()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(verify()), indent=2))
