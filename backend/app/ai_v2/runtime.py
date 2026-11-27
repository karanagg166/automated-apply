"""Builds the v2 AI layer for one store (worker, CLI, API, FastMCP).

Postgres store -> public.semantic_cache (when migration 004's pgvector block is
installed) + public.llm_provider_usage over the SAME asyncpg connection (no
extra Supabase connection). Memory store -> memory backends with the same
contract. With no provider keys the worker runs in deterministic + cache mode.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from backend.app.ai_v2.embeddings import Embedder, FastEmbedder
from backend.app.ai_v2.intro import IntroComposer
from backend.app.ai_v2.jd_scoring import JDScorer
from backend.app.ai_v2.judge import AnswerJudge, judge_mode
from backend.app.ai_v2.pii import build_safe_llm_profile, profile_secrets
from backend.app.ai_v2.router import LLMRouter
from backend.app.ai_v2.screening import ScreeningAnswerer
from backend.app.ai_v2.semantic_cache import (
    DEFAULT_THRESHOLD,
    CacheStore,
    MemoryCacheStore,
    PostgresCacheStore,
    SemanticCache,
)
from backend.app.ai_v2.usage import MemoryUsageStore, PostgresUsageStore, UsageStore

THRESHOLD_ENV = "SEMANTIC_CACHE_THRESHOLD"
_EMBEDDER: Embedder | None = None


def shared_embedder() -> Embedder:
    """One lazily-loaded ONNX model per process."""
    global _EMBEDDER
    if _EMBEDDER is None:
        _EMBEDDER = FastEmbedder()
    return _EMBEDDER


def cache_threshold(env: Mapping[str, str]) -> float:
    try:
        value = float(env.get(THRESHOLD_ENV) or DEFAULT_THRESHOLD)
    except ValueError:
        return DEFAULT_THRESHOLD
    return value if 0.5 <= value <= 1.0 else DEFAULT_THRESHOLD


@dataclass
class AIRuntime:
    cache: SemanticCache
    router: LLMRouter
    answerer: ScreeningAnswerer
    jd_scorer: JDScorer
    intro: IntroComposer | None = None

    def bind_profile(self, profile: Mapping[str, Any]) -> None:
        """Refresh the PII-free LLM context and the owner identifiers scrubbed from prompts."""
        safe = build_safe_llm_profile(profile)
        self.router.register_secrets(profile_secrets(profile))
        self.answerer.bind_profile(safe)
        if self.intro is not None:
            self.intro.bind_profile(safe)
        prefs = profile.get("preferences") or {}
        min_score = prefs.get("min_match_score") if isinstance(prefs, Mapping) else None
        self.jd_scorer.bind_profile(safe, float(min_score) if isinstance(min_score, (int, float))
                                    and not isinstance(min_score, bool) else None)

    async def status(self) -> dict[str, Any]:
        return {"providers": await self.router.status(),
                "chains": {task: list(self.router.chain(task)) for task in self.router.chains},
                "semantic_cache": await self.cache.stats(),
                "local_generative_llm": "disabled"}

    @classmethod
    def build(cls, cache_store: CacheStore, usage: UsageStore, *, embedder: Embedder | None = None,
              env: Mapping[str, str] | None = None, transport: httpx.AsyncBaseTransport | None = None,
              save_llm_answers: bool = True) -> AIRuntime:
        router = LLMRouter(env=env, usage=usage, transport=transport)
        cache = SemanticCache(cache_store, embedder or shared_embedder(), threshold=cache_threshold(router.env))
        return cls(cache=cache, router=router,
                   answerer=ScreeningAnswerer(cache, router, save_llm_answers=save_llm_answers,
                                              judge=AnswerJudge(router, mode=judge_mode(router.env))),
                   jd_scorer=JDScorer(router, cache), intro=IntroComposer(router))

    @classmethod
    async def for_store(cls, store: Any, *, embedder: Embedder | None = None,
                        env: Mapping[str, str] | None = None,
                        transport: httpx.AsyncBaseTransport | None = None) -> AIRuntime:
        from backend.app.browser_v2.store import PostgresStore

        cache_store: CacheStore
        usage: UsageStore
        if isinstance(store, PostgresStore):
            connection = store.connection
            cache_store = PostgresCacheStore(connection) if await PostgresCacheStore.ready(connection) \
                else MemoryCacheStore()
            usage = PostgresUsageStore(connection)
        else:
            cache_store, usage = MemoryCacheStore(), MemoryUsageStore()
        return cls.build(cache_store, usage, embedder=embedder, env=env, transport=transport)


def ai_disabled() -> bool:
    """AI_V2_DISABLED=true forces deterministic-only mode (no cache, no LLM)."""
    return os.environ.get("AI_V2_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"}
