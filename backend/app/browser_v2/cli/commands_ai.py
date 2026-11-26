"""AI commands: ai-status, ai-test, seed-cache, export-sft-dataset, test-qa."""

from __future__ import annotations

from typing import Any

from backend.app.browser_v2.cli.common import emit


async def ai_status_command(load_embedder: bool) -> int:
    """Configured providers, failover order and embedding-model readiness (no LLM calls)."""
    from backend.app.ai_v2.embeddings import FastEmbedder
    from backend.app.ai_v2.runtime import AIRuntime
    from backend.app.browser_v2.service import open_store

    store, backend = await open_store(require_db=False)
    try:
        ai = await AIRuntime.for_store(store)
        embedder = ai.cache.embedder
        embed_info: dict[str, Any] = {"model": embedder.model_name, "loaded": embedder.ready}
        if isinstance(embedder, FastEmbedder):
            embed_info |= {"cache_dir": str(embedder.cache_dir), "downloaded": embedder.downloaded()}
        if load_embedder:
            vector = await embedder.embed("warm up the local embedding model")
            embed_info |= {"loaded": embedder.ready, "dimensions": len(vector)}
        status = await ai.status()
        from backend.app.browser_v2.env_loader import key_sources

        key_names = sorted({k for config in ai.router.providers.values()
                            for k in (*config.spec.key_envs, *config.spec.required_envs)})
        emit({"store": backend, "cache_backend": ai.cache.store.backend, "usage_backend": ai.router.usage.backend,
              "key_sources": key_sources(key_names),
              "embedding": embed_info,
              "configured_failover": {task: ai.router.configured_chain(task) for task in ai.router.chains},
              **status})
        return 0
    finally:
        await store.close()


async def ai_test_command(only: list[str]) -> int:
    """Live 1-request JSON health probe per configured free provider (zero PII, ~20 tokens each)."""
    from backend.app.ai_v2.probe import probe_all
    from backend.app.ai_v2.router import LLMRouter
    from backend.app.browser_v2.env_loader import env_layers, key_sources, load_env

    layers = env_layers()
    router = LLMRouter(env=load_env())
    names = sorted({k for config in router.providers.values()
                    for k in (*config.spec.key_envs, *config.spec.required_envs)})
    report = await probe_all(router.providers, only=only)
    emit({"env_layers": [layer.label + (f" ({layer.path.name})" if layer.path else "") for layer in layers],
          "key_sources": key_sources(names, layers=layers), **report})
    return 0 if report["configured"] == 0 or report["passed"] == report["configured"] else 1


async def seed_cache_command() -> int:
    """Idempotently import reviewed application_answer_drafts into semantic_cache (source='profile')."""
    from backend.app.ai_v2.runtime import AIRuntime
    from backend.app.ai_v2.semantic_cache import seed_semantic_cache
    from backend.app.browser_v2.service import open_store

    store, backend = await open_store(require_db=False)
    try:
        ai = await AIRuntime.for_store(store)
        _, reviewed = await store.load_profile()
        counts = await seed_semantic_cache(ai.cache, reviewed)
        persisted = ai.cache.store.backend == "postgres"
        emit({"store": backend, "cache_backend": ai.cache.store.backend, **counts,
              "stats": await ai.cache.stats(),
              **({} if persisted else {"warning": "semantic_cache table unavailable: seeded in memory only "
                                                  "(apply migration 004 with pgvector)"})})
        return 0 if persisted or backend != "postgres" else 1
    finally:
        await store.close()


async def export_sft_command(out: str) -> int:
    """PII-scrubbed, human-verified Q&A -> chat-completion JSONL (0600) for future fine-tuning."""
    from backend.app.ai_v2.runtime import AIRuntime
    from backend.app.ai_v2.sft_export import export_sft_dataset
    from backend.app.browser_v2.service import open_store

    store, backend = await open_store(require_db=False)
    try:
        ai = await AIRuntime.for_store(store)
        profile, reviewed = await store.load_profile()
        result = await export_sft_dataset(out, cache_store=ai.cache.store, reviewed=reviewed, profile=profile)
        emit({"store": backend, "cache_backend": ai.cache.store.backend, **result})
        return 0
    finally:
        await store.close()


async def test_qa_command(question: str, options: list[str], no_llm: bool, no_save: bool) -> int:
    """Run Tier 0 -> 1 -> 2 -> 3 for one question and print which tier answered."""
    from backend.app.ai_v2.runtime import AIRuntime
    from backend.app.browser_v2.answers import CandidateFacts
    from backend.app.browser_v2.service import open_store

    store, backend = await open_store(require_db=False)
    try:
        ai = await AIRuntime.for_store(store)
        profile, reviewed = await store.load_profile()
        ai.bind_profile(profile)
        ai.answerer.save_llm_answers = not no_save
        if no_llm:
            ai.answerer.router = None
        resolved = await ai.answerer.resolve(question, tuple(options), CandidateFacts.from_profile(profile, reviewed))
        emit({"store": backend, "cache_backend": ai.cache.store.backend, "question": question,
              "options": options, "tier": resolved.tier,
              "tier_name": {0: "profile_facts", 1: "semantic_cache", 2: "free_llm", 3: "human_hitl"}[resolved.tier],
              "cache_hit": resolved.tier == 1, **resolved.public()})
        return 0
    finally:
        await store.close()
