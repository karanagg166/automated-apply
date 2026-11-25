"""Python v2 control plane: portal rules, screening facts, applications, worker control,
AI router status, the semantic-cache curation endpoints (Phase 3) and the HITL inbox +
Telegram status (Phase 4; same HITLResolutionService as the Telegram bot).

Thin handlers over browser_v2.store (v2 tables) and the existing candidate
profile repository (screening facts live in candidate_profiles.preferences).
The worker re-reads everything each cycle, so saves never pause it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai_v2.runtime import AIRuntime
from backend.app.ai_v2.schemas import (
    AIStatusRead,
    SemanticCacheCreate,
    SemanticCacheEntryRead,
    SemanticCachePage,
)
from backend.app.ai_v2.semantic_cache import InvalidCacheEntry
from backend.app.browser_v2.hitl import HITLResolutionService, Resolution
from backend.app.browser_v2.rules import PortalRules, within_active_hours
from backend.app.browser_v2.schemas import (
    SCREENING_FIELDS,
    ApplicationPage,
    ApplicationRead,
    AutomationStatus,
    HitlPage,
    HitlRead,
    HitlResolutionRead,
    HitlResolveInput,
    HitlStatusName,
    PortalRulesPatch,
    PortalRulesRead,
    PortalStatus,
    ResumeAuthRead,
    ScreeningProfilePatch,
    ScreeningProfileRead,
    StateEventRead,
    TelegramStatusRead,
    WorkerControlRead,
    WorkerStartInput,
)
from backend.app.browser_v2.service import quota_counts
from backend.app.browser_v2.state import ApplicationState
from backend.app.browser_v2.store import (
    ApplicationQuery,
    PostgresStore,
    RevisionConflict,
    RulesNotFound,
    Store,
    WorkerControl,
    WorkerState,
)
from backend.app.core.security import require_api_token
from backend.app.db.session import get_db_session

router = APIRouter(prefix="/api/v1/v2", tags=["Automation v2"], dependencies=[Depends(require_api_token)])
SessionDep = Annotated[AsyncSession, Depends(get_db_session)]
HEARTBEAT_STALE_SEC = 300


async def get_v2_store(session: SessionDep) -> AsyncIterator[Store]:
    """Borrow the pooled asyncpg connection (no extra Supabase connection)."""
    connection = await session.connection()
    if connection.dialect.name != "postgresql":
        raise HTTPException(503, "Python v2 store requires PostgreSQL")
    raw = await connection.get_raw_connection()
    try:
        store = await PostgresStore.borrowed(raw.driver_connection)
    except RuntimeError:
        raise HTTPException(503, "Python v2 tables are missing: apply migration 004") from None
    yield store


StoreDep = Annotated[Store, Depends(get_v2_store)]


async def get_ai_runtime(store: StoreDep) -> AIRuntime:
    """Cache + router over the same borrowed connection; the ONNX embedder is a process singleton."""
    return await AIRuntime.for_store(store)


AIDep = Annotated[AIRuntime, Depends(get_ai_runtime)]


def worker_read(control: WorkerControl, now: datetime | None = None) -> WorkerControlRead:
    now = now or datetime.now(UTC)
    age = (now - control.heartbeat_at).total_seconds() if control.heartbeat_at else None
    return WorkerControlRead(
        desired_state=control.desired_state.value, dry_run=control.dry_run,
        run_once_requested_at=control.run_once_requested_at, observed_state=control.observed_state,
        heartbeat_at=control.heartbeat_at, heartbeat_age_sec=age,
        stale=age is None or age > HEARTBEAT_STALE_SEC, current_platform=control.current_platform,
        last_cycle_at=control.last_cycle_at, last_error=control.last_error, revision=control.revision)


# --- portal rules -------------------------------------------------------------------
@router.get("/portal-rules", response_model=list[PortalRulesRead])
async def list_portal_rules(store: StoreDep) -> list[PortalRulesRead]:
    return [PortalRulesRead.from_rules(rules) for rules in await store.list_rules()]


@router.patch("/portal-rules/{platform}", response_model=PortalRulesRead,
              responses={404: {"description": "Unknown portal"},
                         409: {"description": "Revision conflict; reload and retry"}})
async def patch_portal_rules(platform: str, data: PortalRulesPatch,
                             store: StoreDep) -> PortalRulesRead:
    current = {r.platform: r for r in await store.list_rules()}.get(platform)
    if current is None:
        raise HTTPException(404, "Unknown portal")
    changes = data.changes()
    merged = {**{name: getattr(current, name) for name in changes}, **changes}
    min_delay = merged.get("min_delay_sec", current.min_delay_sec)
    max_delay = merged.get("max_delay_sec", current.max_delay_sec)
    if max_delay < min_delay:
        raise HTTPException(422, "max_delay_sec must be greater than or equal to min_delay_sec")
    per_hour = merged.get("max_applies_per_hour", current.max_applies_per_hour)
    per_day = merged.get("max_applies_per_day", current.max_applies_per_day)
    if per_hour > per_day:
        raise HTTPException(422, "max_applies_per_hour cannot exceed max_applies_per_day")
    try:
        updated = await store.update_rules(platform, changes, data.revision)
    except RulesNotFound:
        raise HTTPException(404, "Unknown portal") from None
    except RevisionConflict as exc:
        raise HTTPException(409, f"Rules changed (current revision {exc.current}); reload and retry") from None
    return PortalRulesRead.from_rules(updated)


# --- screening facts ----------------------------------------------------------------
def screening_read(profile: Any) -> ScreeningProfileRead:
    prefs = dict(profile.preferences or {}) if profile is not None else {}
    values = {name: prefs[name] for name in SCREENING_FIELDS if prefs.get(name) is not None}
    return ScreeningProfileRead(**values, version=profile.version if profile is not None else 0,
                                has_profile=profile is not None)


@router.get("/screening-profile", response_model=ScreeningProfileRead)
async def get_screening_profile(session: SessionDep) -> ScreeningProfileRead:
    from backend.app.repositories.candidate_profile import CandidateProfileRepository

    return screening_read(await CandidateProfileRepository(session).get_primary_profile())


@router.patch("/screening-profile", response_model=ScreeningProfileRead,
              responses={404: {"description": "Create the candidate profile first"},
                         409: {"description": "Profile version conflict"}})
async def patch_screening_profile(data: ScreeningProfilePatch,
                                  session: SessionDep) -> ScreeningProfileRead:
    from backend.app.repositories.candidate_profile import (
        CandidateProfileRepository,
        ProfileConflictError,
        ProfileNotFoundError,
    )
    from backend.app.schemas.candidate_profile import CandidateProfileUpdate

    repository = CandidateProfileRepository(session)
    try:
        profile = await repository.update_primary_profile(
            CandidateProfileUpdate(preferences=data.changes()), data.version)
    except ProfileNotFoundError:
        raise HTTPException(404, "Create the candidate profile first") from None
    except ProfileConflictError:
        raise HTTPException(409, "Profile changed; reload and retry") from None
    return screening_read(profile)


# --- applications -------------------------------------------------------------------
@router.get("/applications", response_model=ApplicationPage)
async def list_applications(
    store: StoreDep,
    platform: Annotated[str | None, Query(max_length=40, pattern=r"^[a-z][a-z0-9_]{1,39}$")] = None,
    state: ApplicationState | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> ApplicationPage:
    rows, total = await store.list_applications(ApplicationQuery(
        platform=platform, state=state.value if state else None, since=since, until=until,
        limit=limit, offset=offset))
    return ApplicationPage(items=[ApplicationRead(**row.public()) for row in rows], total=total,
                           limit=limit, offset=offset)


@router.get("/applications/{application_id}/events", response_model=list[StateEventRead])
async def application_events(application_id: str, store: StoreDep
                             ) -> list[StateEventRead]:
    from uuid import UUID

    try:
        UUID(application_id)
    except ValueError:
        if not application_id.startswith("mem-"):
            raise HTTPException(404, "Application not found") from None
    events = await store.application_events(application_id)
    if events is None:
        raise HTTPException(404, "Application not found")
    return [StateEventRead(**event) for event in events]


# --- status -------------------------------------------------------------------------
async def portal_status(store: Store, rules: PortalRules, now: datetime) -> PortalStatus:
    counts = await quota_counts(store, rules, now)
    return PortalStatus(
        platform=rules.platform, enabled=rules.enabled, auto_apply_enabled=rules.auto_apply_enabled,
        auth_status=rules.auth_status, auth_checked_at=rules.auth_checked_at,
        portal_limit_hit_at=rules.portal_limit_hit_at, max_applies_per_day=rules.max_applies_per_day,
        max_applies_per_hour=rules.max_applies_per_hour, within_active_hours=within_active_hours(rules, now),
        waiting_for_user=await store.count_state(ApplicationState.WAITING_FOR_USER, rules.platform),
        **counts)


@router.get("/status", response_model=AutomationStatus)
async def automation_status(store: StoreDep) -> AutomationStatus:
    now = datetime.now(UTC)
    portals = [await portal_status(store, rules, now) for rules in await store.list_rules()]
    return AutomationStatus(
        generated_at=now, waiting_for_user=await store.count_state(ApplicationState.WAITING_FOR_USER),
        worker=worker_read(await store.get_worker_control(), now), portals=portals)


# --- worker control -----------------------------------------------------------------
@router.get("/worker", response_model=WorkerControlRead)
async def get_worker(store: StoreDep) -> WorkerControlRead:
    return worker_read(await store.get_worker_control())


@router.post("/worker/start", response_model=WorkerControlRead)
async def start_worker(store: StoreDep, data: WorkerStartInput | None = None) -> WorkerControlRead:
    dry_run = data.dry_run if data is not None else None
    return worker_read(await store.set_worker_control(WorkerState.RUNNING, dry_run=dry_run))


@router.post("/worker/pause", response_model=WorkerControlRead)
async def pause_worker(store: StoreDep) -> WorkerControlRead:
    return worker_read(await store.set_worker_control(WorkerState.PAUSED))


@router.post("/worker/stop", response_model=WorkerControlRead)
async def stop_worker(store: StoreDep) -> WorkerControlRead:
    return worker_read(await store.set_worker_control(WorkerState.STOPPED))


@router.post("/worker/run-once", response_model=WorkerControlRead)
async def run_worker_once(store: StoreDep) -> WorkerControlRead:
    return worker_read(await store.set_worker_control(run_once=True))


# --- AI router + semantic cache (Phase 3) ---------------------------------------------
@router.get("/ai/status", response_model=AIStatusRead)
async def ai_status(ai: AIDep) -> AIStatusRead:
    return AIStatusRead.model_validate(await ai.status())


@router.get("/semantic-cache", response_model=SemanticCachePage)
async def list_semantic_cache(
    ai: AIDep,
    kind: Annotated[str | None, Query(pattern=r"^[a-z][a-z0-9_]{1,39}$")] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> SemanticCachePage:
    entries, total = await ai.cache.store.list_entries(kind, q, limit, offset)
    return SemanticCachePage(items=[SemanticCacheEntryRead(**entry.public()) for entry in entries],
                             total=total, limit=limit, offset=offset)


@router.post("/semantic-cache", response_model=SemanticCacheEntryRead, status_code=201,
             responses={422: {"description": "Invalid question/answer"}})
async def create_semantic_cache_entry(data: SemanticCacheCreate, ai: AIDep) -> SemanticCacheEntryRead:
    """Teach a verified Q&A pair (source='user' outranks profile/LLM answers)."""
    try:
        result = await ai.cache.put(data.kind, data.question_text, data.answer_text, "user")
    except InvalidCacheEntry as exc:
        raise HTTPException(422, str(exc)) from None
    return SemanticCacheEntryRead(**result.entry.public())


@router.delete("/semantic-cache/{entry_id}", status_code=204, response_class=Response,
               responses={404: {"description": "Entry not found"}})
async def delete_semantic_cache_entry(entry_id: str, ai: AIDep) -> Response:
    from uuid import UUID

    try:
        UUID(entry_id)
    except ValueError:
        raise HTTPException(404, "Entry not found") from None
    if not await ai.cache.store.delete(entry_id):
        raise HTTPException(404, "Entry not found")
    return Response(status_code=204)


# --- Phase 4: HITL inbox + Telegram status ---------------------------------------------
PLATFORM_PATTERN = r"^[a-z][a-z0-9_]{1,39}$"
RESOLUTION_ERRORS = {"not_found": 404, "already_resolved": 409, "invalid_option": 422, "empty_answer": 422,
                     "answer_too_long": 422, "wrong_kind": 422}


def resolution_read(result: Resolution) -> HitlResolutionRead:
    if not result.ok:
        status = RESOLUTION_ERRORS.get(result.code, 422)
        raise HTTPException(status, result.message)  # invalid_option lists the numbered options
    return HitlResolutionRead.model_validate(result.public())


def hitl_id_or_404(hitl_id: str) -> str:
    from uuid import UUID

    try:
        return str(UUID(hitl_id))
    except ValueError:
        raise HTTPException(404, "HITL request not found") from None


async def get_hitl_service(store: StoreDep, ai: AIDep) -> HITLResolutionService:
    return HITLResolutionService(store, ai.cache)


HITLDep = Annotated[HITLResolutionService, Depends(get_hitl_service)]
RESOLVE_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"description": "HITL request not found"}, 409: {"description": "Already resolved"},
    422: {"description": "Invalid option / empty answer / wrong kind"}}


@router.get("/telegram/status", response_model=TelegramStatusRead)
async def get_telegram_status(store: StoreDep) -> TelegramStatusRead:
    """Bot config + long-polling state persisted by the worker. Never returns the token."""
    from backend.app.telegram_v2.bot import telegram_status

    return TelegramStatusRead.model_validate(await telegram_status(store))


@router.get("/hitl", response_model=HitlPage)
async def list_hitl_requests(
    store: StoreDep,
    status: HitlStatusName | None = "OPEN",
    platform: Annotated[str | None, Query(max_length=40, pattern=PLATFORM_PATTERN)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> HitlPage:
    rows, total = await store.list_hitl(status, platform, limit, offset)
    return HitlPage(items=[HitlRead.model_validate(row.public()) for row in rows], total=total,
                    limit=limit, offset=offset)


@router.post("/hitl/{hitl_id}/resolve", response_model=HitlResolutionRead, responses=RESOLVE_RESPONSES)
async def resolve_hitl_request(hitl_id: str, data: HitlResolveInput, hitl: HITLDep) -> HitlResolutionRead:
    """Answer & resume: validates options, learns into the semantic cache (cache_answer) and re-enqueues."""
    return resolution_read(await hitl.answer(hitl_id_or_404(hitl_id), data.answer,
                                             cache_answer=data.cache_answer, via="dashboard"))


@router.post("/hitl/{hitl_id}/skip", response_model=HitlResolutionRead, responses=RESOLVE_RESPONSES)
async def skip_hitl_request(hitl_id: str, hitl: HITLDep) -> HitlResolutionRead:
    return resolution_read(await hitl.skip(hitl_id_or_404(hitl_id), via="dashboard"))


@router.post("/hitl/{hitl_id}/retry", response_model=HitlResolutionRead, responses=RESOLVE_RESPONSES)
async def retry_hitl_request(hitl_id: str, hitl: HITLDep) -> HitlResolutionRead:
    return resolution_read(await hitl.retry(hitl_id_or_404(hitl_id), via="dashboard"))


@router.post("/portal-rules/{platform}/resume-auth", response_model=ResumeAuthRead,
             responses={404: {"description": "Unknown portal"}})
async def resume_portal_auth(platform: str, hitl: HITLDep) -> ResumeAuthRead:
    """Same as Telegram /resume <portal>: auth_status -> UNKNOWN, open AUTH requests resolved."""
    outcome = await hitl.resume_portal(platform, via="dashboard")
    if not outcome.ok:
        raise HTTPException(404, "Unknown portal")
    return ResumeAuthRead.model_validate(outcome.public())
