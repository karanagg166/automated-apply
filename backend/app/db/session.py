"""Database engine and async session management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from backend.app.core.config import get_settings
from backend.app.core.logging import logger
from backend.app.core.timing import (
    TimedAsyncAdaptedQueuePool,
    instrument_engine,
    span,
    timed,
)
from backend.app.db.errors import DATABASE_ERRORS
from backend.app.db.safety import database_connect_args, database_target

# The Supabase runtime role allows 5 connections in total (SQLSTATE 53300 when
# exceeded). One process keeps at most 3, leaving room for the readiness probe,
# a migration/inspection client and the owner's psql session.
POOL_SIZE_CAP = 2
MAX_OVERFLOW_CAP = 1

_engine: AsyncEngine | None = None
_readiness_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


class TimedSession(AsyncSession):
    @timed("flush")
    async def flush(self, objects=None):
        return await super().flush(objects)

    @timed("commit")
    async def commit(self):
        return await super().commit()

    @timed("rollback")
    async def rollback(self):
        return await super().rollback()


def pool_limits(settings) -> tuple[int, int]:
    """Clamp configured pool sizes to the Supabase role connection budget."""
    pool_size = min(settings.DB_POOL_SIZE, POOL_SIZE_CAP)
    max_overflow = min(settings.DB_MAX_OVERFLOW, MAX_OVERFLOW_CAP)
    if (pool_size, max_overflow) != (settings.DB_POOL_SIZE, settings.DB_MAX_OVERFLOW):
        logger.warning(
            "Database pool clamped to pool_size=%s max_overflow=%s (role connection limit 5)",
            pool_size, max_overflow,
        )
    return pool_size, max_overflow


def get_engine() -> AsyncEngine:
    """Initialize or return the cached async SQLAlchemy engine."""
    global _engine
    settings = get_settings()
    target = database_target(settings)
    if _engine is not None and _engine.url != target:
        from backend.app.db.safety import DatabaseConfigurationError

        raise DatabaseConfigurationError("database_target_changed_restart_required")
    if _engine is None:
        if target.drivername == "postgresql+asyncpg":
            pool_size, max_overflow = pool_limits(settings)
            _engine = create_async_engine(
                settings.DATABASE_URL,
                echo=settings.DB_ECHO,
                hide_parameters=True,
                pool_pre_ping=True,
                pool_recycle=300,
                poolclass=TimedAsyncAdaptedQueuePool,
                pool_size=pool_size,
                max_overflow=max_overflow,
                connect_args=database_connect_args(settings),
                # Keep a small connection budget without failing queued
                # dashboard reads during a full remote catalog audit.
                pool_timeout=30,
            )
        else:
            # SQLite / In-memory for testing
            _engine = create_async_engine(
                settings.DATABASE_URL,
                echo=settings.DB_ECHO,
                hide_parameters=True,
            )
        instrument_engine(_engine)
        logger.info(f"Database engine initialized for schema: {settings.DATABASE_SCHEMA}")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Initialize or return the cached async session factory."""
    global _session_factory
    engine = get_engine()
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=engine,
            class_=TimedSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


def get_readiness_engine() -> AsyncEngine:
    """Use one in-flight API probe without retaining an idle database session.

    The readiness route coalesces simultaneous callers. NullPool returns its
    transient slot on completion, leaving capacity for recovery and operators.
    Business transactions retain their own bounded pools; probes never queue
    behind them. Workers never call this accessor.
    """
    global _readiness_engine
    settings = get_settings()
    target = database_target(settings)
    # Retain the startup engine's pin even before the first probe connection.
    normal = get_engine()
    if target.drivername != "postgresql+asyncpg":
        return normal
    if _readiness_engine is not None and _readiness_engine.url != target:
        from backend.app.db.safety import DatabaseConfigurationError

        raise DatabaseConfigurationError("database_target_changed_restart_required")
    if _readiness_engine is None:
        arguments = database_connect_args(settings)
        arguments["server_settings"]["application_name"] = "automated-apply:readiness"
        _readiness_engine = create_async_engine(
            settings.DATABASE_URL, hide_parameters=True, poolclass=NullPool,
            connect_args=arguments,
        )
    return _readiness_engine


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for obtaining an isolated async database session."""
    with span("session_creation"):
        factory = get_session_factory()
        session = factory()
    async with session:
        try:
            yield session
            with span("flush_commit"):
                await session.commit()
        except DATABASE_ERRORS as exc:
            await session.rollback()
            # Only PostgreSQL's explicit transaction-abort codes establish a
            # retryable rollback. Connection loss and commit timeouts remain
            # ambiguous; never label those safe to replay.
            original = getattr(exc, "orig", exc)
            sqlstate = getattr(original, "sqlstate", None)
            retryable = sqlstate in {"55P03", "40P01", "40001"}
            from backend.app.db.errors import database_failure_code

            logger.warning("Database transaction rejected; category=%s retry_safe=%s",
                           database_failure_code(exc), retryable)
            raise HTTPException(
                503, "Database storage unavailable",
                headers={"X-Automated-Apply-Transaction": "rolled-back"}
                if retryable else None,
            ) from exc
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for standalone services, scripts, and background workers."""
    factory = get_session_factory()
    if get_settings().ENVIRONMENT != "testing":
        from backend.app.operations.health import database_health

        await database_health(get_engine(), get_settings())
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_db_engine() -> None:
    """Gracefully dispose of database engine connection pool upon shutdown."""
    global _engine, _readiness_engine, _session_factory
    if _readiness_engine is not None:
        await _readiness_engine.dispose()
        _readiness_engine = None
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database connection pool closed.")
