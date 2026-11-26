"""WRITE tools that touch application rows: owner-requested priority jobs and HITL resolution.

Both are fenced twice: the agent guardrail refuses APPLIED / SUBMISSION_UNKNOWN targets before
anything runs, and the store methods (`enqueue_owner_job`, `set_owner_priority`) refuse them again.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from backend.app.agent_v2.tools.args import EnqueueArgs, ResolveHitlArgs
from backend.app.agent_v2.tools.base import GuardrailViolation, ToolResult
from backend.app.agent_v2.tools.guardrails import check_fence, fence_reason
from backend.app.agent_v2.tools.spec import ToolContext, ToolSpec, h, refused
from backend.app.browser_v2.domain import JobListing
from backend.app.browser_v2.portals import PORTALS, portal_label
from backend.app.browser_v2.state import ApplicationState
from backend.app.browser_v2.store import DiscoveryMeta

HOST_PORTALS = {"naukri.com": "naukri", "instahyre.com": "instahyre", "internshala.com": "internshala",
                "wellfound.com": "wellfound", "angel.co": "wellfound", "workatastartup.com": "work_at_a_startup",
                "himalayas.app": "himalayas", "weworkremotely.com": "we_work_remotely", "hiring.cafe": "hiringcafe",
                "jobs.ashbyhq.com": "ashby", "smartrecruiters.com": "smartrecruiters", "remotive.com": "remotive",
                "arbeitnow.com": "arbeitnow", "news.ycombinator.com": "hacker_news"}
REQUEUE_STATES = (ApplicationState.FILTERED_OUT, ApplicationState.FAILED)
HITL_VIA = {"telegram": "telegram", "mcp": "mcp", "worker": "worker"}
OWNER_REASON = "owner_requested"


def job_target(url: str, portal: str | None) -> tuple[str, str, str]:
    """(platform, external_job_id, canonical url) for a pasted job URL, or GuardrailViolation."""
    from backend.app.browser_v2.adapters.common import ats_handoff_target
    from backend.app.browser_v2.service import job_id_from_url

    handoff = ats_handoff_target(url)
    if handoff is not None and (portal is None or portal == handoff.platform):
        return handoff.platform, handoff.external_job_id, handoff.url
    host = (urlsplit(url).hostname or "").lower()
    platform = portal or next((p for suffix, p in HOST_PORTALS.items()
                               if host == suffix or host.endswith("." + suffix)), None)
    if platform is None or platform not in PORTALS:
        raise GuardrailViolation("I can't tell which portal that URL belongs to; name the portal too.")
    external_id = job_id_from_url(platform, url)
    if not external_id:
        raise GuardrailViolation(f"That doesn't look like a {portal_label(platform)} job URL.")
    return platform, external_id, url


async def enqueue_guard(ctx: ToolContext, args: EnqueueArgs) -> str | None:
    try:
        platform, external_id, _ = job_target(args.url, args.portal)
    except GuardrailViolation as exc:
        return str(exc)
    existing = await ctx.store.get(platform, external_id)
    return fence_reason(existing.state) if existing is not None else None


async def enqueue_snapshot(ctx: ToolContext, args: EnqueueArgs) -> dict[str, Any] | None:
    try:
        platform, external_id, _ = job_target(args.url, args.portal)
    except GuardrailViolation:
        return None
    record = await ctx.store.get(platform, external_id)
    return {"platform": platform, "external_job_id": external_id,
            "state": record.state.value if record else None, "priority": record.priority if record else None}


async def enqueue_priority_job(ctx: ToolContext, args: EnqueueArgs, confirmed: bool) -> ToolResult:
    platform, external_id, url = job_target(args.url, args.portal)
    priority = int(args.priority[1])
    check_fence(await ctx.store.get(platform, external_id))
    meta = DiscoveryMeta(priority=priority, priority_reason=OWNER_REASON, discovered_via=ctx.source)
    result = await ctx.store.enqueue_owner_job(JobListing(platform=platform, external_job_id=external_id, url=url),
                                               meta)
    record = result.record
    notes = []
    if record.state in REQUEUE_STATES:
        record = await ctx.store.transition(record, ApplicationState.SCORED, OWNER_REASON,
                                            payload={"via": ctx.source, "priority": args.priority})
        notes.append(f"re-queued from {result.record.state.value}")
    if record.priority > priority and record.state in (ApplicationState.DISCOVERED, ApplicationState.SCORED):
        await ctx.store.set_owner_priority(record.id, priority, OWNER_REASON)
    elif record.state not in (ApplicationState.DISCOVERED, ApplicationState.SCORED):
        notes.append(f"currently {record.state.value}; left as is")
    rules = await ctx.store.get_rules(platform)
    if not (rules.enabled and rules.auto_apply_enabled):
        notes.append(f"auto-apply is OFF for {portal_label(platform)}, so it waits until you enable it")
    woke = await ctx.notify_wake()
    status = "queued" if result.inserted else "already known"
    head = (f"• {h(portal_label(platform), 40)} job <code>{h(external_id, 60)}</code>: {status}, "
            f"<b>{h(args.priority, 3)}</b>")
    lines = [head, *[f"• {h(n, 200)}" for n in notes]]
    if woke:
        lines.append("• worker woken")
    return ToolResult(True, f"{status} as {args.priority}", {"platform": platform, "external_job_id": external_id,
                      "application_id": record.id, "inserted": result.inserted},
                      user_html="🚀 <b>Priority job</b>\n" + "\n".join(lines),
                      llm_summary=f"ok: {platform} {external_id} {status} {args.priority}; " + "; ".join(notes))


# --- resolve_hitl_via_agent ---------------------------------------------------------------------
async def find_hitl(ctx: ToolContext, key: str) -> tuple[Any, str | None]:
    hitl = await ctx.store.get_hitl(key) if len(key) >= 32 else None
    if hitl is not None:
        return hitl, None
    found, problem = await ctx.hitl().by_ref(key.lower())
    return found, problem.message if problem is not None else None


async def hitl_guard(ctx: ToolContext, args: ResolveHitlArgs) -> str | None:
    hitl, problem = await find_hitl(ctx, args.hitl_id_or_ref)
    if hitl is None:
        return problem or "No such open request."
    if hitl.application_id:
        record = await ctx.store.get_application(hitl.application_id)
        reason = fence_reason(record.state) if record is not None else None
        if reason:
            return reason + " Use /skip on the request card to close it."
    if args.action == "answer" and not (args.answer or "").strip():
        return "An answer is required (or use action skip/retry)."
    return None


async def hitl_snapshot(ctx: ToolContext, args: ResolveHitlArgs) -> dict[str, Any] | None:
    hitl, _ = await find_hitl(ctx, args.hitl_id_or_ref)
    if hitl is None:
        hitl = await ctx.store.get_hitl(args.hitl_id_or_ref) if len(args.hitl_id_or_ref) >= 32 else None
    if hitl is None:
        return None
    record = await ctx.store.get_application(hitl.application_id) if hitl.application_id else None
    return {"ref": hitl.ref, "kind": hitl.kind, "status": hitl.status,
            "application_state": record.state.value if record else None}


async def resolve_hitl_via_agent(ctx: ToolContext, args: ResolveHitlArgs, confirmed: bool) -> ToolResult:
    hitl, problem = await find_hitl(ctx, args.hitl_id_or_ref)
    if hitl is None:
        return refused(problem or "No such open request.")
    if hitl.application_id:
        check_fence(await ctx.store.get_application(hitl.application_id))
    service = ctx.hitl()
    via = HITL_VIA.get(ctx.source, "dashboard")
    if args.action == "skip":
        resolution = await service.skip(hitl.id, via=via)
    elif args.action == "retry":
        resolution = await service.retry(hitl.id, via=via)
    else:
        resolution = await service.answer(hitl.id, args.answer or "", cache_answer=hitl.kind == "QUESTION", via=via)
    if not resolution.ok:
        return ToolResult(False, resolution.message, {"resolution": resolution},
                          user_html=f"⚠️ {h(resolution.message, 800)}", llm_summary=f"failed: {resolution.message}",
                          outcome="refused")
    return ToolResult(True, resolution.message, {"resolution": resolution},
                      user_html=f"✅ <b>Request {h(hitl.ref, 12)}</b>: {h(resolution.message, 500)}",
                      llm_summary=f"ok: {resolution.code} {hitl.ref}")


QUEUE_SPECS = (
    ToolSpec("enqueue_priority_job", "Queue a pasted job URL as an owner-requested priority job (portal is "
             "detected from the URL).", EnqueueArgs, "write",
             enqueue_priority_job, guard=enqueue_guard, snapshot=enqueue_snapshot),
    ToolSpec("resolve_hitl_via_agent", "Resolve an open request by ref: action answer (with answer text) | skip | "
             "retry.", ResolveHitlArgs, "write", resolve_hitl_via_agent, guard=hitl_guard, snapshot=hitl_snapshot),
)
