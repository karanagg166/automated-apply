"""WRITE tools for the candidate profile and the screening-fact (semantic cache) memory.

- update_candidate_profile: preferences only, validated by JobSearchPreferences through
  `store.update_preferences`; then the profile-derived cache entries are re-seeded (source='profile').
- upsert_qa_fact: a verified owner fact (source='user', outranks profile/LLM answers).
- remove_qa_fact: risky (needs confirmation); removes one cache row by id.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.app.agent_v2.tools.args import (
    RemoveFactArgs,
    UpdateProfileArgs,
    UpsertFactArgs,
)
from backend.app.agent_v2.tools.base import (
    PREFERENCE_LISTS,
    GuardrailViolation,
    ToolResult,
)
from backend.app.agent_v2.tools.spec import ToolContext, ToolSpec, h, refused
from backend.app.browser_v2.store import PROFILE_KEYS, ProfileMissing

SYSTEM_PREFERENCES = frozenset({"portal_rule_overrides"})
TOP_LEVEL = frozenset(PROFILE_KEYS) - {"preferences"}
# Profile facts re-seeded into the semantic cache (source='profile') when they change.
DERIVED_FACTS: dict[str, tuple[str, Callable[[Any], str]]] = {
    "notice_period_days": ("What is your notice period (in days)?",
                           lambda v: "Immediate (0 days)" if v == 0 else f"{v} days"),
    "total_experience_years": ("How many years of total work experience do you have?", lambda v: f"{v} years"),
    "current_location": ("What is your current location?", str),
    "willing_to_relocate": ("Are you willing to relocate?", lambda v: "Yes" if v else "No"),
}


def preference_fields() -> frozenset[str]:
    from backend.app.schemas.candidate_profile import JobSearchPreferences

    return frozenset(JobSearchPreferences.model_fields) - SYSTEM_PREFERENCES


def _merge_list(current: Any, op: dict[str, Any]) -> list[str]:
    items = [str(v) for v in current or []]
    add = [str(v).strip() for v in op.get("add") or [] if str(v).strip()]
    drop = {str(v).strip().lower() for v in op.get("remove") or []}
    merged = [v for v in items if v.lower() not in drop]
    return merged + [v for v in add if v.lower() not in {m.lower() for m in merged}]


async def _preferences(ctx: ToolContext) -> dict[str, Any]:
    profile, _ = await ctx.store.load_profile()
    if not profile:
        raise GuardrailViolation("Create the candidate profile on the dashboard first.")
    return dict(profile.get("preferences") or {})


async def profile_snapshot(ctx: ToolContext, args: UpdateProfileArgs) -> dict[str, Any] | None:
    try:
        prefs = await _preferences(ctx)
    except GuardrailViolation:
        return None
    return {key: prefs.get(key) for key in args.fields}


async def reseed_profile_facts(ctx: ToolContext, prefs: dict[str, Any], changed: list[str]) -> dict[str, int]:
    """Reviewed answers (same as `facts reseed-cache`) + the changed derived facts, source='profile'."""
    if ctx.cache is None:
        return {}
    from backend.app.ai_v2.semantic_cache import seed_semantic_cache
    from backend.app.browser_v2.facts_cli import reseed_cache

    counts = await reseed_cache(ctx.store, ctx.ai)
    pairs = [(question, render(prefs[key])) for key, (question, render) in DERIVED_FACTS.items()
             if key in changed and prefs.get(key) is not None]
    derived = await seed_semantic_cache(ctx.cache, pairs) if pairs else {}
    return {"reviewed_seen": int(counts.get("seen", 0)), "derived_seeded": int(derived.get("inserted", 0))
            + int(derived.get("updated", 0))}


async def update_candidate_profile(ctx: ToolContext, args: UpdateProfileArgs, confirmed: bool) -> ToolResult:
    top = sorted(set(args.fields) & TOP_LEVEL)
    if top:
        return refused(f"Name/contact/link fields ({', '.join(top)}) are edited on the dashboard profile page.")
    allowed = preference_fields()
    unknown = sorted(set(args.fields) - allowed)
    if unknown:
        return refused(f"Unknown profile field(s): {', '.join(unknown)}.")
    before = await _preferences(ctx)
    changes: dict[str, Any] = {}
    for key, value in args.fields.items():
        if isinstance(value, dict) and value and set(value) <= {"add", "remove"} and \
                (key in PREFERENCE_LISTS or isinstance(before.get(key), list)):
            changes[key] = _merge_list(before.get(key), value)
        else:
            changes[key] = value
    try:
        stored = await ctx.store.update_preferences(changes)
    except ProfileMissing:
        return refused("Create the candidate profile on the dashboard first.")
    except ValueError as exc:
        return refused(f"Rejected by profile validation: {exc}")
    reseeded = await reseed_profile_facts(ctx, stored, list(changes))
    lines = [f"• <b>{h(k, 40)}</b>: {h(before.get(k), 80)} → {h(stored.get(k), 120)}" for k in changes]
    note = " Semantic cache re-seeded from your profile." if reseeded else ""
    return ToolResult(True, f"Updated profile: {', '.join(changes)}.{note}", {"fields": list(changes),
                      "reseeded": reseeded}, user_html="✅ <b>Profile updated</b>\n" + "\n".join(lines),
                      llm_summary=f"ok: updated {', '.join(changes)}; worker re-reads preferences every cycle.")


async def upsert_qa_fact(ctx: ToolContext, args: UpsertFactArgs, confirmed: bool) -> ToolResult:
    from backend.app.ai_v2.semantic_cache import InvalidCacheEntry
    from backend.app.browser_v2.answers import BLOCKED

    if ctx.cache is None:
        return refused("The semantic cache is unavailable (AI_V2_DISABLED).")
    if BLOCKED.search(args.question):
        return refused("Login, password, OTP, email and consent answers are never stored.")
    try:
        result = await ctx.cache.put(args.category, args.question, args.answer, "user")
    except InvalidCacheEntry as exc:
        return refused(f"Rejected: {exc}")
    entry = result.entry
    return ToolResult(True, f"Saved fact ({result.outcome}).", {"id": entry.id, "outcome": result.outcome},
                      user_html=(f"🧠 <b>Fact saved</b> ({h(result.outcome, 30)}, verified owner answer)\n"
                                 f"Q: <i>{h(entry.question_text, 300)}</i>\nA: {h(entry.answer_text, 300)}\n"
                                 f"id <code>{h(entry.id, 40)}</code>"),
                      llm_summary=f"ok: fact {result.outcome} id={entry.id}")


async def _find_fact(ctx: ToolContext, fact_id: str) -> Any:
    entries, _ = await ctx.cache.store.list_entries(None, None, 500, 0)
    return next((e for e in entries if e.id.lower() == fact_id.lower()), None)


async def fact_snapshot(ctx: ToolContext, args: RemoveFactArgs) -> dict[str, Any] | None:
    if ctx.cache is None:
        return None
    entry = await _find_fact(ctx, args.id)
    return {"id": entry.id, "question": entry.question_text, "source": entry.source} if entry else {"id": None}


async def remove_qa_fact(ctx: ToolContext, args: RemoveFactArgs, confirmed: bool) -> ToolResult:
    if ctx.cache is None:
        return refused("The semantic cache is unavailable (AI_V2_DISABLED).")
    entry = await _find_fact(ctx, args.id)
    if entry is None:
        return refused(f"No saved fact with id {args.id}.")
    removed = await ctx.cache.store.delete(entry.id)
    if not removed:
        return refused(f"Fact {args.id} was already gone.")
    return ToolResult(True, "Fact removed.", {"id": entry.id},
                      user_html=(f"🗑 <b>Fact removed</b>\nQ: <i>{h(entry.question_text, 300)}</i>\n"
                                 f"A: {h(entry.answer_text, 200)} ({h(entry.source, 20)})"),
                      llm_summary=f"ok: fact {entry.id} removed")


PROFILE_SPECS = (
    ToolSpec("update_candidate_profile", "Update job-search preferences (fields: {name: value}; list fields also "
             "accept {\"add\": [...], \"remove\": [...]}), validated like the dashboard. Name/contact fields "
             "are dashboard-only.", UpdateProfileArgs, "write", update_candidate_profile,
             snapshot=profile_snapshot),
    ToolSpec("upsert_qa_fact", "Save a verified screening answer (question, answer, category) used before any "
             "LLM.", UpsertFactArgs, "write", upsert_qa_fact),
    ToolSpec("remove_qa_fact", "Remove one saved screening fact by id (needs the owner's confirmation).",
             RemoveFactArgs, "write", remove_qa_fact, risky=True, snapshot=fact_snapshot),
)
