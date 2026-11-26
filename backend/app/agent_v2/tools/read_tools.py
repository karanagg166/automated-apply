"""READ tools: status, applications, profile facts, semantic cache, rules, HITL and analytics.

Each returns a compact JSON `llm_summary` (the LLM's observation; the router PII-scrubs it
before dispatch). Values only the owner may see go to `user_html` (his own chat).
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

from backend.app.agent_v2.tools.args import (
    BOARD_PORTALS,
    AnalyticsArgs,
    ApplicationDetailsArgs,
    NoArgs,
    PortalArg,
    QueryApplicationsArgs,
    SearchCacheArgs,
)
from backend.app.agent_v2.tools.base import ToolResult
from backend.app.agent_v2.tools.spec import ToolContext, ToolSpec, h, refused
from backend.app.browser_v2.portals import PORTALS, portal_label
from backend.app.browser_v2.rules import normalize_company
from backend.app.browser_v2.store import ApplicationQuery
from backend.app.browser_v2.store.agent_records import FUNNEL_KEYS

SUMMARY_CHARS = 3500


def summary(value: Any) -> str:
    text = json.dumps(value, default=str, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= SUMMARY_CHARS else text[:SUMMARY_CHARS] + "…"


def ok(message: str, data: Any, *, user_html: str | None = None) -> ToolResult:
    return ToolResult(True, message, {"result": data}, user_html=user_html, llm_summary=summary(data))


def _row(record: Any) -> dict[str, Any]:
    return {"id": record.id, "portal": record.platform, "company": record.company_name, "role": record.role_title,
            "state": record.state.value, "reason": record.reason, "priority": f"P{record.priority}",
            "updated_at": record.updated_at}


async def get_system_status(ctx: ToolContext, args: NoArgs, confirmed: bool) -> ToolResult:
    from backend.app.browser_v2.service import quota_counts

    control = await ctx.store.get_worker_control()
    now = ctx.clock()
    portals = []
    for rules in await ctx.store.list_rules():
        if not rules.enabled:
            continue
        counts = await quota_counts(ctx.store, rules, now)
        portals.append({"portal": rules.platform, "auto_apply": rules.auto_apply_enabled,
                        "applied_today": counts["applied_today"], "daily_cap": rules.max_applies_per_day,
                        "auth": rules.auth_status, "paused_until": rules.paused_until})
    providers = None
    router = getattr(ctx.ai, "router", None)
    if router is not None:
        providers = [p["provider"] for p in await router.status() if p["status"] == "healthy"]
    data = {"worker": {"desired": control.desired_state.value, "observed": control.observed_state,
                       "mode": "DRY_RUN" if control.dry_run else "LIVE", "current_portal": control.current_platform,
                       "last_cycle_at": control.last_cycle_at, "last_error": control.last_error},
            "enabled_portals": portals, "open_hitl": await ctx.store.count_open_hitl(),
            "healthy_llm_providers": providers}
    return ok("system status", data)


async def query_applications(ctx: ToolContext, args: QueryApplicationsArgs, confirmed: bool) -> ToolResult:
    since = ctx.clock() - timedelta(days=args.days)
    wanted = normalize_company(args.company) if args.company else None
    rows, total = await ctx.store.list_applications(ApplicationQuery(
        platform=args.portal, state=args.status, since=since, limit=500 if wanted else args.limit))
    if wanted:
        rows = [r for r in rows if wanted in normalize_company(r.company_name)]
        total = len(rows)
    return ok("applications", {"total": total, "items": [_row(r) for r in rows[:args.limit]]})


async def get_application_details(ctx: ToolContext, args: ApplicationDetailsArgs, confirmed: bool) -> ToolResult:
    key = args.app_id_or_company
    record = await ctx.store.get_application(key)
    matches = [record] if record is not None else []
    if not matches:
        wanted = normalize_company(key)
        rows, _ = await ctx.store.list_applications(ApplicationQuery(limit=500))
        matches = [r for r in rows if wanted and wanted in normalize_company(r.company_name)][:3]
    if not matches:
        return ok("not found", {"found": False, "query": key})
    items = []
    for record in matches:
        events = await ctx.store.application_events(record.id) or []
        # Event payloads can carry HITL answers: only the transitions are shared.
        history = [{"to": e.get("to_state"), "event": e.get("event_type"), "at": e.get("created_at")}
                   for e in events[-6:]]
        items.append(_row(record) | {"job_url": record.job_url, "attempts": record.attempts,
                                     "applied_at": record.applied_at, "history": history})
    return ok("application details", {"found": True, "items": items})


async def get_candidate_profile_and_facts(ctx: ToolContext, args: NoArgs, confirmed: bool) -> ToolResult:
    from backend.app.ai_v2.pii import build_safe_llm_profile
    from backend.app.browser_v2.facts_cli import facts_report

    profile, reviewed = await ctx.store.load_profile()
    if not profile:
        return ok("no profile", {"profile": "missing"})
    report = await facts_report(ctx.store)
    prefs = profile.get("preferences") or {}
    safe = {"safe_profile": build_safe_llm_profile(profile), "facts_present": report.get("present"),
            "facts_missing": report.get("missing"), "preference_keys": sorted(prefs),
            "reviewed_answers": len(reviewed)}
    shown = [f"• <b>{h(k, 40)}</b>: {h(v, 120)}" for k, v in sorted(prefs.items())
             if v not in (None, "", [], {}) and k != "portal_rule_overrides"][:40]
    user_html = "👤 <b>Your profile preferences</b>\n" + ("\n".join(shown) or "(none set)")
    return ok("profile summary", safe, user_html=user_html)


async def search_semantic_cache(ctx: ToolContext, args: SearchCacheArgs, confirmed: bool) -> ToolResult:
    if ctx.cache is None:
        return refused("The semantic cache is unavailable (AI_V2_DISABLED).")
    entries, total = await ctx.cache.store.list_entries(None, args.query, args.limit, 0)
    return ok("semantic cache", {"total": total, "items": [
        {"id": e.id, "kind": e.kind, "source": e.source, "question": e.question_text[:200],
         "answer": e.answer_text[:200]} for e in entries]})


async def get_portal_rules(ctx: ToolContext, args: PortalArg, confirmed: bool) -> ToolResult:
    if args.portal and args.portal not in PORTALS:
        return refused(f"Unknown portal: {args.portal}")
    profile, _ = await ctx.store.load_profile()
    prefs = (profile or {}).get("preferences") or {}
    items = []
    for rules in await ctx.store.list_rules():
        if args.portal and rules.platform != args.portal:
            continue
        item: dict[str, Any] = {
            "portal": rules.platform, "label": portal_label(rules.platform), "enabled": rules.enabled,
            "auto_apply": rules.auto_apply_enabled, "daily_cap": rules.max_applies_per_day,
            "hourly_cap": rules.max_applies_per_hour, "max_job_age_days": rules.max_job_age_days,
            "max_applicants": rules.max_applicants, "delay_sec": [rules.min_delay_sec, rules.max_delay_sec],
            "paused_until": rules.paused_until, "auth": rules.auth_status,
            "allow_unknown_posting_age": rules.unknown_age_allowed, "circuit_open_until": rules.circuit_open_until}
        if rules.platform in BOARD_PORTALS:
            item["boards"] = sorted(prefs.get(f"{rules.platform}_boards") or {})
        items.append(item)
    return ok("portal rules", {"items": items})


async def get_pending_hitl(ctx: ToolContext, args: NoArgs, confirmed: bool) -> ToolResult:
    rows, total = await ctx.store.list_hitl("OPEN", limit=20)
    return ok("open requests", {"total": total, "items": [
        {"ref": r.ref, "kind": r.kind, "portal": r.platform, "company": r.company, "title": r.title,
         "question": r.prompt_text[:200], "options": list(r.options)[:10]} for r in rows]})


async def get_analytics_summary(ctx: ToolContext, args: AnalyticsArgs, confirmed: bool) -> ToolResult:
    per_portal = await ctx.store.funnel(args.days, args.portal, now=ctx.clock())
    totals = {key: sum(bucket.get(key, 0) for bucket in per_portal.values()) for key in FUNNEL_KEYS}
    return ok("funnel", {"days": args.days, "totals": totals, "per_portal": per_portal})


READ_SPECS = (
    ToolSpec("get_system_status", "Worker state, mode (dry run/live), enabled portals with today's applies vs caps,"
             " open HITL count and healthy LLM providers.", NoArgs, "read", get_system_status),
    ToolSpec("query_applications", "Recent applications filtered by portal, status (an application state, e.g. "
             "APPLIED, FAILED, WAITING_FOR_USER), company, days<=90, limit<=25.", QueryApplicationsArgs, "read", query_applications),
    ToolSpec("get_application_details", "One application by id or company name: state, reason, priority and "
             "state history.", ApplicationDetailsArgs, "read", get_application_details),
    ToolSpec("get_candidate_profile_and_facts", "Safe professional profile summary plus which screening facts "
             "are present/missing (values are shown to the owner, not to you).", NoArgs, "read",
             get_candidate_profile_and_facts),
    ToolSpec("search_semantic_cache", "Search saved screening Q&A facts (question/answer, source, id); limit "
             "<= 10.", SearchCacheArgs, "read", search_semantic_cache),
    ToolSpec("get_portal_rules", "Portal rules (caps, age, delays, pause, auth, ATS boards) for one portal or "
             "all.", PortalArg, "read", get_portal_rules),
    ToolSpec("get_pending_hitl", "Open human-in-the-loop requests (ref, kind, question, options).", NoArgs,
             "read", get_pending_hitl),
    ToolSpec("get_analytics_summary", "Funnel counts per portal for the last N days (<=90): discovered, filtered,"
             " applied, failed, waiting, quota, submission_unknown, recruiter_replies.", AnalyticsArgs, "read",
             get_analytics_summary),
)
