"""Promote an owner's HITL answer into the semantic cache (human_verified, highest trust).

The HITL row carries the context the form filler saw: company, options, DOM field kind and the
job's country (followup: browser_v2 form_filler / service.apply). The question is cached in its
LOCALIZED form; questions the cache refuses (cover letters, company motivation without a company,
work authorization / sponsorship without a named country) are not cached and the owner is told
"Not cached (one-time)". A cached answer the owner contradicts is quarantined.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.app.ai_v2.semantic_cache.cache import SemanticCache
from backend.app.ai_v2.semantic_cache.keys import profile_hash_from_profile
from backend.app.ai_v2.semantic_cache.models import InvalidCacheEntry, QuestionContext

logger = logging.getLogger("backend.app.ai_v2.semantic_cache")


def hitl_question_context(context: dict[str, Any] | None, options: tuple[str, ...],
                          profile_hash: str | None) -> QuestionContext:
    """QuestionContext from a hitl_requests.context JSON (top level: company; nested `context`:
    field_kind / role_country / platform from the form filler)."""
    ctx: dict[str, Any] = context if isinstance(context, dict) else {}
    raw_nested = ctx.get("context")
    nested: dict[str, Any] = raw_nested if isinstance(raw_nested, dict) else {}
    field_kind = nested.get("field_kind") or ({"multi": "multi_select"}.get(str(ctx.get("input_kind"))))
    return QuestionContext(field_kind=field_kind, options=tuple(options),
                           company=ctx.get("company") or nested.get("company"),
                           role_country=nested.get("role_country"), profile_hash=profile_hash,
                           platform=nested.get("platform") or ctx.get("platform"))


async def _profile_hash(store: Any, cache: SemanticCache) -> str | None:
    try:
        profile, _ = await store.load_profile()
        return profile_hash_from_profile(profile) or getattr(cache, "profile_hash", None)
    except Exception as exc:  # noqa: BLE001 - fall back to the answerer's last known hash
        logger.info("semantic_cache promotion profile_unavailable error=%s", type(exc).__name__)
        return getattr(cache, "profile_hash", None)


async def promote_human_answer(cache: SemanticCache, hitl: Any, answer: str, *, store: Any = None) -> bool:
    """True when the answer was written to the cache. Never raises for a refused question."""
    profile_hash = await _profile_hash(store, cache) if store is not None else getattr(cache, "profile_hash", None)
    options = tuple(getattr(hitl, "options", ()) or ())
    context = hitl_question_context(getattr(hitl, "context", None), options, profile_hash)
    from backend.app.browser_v2.answers.localize import localize_question

    question = localize_question(hitl.prompt_text, context.role_country)
    try:
        await cache.store_verified_user_answer(question, answer, context=context)
    except InvalidCacheEntry as exc:
        logger.info("semantic_cache promotion refused ref=%s reason=%s", getattr(hitl, "ref", "?"), exc)
        return False
    return True
