"""Profile-hash stamping for owner-verified semantic-cache rows (dashboard "Stamp Profile Hash").

Same facts build as the worker (`ApplyMixin.process_job`: profile + project-.env overrides) so the
stamped hash is exactly the one the screening resolver compares against. Only owner-verified rows
(source user/profile) are ever stamped; LLM answers keep their original hash and go stale on a
profile change, which is the point of the stale-profile guard.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from backend.app.browser_v2.answers import CandidateFacts
from backend.app.browser_v2.schemas.ops import StampProfileRead

OWNER_SOURCES = ("user", "profile")
FACTUAL = "factual_profile"

STAMP_SQL = {
    "unstamped": """UPDATE public.semantic_cache SET profile_version_hash=$1, updated_at=now()
                    WHERE profile_version_hash IS NULL AND status='active' AND source IN ('user','profile')""",
    "owner_verified": """UPDATE public.semantic_cache SET profile_version_hash=$1, updated_at=now()
                         WHERE profile_version_hash IS DISTINCT FROM $1 AND status='active'
                           AND source IN ('user','profile')""",
}
STALE_SQL = """SELECT count(*) FROM public.semantic_cache
               WHERE status='active' AND invalidation_scope='factual_profile'
                 AND profile_version_hash IS DISTINCT FROM $1"""


async def current_profile_hash(store: Any, env: Mapping[str, str]) -> str:
    from backend.app.ai_v2.semantic_cache.keys import profile_version_hash
    from backend.app.browser_v2.service.helpers import (
        apply_env_profile,
        env_profile_overrides,
    )

    profile, reviewed = await store.load_profile()
    facts = apply_env_profile(CandidateFacts.from_profile(profile, reviewed), env_profile_overrides(env))
    return profile_version_hash(facts) or ""


def _memory_stamp(cache_store: Any, digest: str, scope: str) -> tuple[int, int]:
    stamped = 0
    for key, row in list(cache_store.rows.items()):
        entry = row.entry
        current = entry.meta.profile_version_hash
        due = current is None if scope == "unstamped" else current != digest
        if entry.status == "active" and entry.source in OWNER_SOURCES and due:
            row.entry = replace(entry, meta=replace(entry.meta, profile_version_hash=digest))
            cache_store.rows[key] = row
            stamped += 1
    stale = sum(1 for row in cache_store.rows.values() if row.entry.status == "active"
                and row.entry.meta.invalidation_scope == FACTUAL and row.entry.meta.profile_version_hash != digest)
    return stamped, stale


async def stale_count(ai: Any, digest: str) -> int | None:
    """Active factual entries whose profile hash is not `digest` (None when the cache is unreachable)."""
    cache_store = getattr(getattr(ai, "cache", None), "store", None)
    connection = getattr(cache_store, "connection", None)
    if connection is not None:
        return int(await connection.fetchval(STALE_SQL, digest) or 0)
    if cache_store is not None and hasattr(cache_store, "rows"):
        return sum(1 for row in cache_store.rows.values() if row.entry.status == "active"
                   and row.entry.meta.invalidation_scope == FACTUAL
                   and row.entry.meta.profile_version_hash != digest)
    return None


async def stamp_profile_hash(store: Any, ai: Any, env: Mapping[str, str], *,
                             scope: str = "unstamped") -> StampProfileRead:
    """Raises LookupError when no semantic cache store is reachable."""
    if scope not in STAMP_SQL:
        raise ValueError("invalid_scope")
    cache_store = getattr(getattr(ai, "cache", None), "store", None)
    if cache_store is None:
        raise LookupError("semantic cache unavailable")
    digest = await current_profile_hash(store, env)
    connection = getattr(cache_store, "connection", None)
    if connection is not None:
        result = await connection.execute(STAMP_SQL[scope], digest)
        stamped = int(str(result).rsplit(" ", 1)[-1] or 0)
        stale = int(await connection.fetchval(STALE_SQL, digest) or 0)
    elif hasattr(cache_store, "rows"):
        stamped, stale = _memory_stamp(cache_store, digest, scope)
    else:
        raise LookupError("semantic cache backend does not support stamping")
    return StampProfileRead(stamped=stamped, profile_hash=digest[:12], stale_remaining=stale, scope=scope)
