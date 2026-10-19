"""Database engine and async session management."""

import ssl
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

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Initialize or return the cached async SQLAlchemy engine."""
    global _engine
    if _engine is None:
        settings = get_settings()
        connect_args = {}
        
        # Dialect specific configuration
        if settings.DATABASE_URL.startswith("postgresql"):
            # Set search_path so unqualified queries or schema references work natively
            connect_args = {
                "server_settings": {
                    "search_path": f"{settings.DATABASE_SCHEMA},public"
                }
            }
            if settings.ENVIRONMENT in {"staging", "production"} and settings.DB_REQUIRE_TLS:
                connect_args["ssl"] = ssl.create_default_context()
            _engine = create_async_engine(
                settings.DATABASE_URL,
                echo=settings.DB_ECHO,
                hide_parameters=True,
                pool_pre_ping=True,
                pool_recycle=300,
                pool_size=settings.DB_POOL_SIZE,
                max_overflow=settings.DB_MAX_OVERFLOW,
                connect_args=connect_args,
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
    if _session_factory is None:
        engine = get_engine()
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
