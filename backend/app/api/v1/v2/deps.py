"""Shared FastAPI dependencies of the v2 control plane (defined ONCE here; tests override them via
``app.dependency_overrides`` using the same function objects re-exported by ``automation_v2``)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai_v2.runtime import AIRuntime
from backend.app.browser_v2.hitl import HITLResolutionService
from backend.app.browser_v2.schemas import WorkerControlRead
from backend.app.browser_v2.store import PostgresStore, Store, WorkerControl
from backend.app.db.session import get_db_session

__all__ = [
    "HEARTBEAT_STALE_SEC",
    "PLATFORM_PATTERN",
    "AIDep",
    "EnrichmentDep",
    "HITLDep",
    "MailDep",
    "SessionDep",
    "StoreDep",
    "get_ai_runtime",
    "get_enrichment_service",
    "get_hitl_service",
    "get_mail_service",
    "get_v2_store",
    "mail_config",
    "worker_read",
]

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
HEARTBEAT_STALE_SEC = 300


async def get_v2_store(session: SessionDep) -> AsyncIterator[Store]:
    """Borrow the pooled asyncpg connection (no extra Supabase connection)."""
    connection = await session.connection()
    if connection.dialect.name != "postgresql":
        raise HTTPException(503, "Python v2 store requires PostgreSQL")
    raw = await connection.get_raw_connection()
    try:
        store = await PostgresStore.borrowed(raw.driver_connection)
    except RuntimeError:
        raise HTTPException(503, "Python v2 tables are missing: apply migration 004") from None
    yield store


StoreDep = Annotated[Store, Depends(get_v2_store)]


async def get_ai_runtime(store: StoreDep) -> AIRuntime:
    """Cache + router over the same borrowed connection; the ONNX embedder is a process singleton."""
    return await AIRuntime.for_store(store)


AIDep = Annotated[AIRuntime, Depends(get_ai_runtime)]


def worker_read(control: WorkerControl, now: datetime | None = None) -> WorkerControlRead:
    now = now or datetime.now(UTC)
    age = (now - control.heartbeat_at).total_seconds() if control.heartbeat_at else None
    return WorkerControlRead(
        desired_state=control.desired_state.value, dry_run=control.dry_run,
        run_once_requested_at=control.run_once_requested_at, observed_state=control.observed_state,
        heartbeat_at=control.heartbeat_at, heartbeat_age_sec=age,
        stale=age is None or age > HEARTBEAT_STALE_SEC, current_platform=control.current_platform,
        last_cycle_at=control.last_cycle_at, last_error=control.last_error, revision=control.revision)


# --- Phase 4: HITL inbox + Telegram status ---------------------------------------------
PLATFORM_PATTERN = r"^[a-z][a-z0-9_]{1,39}$"


async def get_hitl_service(store: StoreDep, ai: AIDep) -> HITLResolutionService:
    return HITLResolutionService(store, ai.cache)


HITLDep = Annotated[HITLResolutionService, Depends(get_hitl_service)]


# --- Phase 5: quota fallback (Gmail drafts + enrichment). READ + DRAFT ONLY. -------------
def mail_config() -> Any:
    from backend.app.ai_v2.router import load_env
    from backend.app.mail_v2.config import MailConfig

    return MailConfig.from_env(load_env())


async def get_mail_service(store: StoreDep) -> Any:
    """MailDraftService over the borrowed connection (dependency: tests inject fake IMAP/Mail.app)."""
    from backend.app.mail_v2.service import MailDraftService

    return MailDraftService(store, mail_config())


async def get_enrichment_service(store: StoreDep) -> Any:
    from backend.app.enrichment_v2.service import EnrichmentService

    return await EnrichmentService.for_store(store)


MailDep = Annotated[Any, Depends(get_mail_service)]
EnrichmentDep = Annotated[Any, Depends(get_enrichment_service)]
