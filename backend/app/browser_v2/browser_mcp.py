"""FastMCP exposure of the same in-process browser tools (stdio, local owner only).

Run: backend/venv/bin/python -m backend.app.browser_v2.cli mcp
Live applies require the Postgres store so the never-replay guard is durable.
There is intentionally no email-delivery tool here (Gmail is read + draft only),
and no local generative LLM: AI tools use the local embedding cache + free external router.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastmcp import FastMCP

from backend.app.ai_v2.runtime import AIRuntime
from backend.app.browser_v2.service import BrowserService, build_service, plain
from backend.app.browser_v2.store import PostgresStore

mcp = FastMCP("automated-apply-browser")
TOOL_NAMES = ("check_portal_session", "discover_portal_jobs", "inspect_job_form", "apply_to_job",
              "recycle_browser", "lookup_semantic_cache", "save_semantic_cache_entry", "get_llm_router_status",
              "list_open_hitl_requests", "resolve_hitl_request", "get_telegram_status",
              "enrich_company_contact", "create_application_gmail_draft", "list_email_drafts",
              "get_mail_and_enrichment_status", "agent_control_chat", "get_event_bus_status",
              "list_recruiter_replies")
# Phase 5 mail tools are READ + DRAFT ONLY (enforced by test_gmail_no_send_guardrail.py).
DRAFT_ONLY_MAIL_TOOLS = frozenset({"create_application_gmail_draft", "list_email_drafts",
                                   "get_mail_and_enrichment_status"})

_service: BrowserService | None = None
_service_lock = asyncio.Lock()


async def service() -> BrowserService:
    global _service
    async with _service_lock:
        if _service is None:
            _service, _ = await build_service(require_db=False)
        return _service


@mcp.tool()
async def check_portal_session(platform: str = "naukri") -> dict[str, Any]:
    """Check whether the dedicated Brave profile is logged in to a portal (refreshes once)."""
    return await (await service()).check_portal_session(platform)


@mcp.tool()
async def discover_portal_jobs(query: str, platform: str = "naukri", limit: int = 20) -> list[dict[str, Any]]:
    """Search a portal and record new jobs as DISCOVERED."""
    return await (await service()).discover_portal_jobs(platform, query, limit)


@mcp.tool()
async def inspect_job_form(url: str, platform: str = "naukri") -> dict[str, Any]:
    """Compact JSON of the visible form/chatbot fields on a job page (no raw HTML)."""
    return await (await service()).inspect_job_form(platform, url)


@mcp.tool()
async def apply_to_job(url: str, platform: str = "naukri", dry_run: bool = True) -> dict[str, Any]:
    """Apply to one job. dry_run stops before the Apply click; live refuses APPLIED/SUBMISSION_UNKNOWN."""
    current = await service()
    if not dry_run and not isinstance(current.store, PostgresStore):
        return {"refused": "live_apply_requires_postgres_store"}
    return await current.apply_to_job(platform, url, dry_run=dry_run)


@mcp.tool()
async def recycle_browser() -> dict[str, Any]:
    """Close and relaunch Brave between jobs (refused while a job is in flight)."""
    return await (await service()).recycle_browser()


async def ai_runtime() -> AIRuntime:
    current = await service()
    if current.ai is None:
        current.ai = await AIRuntime.for_store(current.store)
    return current.ai


@mcp.tool()
async def lookup_semantic_cache(question: str, kind: str = "screening_qa") -> dict[str, Any]:
    """Local semantic-cache lookup (exact, then cosine >= threshold with the qualifier guard). 0 LLM tokens."""
    hit = await (await ai_runtime()).cache.lookup(kind, question)
    if hit is None:
        return {"hit": False}
    return {"hit": True, "match": hit.match, "similarity": round(hit.similarity, 4),
            "entry": plain(hit.entry.public())}


@mcp.tool()
async def save_semantic_cache_entry(question: str, answer: str, kind: str = "screening_qa") -> dict[str, Any]:
    """Store a human-verified Q&A pair (source='user'; outranks profile and LLM answers)."""
    result = await (await ai_runtime()).cache.put(kind, question, answer, "user")
    return {"outcome": result.outcome, "entry": plain(result.entry.public())}


@mcp.tool()
async def get_llm_router_status() -> dict[str, Any]:
    """Free LLM provider states (unconfigured/healthy/cooldown/circuit_open), usage vs caps, cache stats."""
    return plain(await (await ai_runtime()).status())


# --- Phase 4 HITL (same HITLResolutionService as Telegram and the dashboard) ------------
async def hitl_service() -> Any:
    from backend.app.browser_v2.hitl import HITLResolutionService

    current = await service()
    return HITLResolutionService(current.store, (await ai_runtime()).cache)


@mcp.tool()
async def list_open_hitl_requests(platform: str | None = None, limit: int = 20) -> dict[str, Any]:
    """OPEN human-in-the-loop requests (short ref, portal, company, kind, question, options)."""
    rows, total = await (await service()).store.list_hitl("OPEN", platform, max(1, min(limit, 100)))
    return {"total": total, "items": [plain(row.public()) for row in rows]}


@mcp.tool()
async def resolve_hitl_request(ref_or_id: str, answer: str | None = None, cache_answer: bool = True,
                               action: str = "answer") -> dict[str, Any]:
    """Resolve one OPEN request by short ref or id. action: answer | skip | retry.
    Answers to QUESTION requests are learned into the semantic cache unless cache_answer=False."""
    resolver = await hitl_service()
    hitl = await resolver.store.get_hitl(ref_or_id)
    if hitl is None:
        hitl, problem = await resolver.by_ref(ref_or_id)
        if problem is not None:
            return plain(problem.public())
    assert hitl is not None
    if action == "skip":
        result = await resolver.skip(hitl.id, via="mcp")
    elif action == "retry":
        result = await resolver.retry(hitl.id, via="mcp")
    elif action == "answer" and answer:
        result = await resolver.answer(hitl.id, answer, cache_answer=cache_answer, via="mcp")
    else:
        return {"ok": False, "code": "invalid_request", "message": "action=answer requires an answer"}
    return plain(result.public())


@mcp.tool()
async def get_telegram_status() -> dict[str, Any]:
    """Telegram HITL bot status (configured, polling/conflict state, open HITL count). Never returns the token."""
    from backend.app.telegram_v2.bot import telegram_status

    return plain(await telegram_status((await service()).store))


# --- Phase 5: enrichment + Gmail drafts (READ + DRAFT ONLY; there is no delivery tool) -----
async def quota_processor() -> Any:
    from backend.app.browser_v2.quota import build_quota_processor

    current = await service()
    if current.ai is None:
        current.ai = await ai_runtime()
    return await build_quota_processor(current)


@mcp.tool()
async def enrich_company_contact(company_name: str | None = None, company_domain: str | None = None,
                                 job_url: str | None = None, jd_text: str | None = None,
                                 role_title: str | None = None, allow_paid: bool = False) -> dict[str, Any]:
    """Find a recruiter email: domain cache -> JD/careers page regex -> (allow_paid) credit-capped
    Apollo/Apify/SignalHire. Never guesses an address; NO_EMAIL_FOUND is a normal answer."""
    enrichment = (await quota_processor()).enrichment
    assert enrichment is not None
    result = await enrichment.find_recruiter_email(company_name=company_name, company_domain=company_domain,
                                                   job_url=job_url, jd_text=jd_text, role_title=role_title,
                                                   allow_paid=allow_paid)
    return plain(result.public())


@mcp.tool()
async def create_application_gmail_draft(application_id: str) -> dict[str, Any]:
    """Enrich + save exactly ONE Gmail draft for an application (idempotent). Drafts only — the owner
    reviews and delivers it manually from Gmail; this server cannot deliver email."""
    processor = await quota_processor()
    record = await processor.store.get_application(application_id)
    if record is None:
        return {"ok": False, "code": "not_found"}
    if record.state.value == "APPLYING":
        return {"ok": False, "code": "application_in_flight"}
    profile, _ = await processor.store.load_profile()
    reason, payload = await processor.draft_once(record, profile)
    draft = await processor.store.get_email_draft(record.id)
    return plain({"ok": reason in ("quota_hit_drafted_and_queued", "quota_hit_queued_already_drafted"),
                  "code": reason, "details": payload, "draft": draft.public() if draft else None})


@mcp.tool()
async def list_email_drafts(platform: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Gmail drafts created by the quota fallback, newest first, with each job's retry status."""
    rows, total = await (await service()).store.list_email_drafts(platform, max(1, min(limit, 100)))
    return {"total": total, "items": [plain(row.public()) for row in rows]}


@mcp.tool()
async def get_mail_and_enrichment_status() -> dict[str, Any]:
    """Mail bridge channel (imap | mail_app | unconfigured, permission READ_AND_DRAFT_ONLY) and
    enrichment providers' free-credit usage. Never returns secrets."""
    processor = await quota_processor()
    assert processor.enrichment is not None and processor.mail is not None
    return plain({"mail": processor.mail.status(), "enrichment": await processor.enrichment.status()})


# --- Phase 6A: control agent, event bus, read-only recruiter-reply feed ----------------------
@mcp.tool()
async def agent_control_chat(text: str) -> dict[str, Any]:
    """Send one owner message to the LangGraph control agent (same guardrailed tools as Telegram
    free chat: portal rules, preferences, status, semantic-cache teaching, worker control)."""
    from backend.app.agent_v2.control_graph import ControlAgent

    svc = await service()
    reader = getattr(svc, "mail_reader", None)
    agent = ControlAgent(svc.store, ai=svc.ai, mail_events=getattr(reader, "events", None),
                         event_bus=getattr(svc, "event_bus", None))
    return plain(await agent.run(text[:2000]))


@mcp.tool()
async def get_event_bus_status() -> dict[str, Any]:
    """Active lifecycle event bus backend (postgres | cloudamqp | upstash_redis) and health."""
    from backend.app.events_v2.bus import bus_status

    return plain(await bus_status(getattr(await service(), "event_bus", None)))


@mcp.tool()
async def list_recruiter_replies(limit: int = 20) -> dict[str, Any]:
    """Recent recruiter replies / interview alerts detected by the READ-ONLY inbox watcher."""
    reader = getattr(await service(), "mail_reader", None)
    events = getattr(reader, "events", None)
    rows = await events.recent(("RECRUITER_REPLY", "INTERVIEW"), limit=max(1, min(limit, 100))) if events else []
    return {"items": [plain(row.public()) for row in rows], "permission": "READ_ONLY"}
