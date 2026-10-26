"""Database engine and async session management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.app.core.config import get_settings
from backend.app.core.logging import logger
from backend.app.db.safety import database_connect_args, database_target

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Initialize or return the cached async SQLAlchemy engine."""
    global _engine
    settings = get_settings()
    target = database_target(settings)
    if _engine is not None and _engine.url != target:
        from backend.app.db.safety import DatabaseConfigurationError

        raise DatabaseConfigurationError("database_target_changed_restart_required")
    if _engine is None:
        
        # Dialect specific configuration
        if target.drivername == "postgresql+asyncpg":
            _engine = create_async_engine(
                settings.DATABASE_URL,
                echo=settings.DB_ECHO,
                hide_parameters=True,
                pool_pre_ping=True,
                pool_recycle=300,
                pool_size=settings.DB_POOL_SIZE,
                max_overflow=settings.DB_MAX_OVERFLOW,
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
        logger.info(f"Database engine initialized for schema: {settings.DATABASE_SCHEMA}")
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Initialize or return the cached async session factory."""
    global _session_factory
    engine = get_engine()
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for obtaining an isolated async database session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
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
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database connection pool closed.")
