"""public.enrichment_cache + public.enrichment_credits, with an in-memory twin for tests.

Postgres uses the worker's single (serialized) asyncpg connection. Credits are
reserved atomically BEFORE a provider call (`used < limit_cap` in the same UPDATE),
so two concurrent callers can never overspend a daily free allowance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Protocol

CACHE_STATUSES = ("FOUND", "NO_EMAIL_FOUND")


@dataclass
class CacheEntry:
    company_domain: str
    status: str
    emails: list[dict[str, Any]] = field(default_factory=list)
    source: str | None = None
    role_family: str | None = None
    expires_at: datetime | None = None
    updated_at: datetime | None = None

    def valid(self, now: datetime) -> bool:
        return self.expires_at is None or self.expires_at > now


@dataclass
class CreditRow:
    provider: str
    period_key: str
    used: int = 0
    limit_cap: int = 0
    cooldown_until: datetime | None = None
    last_error: str | None = None


class EnrichmentStore(Protocol):
    backend: str

    async def get_cache(self, key: str) -> CacheEntry | None: ...

    async def put_cache(self, key: str, *, status: str, emails: list[dict[str, Any]], source: str | None,
                        expires_at: datetime, role_family: str | None = None) -> None: ...

    async def credit(self, provider: str, period_key: str) -> CreditRow | None: ...

    async def reserve_credit(self, provider: str, period_key: str, cap: int) -> bool: ...

    async def set_cooldown(self, provider: str, period_key: str, cap: int, until: datetime | None,
                           error: str | None) -> None: ...

    async def cooldown_until(self, provider: str) -> datetime | None: ...

    async def cached_domains(self, now: datetime) -> int: ...


def _check_status(status: str) -> None:
    if status not in CACHE_STATUSES:
        raise ValueError("invalid enrichment cache status")


class MemoryEnrichmentStore:
    backend = "memory"

    def __init__(self) -> None:
        self.cache: dict[str, CacheEntry] = {}
        self.credits: dict[tuple[str, str], CreditRow] = {}

    async def get_cache(self, key):
        entry = self.cache.get(key)
        return replace(entry, emails=list(entry.emails)) if entry else None

    async def put_cache(self, key, *, status, emails, source, expires_at, role_family=None):
        _check_status(status)
        self.cache[key] = CacheEntry(company_domain=key, status=status, emails=list(emails), source=source,
                                     role_family=role_family, expires_at=expires_at, updated_at=None)

    async def credit(self, provider, period_key):
        row = self.credits.get((provider, period_key))
        return replace(row) if row else None

    async def reserve_credit(self, provider, period_key, cap):
        if cap <= 0:
            return False
        row = self.credits.setdefault((provider, period_key), CreditRow(provider, period_key, 0, cap))
        row.limit_cap = cap
        if row.used >= cap:
            return False
        row.used += 1
        return True

    async def set_cooldown(self, provider, period_key, cap, until, error):
        row = self.credits.setdefault((provider, period_key), CreditRow(provider, period_key, 0, cap))
        row.cooldown_until, row.last_error = until, (error or None) and str(error)[:200]

    async def cooldown_until(self, provider):
        values = [r.cooldown_until for (p, _), r in self.credits.items() if p == provider and r.cooldown_until]
        return max(values) if values else None

    async def cached_domains(self, now):
        return sum(1 for entry in self.cache.values() if entry.valid(now))


class PostgresEnrichmentStore:
    backend = "postgres"

    def __init__(self, connection: Any) -> None:
        self.connection = connection

    @staticmethod
    async def ready(connection: Any) -> bool:
        return bool(await connection.fetchval(
            "SELECT to_regclass('public.enrichment_cache') IS NOT NULL "
            "AND to_regclass('public.enrichment_credits') IS NOT NULL"))

    async def get_cache(self, key):
        row = await self.connection.fetchrow(
            """SELECT company_domain, status, emails::text AS emails, source, role_family, expires_at, updated_at
               FROM public.enrichment_cache WHERE company_domain=$1""", key)
        if row is None:
            return None
        data = dict(row)
        emails = json.loads(data.pop("emails") or "[]")
        return CacheEntry(**data, emails=emails if isinstance(emails, list) else [])

    async def put_cache(self, key, *, status, emails, source, expires_at, role_family=None):
        _check_status(status)
        await self.connection.execute(
            """INSERT INTO public.enrichment_cache (company_domain, status, emails, source, role_family, expires_at)
               VALUES ($1, $2, $3::jsonb, $4, $5, $6)
               ON CONFLICT (company_domain) DO UPDATE SET status=EXCLUDED.status, emails=EXCLUDED.emails,
                   source=EXCLUDED.source, role_family=EXCLUDED.role_family, expires_at=EXCLUDED.expires_at,
                   updated_at=now()""",
            key, status, json.dumps(emails), source, role_family, expires_at)

    async def credit(self, provider, period_key):
        row = await self.connection.fetchrow(
            """SELECT provider, period_key, used, limit_cap, cooldown_until, last_error
               FROM public.enrichment_credits WHERE provider=$1 AND period_key=$2""", provider, period_key)
        return CreditRow(**dict(row)) if row else None

    async def reserve_credit(self, provider, period_key, cap):
        if cap <= 0:
            return False
        used = await self.connection.fetchval(
            """INSERT INTO public.enrichment_credits (provider, period_key, used, limit_cap) VALUES ($1, $2, 1, $3)
               ON CONFLICT (provider, period_key) DO UPDATE
                   SET used=public.enrichment_credits.used + 1, limit_cap=EXCLUDED.limit_cap, updated_at=now()
                   WHERE public.enrichment_credits.used < EXCLUDED.limit_cap
               RETURNING used""", provider, period_key, cap)
        return used is not None

    async def set_cooldown(self, provider, period_key, cap, until, error):
        await self.connection.execute(
            """INSERT INTO public.enrichment_credits (provider, period_key, used, limit_cap, cooldown_until, last_error)
               VALUES ($1, $2, 0, $3, $4, $5)
               ON CONFLICT (provider, period_key) DO UPDATE SET cooldown_until=EXCLUDED.cooldown_until,
                   last_error=EXCLUDED.last_error, updated_at=now()""",
            provider, period_key, max(cap, 0), until, (error or None) and str(error)[:200])

    async def cooldown_until(self, provider):
        return await self.connection.fetchval(
            "SELECT max(cooldown_until) FROM public.enrichment_credits WHERE provider=$1", provider)

    async def cached_domains(self, now):
        return await self.connection.fetchval(
            "SELECT count(*) FROM public.enrichment_cache WHERE expires_at IS NULL OR expires_at > $1", now)


async def enrichment_store_for(store: Any) -> EnrichmentStore:
    """Same connection as the application store when the v2 tables exist; memory otherwise."""
    from backend.app.browser_v2.store import PostgresStore

    if isinstance(store, PostgresStore) and await PostgresEnrichmentStore.ready(store.connection):
        return PostgresEnrichmentStore(store.connection)
    return MemoryEnrichmentStore()


def ttl(days: float) -> timedelta:
    return timedelta(days=days)
