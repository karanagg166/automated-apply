"""Postgres row mappers, the serialized connection proxy and the PostgresStore base."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any, Self

from backend.app.browser_v2.state import ApplicationState
from backend.app.browser_v2.store.records import (
    ApplicationRecord,
    EmailDraftRecord,
    HitlRecord,
)

logger = logging.getLogger(__name__)


def _broken_connection_errors() -> tuple[type[BaseException], ...]:
    errors: list[type[BaseException]] = [TimeoutError, ConnectionError, OSError]
    try:
        import asyncpg

        errors += [asyncpg.exceptions.ConnectionDoesNotExistError, asyncpg.exceptions.InterfaceError]
    except ImportError:  # pragma: no cover - asyncpg ships with the backend
        pass
    return tuple(errors)


_BROKEN_CONNECTION_ERRORS = _broken_connection_errors()


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _hitl(row: Any) -> HitlRecord:
    data = dict(row)
    context = _json(data.get("context")) or {}
    return HitlRecord(
        id=str(data["id"]), platform=data["platform"], kind=data["kind"], prompt_text=data["prompt_text"],
        status=data["status"], application_id=str(data["application_id"]) if data.get("application_id") else None,
        context=context if isinstance(context, dict) else {}, telegram_msg_id=data.get("telegram_msg_id"),
        answer_text=data.get("answer_text"), created_at=data.get("created_at"),
        resolved_at=data.get("resolved_at"), resolved_via=data.get("resolved_via"),
        consumed_at=data.get("consumed_at"), company_name=data.get("company_name"),
        role_title=data.get("role_title"), job_url=data.get("job_url"),
        application_state=data.get("application_state"),
        telegram_card_closed_at=data.get("telegram_card_closed_at"))


def _uuid(value: str | None) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        return None


class SerializedConnection:
    """One asyncpg connection shared by concurrent tasks (worker loop + Telegram poller).

    asyncpg allows one in-flight operation per connection; this proxy runs one
    query or one whole transaction at a time. Re-entrant for the task that holds
    it, so statements inside `async with transaction()` do not deadlock.
    """

    def __init__(self, connection: Any, reconnect: Callable[[], Awaitable[Any]] | None = None) -> None:
        self._connection = connection
        self._reconnect = reconnect
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None
        self.reconnects = 0

    def _is_closed(self) -> bool:
        probe = getattr(self._connection, "is_closed", None)
        try:
            return bool(probe()) if callable(probe) else False
        except Exception:  # noqa: BLE001 - an unreadable connection is a dead one
            return True

    async def _ensure_open(self) -> None:
        """Replace a dead connection (laptop sleep, network drop, Supabase restart).

        Runs before a query is sent, so nothing is ever executed twice. A failed
        reconnect raises; the caller's cycle fails and the next one tries again.
        """
        if self._reconnect is None or not self._is_closed():
            return
        fresh = await self._reconnect()
        self._connection = fresh
        self.reconnects += 1
        logger.warning("postgres connection was closed; reconnected (count=%d)", self.reconnects)

    def _drop_if_broken(self, exc: BaseException) -> None:
        """A timed-out / reset socket can still report open: terminate it so the next call reconnects."""
        if self._reconnect is None or not isinstance(exc, _BROKEN_CONNECTION_ERRORS):
            return
        terminate = getattr(self._connection, "terminate", None)
        if callable(terminate):
            try:
                terminate()
            except Exception:
                logger.debug("terminate of a broken connection failed", exc_info=True)

    @asynccontextmanager
    async def _hold(self) -> AsyncIterator[None]:
        task = asyncio.current_task()
        if task is not None and self._owner is task:
            yield
            return
        async with self._lock:
            self._owner = task
            try:
                await self._ensure_open()
                try:
                    yield
                except BaseException as exc:
                    self._drop_if_broken(exc)
                    raise
            finally:
                self._owner = None

    async def fetch(self, *args: Any, **kwargs: Any) -> Any:
        async with self._hold():
            return await self._connection.fetch(*args, **kwargs)

    async def fetchrow(self, *args: Any, **kwargs: Any) -> Any:
        async with self._hold():
            return await self._connection.fetchrow(*args, **kwargs)

    async def fetchval(self, *args: Any, **kwargs: Any) -> Any:
        async with self._hold():
            return await self._connection.fetchval(*args, **kwargs)

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        async with self._hold():
            return await self._connection.execute(*args, **kwargs)

    async def executemany(self, *args: Any, **kwargs: Any) -> Any:
        async with self._hold():
            return await self._connection.executemany(*args, **kwargs)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        async with self._hold(), self._connection.transaction():
            yield

    async def close(self) -> None:
        await self._connection.close()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


def _record(row: Any) -> ApplicationRecord:
    data = dict(row)
    return ApplicationRecord(
        id=str(data["id"]), platform=data["platform"], external_job_id=data["external_job_id"],
        state=ApplicationState(data["state"]), version=data["version"], attempts=data["attempts"],
        reason=data["reason"], receipt=_json(data.get("receipt")),
        company_name=data.get("company_name"), role_title=data.get("role_title"),
        job_url=data.get("job_url"), dedup_key=data.get("dedup_key"),
        applied_at=data.get("applied_at"), retry_after=data.get("retry_after"),
        created_at=data.get("created_at"), updated_at=data.get("updated_at"),
        draft_created_at=data.get("draft_created_at"),
        priority=int(data["priority"]) if data.get("priority") is not None else 2,
        posted_at=data.get("posted_at"), posted_precision=data.get("posted_precision"),
        priority_reason=data.get("priority_reason"), discovered_via=data.get("discovered_via"))


def _draft(row: Any) -> EmailDraftRecord:
    data = dict(row)
    known = set(EmailDraftRecord.__dataclass_fields__)
    values = {k: v for k, v in data.items() if k in known}
    values["id"] = str(values["id"])
    values["application_id"] = str(values["application_id"]) if values.get("application_id") else None
    return EmailDraftRecord(**values)


class PostgresBase:
    """Connection state and shared SQL fragments for the PostgresStore repository mixins."""

    COLUMNS = ("id, platform, external_job_id, state, version, attempts, reason, receipt, "
               "company_name, role_title, job_url, dedup_key, applied_at, retry_after, "
               "created_at, updated_at, draft_created_at, "
               "priority, posted_at, posted_precision, priority_reason, discovered_via")

    def __init__(self, connection: Any, *, owns_connection: bool = True) -> None:
        self.connection = connection
        self.owns_connection = owns_connection

    HITL_SELECT = ("SELECT h.id, h.application_id, h.platform, h.kind, h.prompt_text, h.context::text AS context, "
                   "h.telegram_msg_id, h.status, h.answer_text, h.created_at, h.resolved_at, h.resolved_via, "
                   "h.consumed_at, a.company_name, a.role_title, a.job_url, a.state AS application_state "
                   "FROM public.hitl_requests h LEFT JOIN public.applications a ON a.id = h.application_id")

    DRAFT_SELECT = ("SELECT d.id, d.application_id, d.platform, d.recipient_email, d.subject, d.body_preview, "
                    "d.channel, d.status, d.composer, d.enrichment_source, d.external_draft_id, d.last_error, "
                    "d.created_at, d.updated_at, a.company_name, a.role_title, a.state AS application_state, "
                    "a.retry_after FROM public.email_drafts d "
                    "LEFT JOIN public.applications a ON a.id = d.application_id")

    @staticmethod
    async def schema_ready(connection: Any) -> bool:
        return bool(await connection.fetchval(
            "SELECT to_regclass('public.applications') IS NOT NULL "
            "AND to_regclass('public.portal_rules') IS NOT NULL "
            "AND to_regclass('public.worker_control') IS NOT NULL"))

    @classmethod
    async def connect(cls, settings: Any) -> Self:
        import asyncpg

        from backend.app.db.safety import database_connect_args

        url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)

        async def open_connection() -> Any:
            return await asyncpg.connect(url, **database_connect_args(settings))

        connection = await open_connection()
        if not await cls.schema_ready(connection):
            await connection.close()
            raise RuntimeError("v2_schema_missing: run backend.scripts.migrate_v2_core apply first")
        return cls(SerializedConnection(connection, reconnect=open_connection))

    @classmethod
    async def borrowed(cls, connection: Any) -> Self:
        """Wrap an asyncpg connection owned by the SQLAlchemy pool (never closed here)."""
        if not await cls.schema_ready(connection):
            raise RuntimeError("v2_schema_missing")
        return cls(connection, owns_connection=False)

    async def close(self) -> None:
        if self.owns_connection:
            await self.connection.close()
