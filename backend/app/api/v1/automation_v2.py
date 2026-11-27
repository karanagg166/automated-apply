"""Python v2 control plane: portal rules, screening facts, applications, worker control,
AI router status, the semantic-cache curation endpoints (Phase 3), the HITL inbox +
Telegram status (Phase 4; same HITLResolutionService as the Telegram bot) and the
Phase 5 quota fallback: Gmail drafts (READ + DRAFT ONLY), enrichment and mail status, and
Phase 6A: the LangGraph control agent chat, event-bus status and READ-ONLY recruiter replies.

Thin handlers over browser_v2.store (v2 tables) and the existing candidate
profile repository (screening facts live in candidate_profiles.preferences).
The worker re-reads everything each cycle, so saves never pause it.

Composer only: the handlers live in ``backend.app.api.v1.v2.routers.*`` and the shared
dependencies in ``backend.app.api.v1.v2.deps``; this module builds the single ``/api/v1/v2``
router (same prefix, tags and ``require_api_token`` dependency) in the original route order and
re-exports every name (tests use ``app.dependency_overrides[get_v2_store]`` etc. from here).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.app.api.v1.v2.deps import (
    HEARTBEAT_STALE_SEC,
    PLATFORM_PATTERN,
    AIDep,
    EnrichmentDep,
    HITLDep,
    MailDep,
    SessionDep,
    StoreDep,
    get_ai_runtime,
    get_enrichment_service,
    get_hitl_service,
    get_mail_service,
    get_v2_store,
    mail_config,
    worker_read,
)
from backend.app.api.v1.v2.routers import (
    agent,
    ai_cache,
    applications,
    events,
    hitl,
    mail,
    ops,
    portals,
    profile,
    proof,
    watchers,
    worker,
)
from backend.app.api.v1.v2.routers.agent import agent_chat, events_status
from backend.app.api.v1.v2.routers.ai_cache import (
    ai_status,
    create_semantic_cache_entry,
    delete_semantic_cache_entry,
    list_semantic_cache,
)
from backend.app.api.v1.v2.routers.applications import (
    application_detail,
    application_events,
    applications_summary,
    list_applications,
)
from backend.app.api.v1.v2.routers.hitl import (
    RESOLUTION_ERRORS,
    RESOLVE_RESPONSES,
    get_telegram_status,
    hitl_id_or_404,
    list_hitl_requests,
    resolution_read,
    resolve_hitl_request,
    resume_portal_auth,
    retry_hitl_request,
    skip_hitl_request,
)
from backend.app.api.v1.v2.routers.mail import (
    DRAFT_NOW_CODES,
    draft_now,
    enrichment_status,
    list_email_drafts,
    mail_replies,
    mail_status,
)
from backend.app.api.v1.v2.routers.portals import list_portal_rules, patch_portal_rules
from backend.app.api.v1.v2.routers.profile import (
    get_screening_profile,
    patch_screening_profile,
    screening_read,
)
from backend.app.api.v1.v2.routers.worker import (
    automation_status,
    get_worker,
    pause_worker,
    portal_status,
    run_worker_once,
    start_worker,
    stop_worker,
)
from backend.app.core.security import require_api_token

__all__ = [
    "DRAFT_NOW_CODES",
    "HEARTBEAT_STALE_SEC",
    "PLATFORM_PATTERN",
    "RESOLUTION_ERRORS",
    "RESOLVE_RESPONSES",
    "AIDep",
    "EnrichmentDep",
    "HITLDep",
    "MailDep",
    "SessionDep",
    "StoreDep",
    "agent_chat",
    "ai_status",
    "application_detail",
    "application_events",
    "applications_summary",
    "automation_status",
    "create_semantic_cache_entry",
    "delete_semantic_cache_entry",
    "draft_now",
    "enrichment_status",
    "events_status",
    "get_ai_runtime",
    "get_enrichment_service",
    "get_hitl_service",
    "get_mail_service",
    "get_screening_profile",
    "get_telegram_status",
    "get_v2_store",
    "get_worker",
    "hitl_id_or_404",
    "list_applications",
    "list_email_drafts",
    "list_hitl_requests",
    "list_portal_rules",
    "list_semantic_cache",
    "mail_config",
    "mail_replies",
    "mail_status",
    "patch_portal_rules",
    "patch_screening_profile",
    "pause_worker",
    "portal_status",
    "resolution_read",
    "resolve_hitl_request",
    "resume_portal_auth",
    "retry_hitl_request",
    "router",
    "run_worker_once",
    "screening_read",
    "skip_hitl_request",
    "start_worker",
    "stop_worker",
    "worker_read",
]

router = APIRouter(prefix="/api/v1/v2", tags=["Automation v2"], dependencies=[Depends(require_api_token)])
# Original registration order: /mail/replies came after the Phase 6A agent routes.
for _sub in (portals.router, profile.router, applications.router, worker.router, ai_cache.router, hitl.router,
             mail.router, agent.router, mail.replies_router,
             # Milestone 2: ops command center surface.
             ops.router, events.router, watchers.router, proof.router):
    router.include_router(_sub)
del _sub
