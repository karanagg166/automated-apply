"""Private candidate resources, evidence and reviewable answer drafts."""
from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.ai.schemas import AnswerGenerationResult, DraftRead, DraftReviewUpdate, GenerateRequest, ResolveRequest
from backend.app.api.v1.profile import ProtectedProfileRoute
from backend.app.core.config import get_settings
from backend.app.core.security import require_api_token
from backend.app.db.session import get_db_session
from backend.app.repositories.candidate_knowledge import CandidateKnowledgeRepository
from backend.app.schemas.candidate_resources import (
    EvidenceList, EvidencePatch, EvidenceRead, EvidenceWrite, ResolvedLink,
    ResourceList, ResourceRead, ResourceWrite,
)
from backend.app.services.application_answer_service import ApplicationAnswerService
from backend.app.services.profile_link_resolver import ALIASES, ProfileLinkResolver

router = APIRouter(prefix="/api/v1", tags=["Application answers"], route_class=ProtectedProfileRoute,
                   dependencies=[Depends(require_api_token)])


def answer_service(session: AsyncSession = Depends(get_db_session)):
    return ApplicationAnswerService(session)


@router.get("/candidate/resources", response_model=ResourceList)
async def list_resources(offset: int = Query(0, ge=0, le=100000), limit: int = Query(25, ge=1, le=100),
                         session: AsyncSession = Depends(get_db_session)):
    repo = CandidateKnowledgeRepository(session)
    profile = await repo.profile()
    all_resources = await repo.resources(profile.id)
    resolver = ProfileLinkResolver(profile, all_resources, get_settings())
    return ResourceList(resources=await repo.resources(profile.id, offset, limit),
                        resolved_links=[resolver.resolved(kind) for kind in ALIASES], offset=offset, limit=limit)


@router.post("/candidate/resources", response_model=ResourceRead | ResolvedLink)
async def save_resource(data: ResourceWrite, session: AsyncSession = Depends(get_db_session)):
    return await CandidateKnowledgeRepository(session).save_resource(data)


@router.post("/candidate/resources/resolve", response_model=AnswerGenerationResult)
async def resolve_resource(data: ResolveRequest, session: AsyncSession = Depends(get_db_session)):
    repo = CandidateKnowledgeRepository(session)
    profile = await repo.profile()
    return ProfileLinkResolver(profile, await repo.resources(profile.id), get_settings()).resolve(data.question)


@router.get("/candidate/evidence", response_model=EvidenceList)
async def list_evidence(offset: int = Query(0, ge=0, le=100000), limit: int = Query(25, ge=1, le=100),
                        session: AsyncSession = Depends(get_db_session)):
    repo = CandidateKnowledgeRepository(session)
    profile = await repo.profile()
    items = await repo.evidence(profile.id, offset, limit)
    return EvidenceList(verified=[i for i in items if i.user_confirmed],
                        unverified=[i for i in items if not i.user_confirmed], offset=offset, limit=limit)


@router.post("/candidate/evidence", response_model=EvidenceRead, status_code=201)
async def add_evidence(data: EvidenceWrite, session: AsyncSession = Depends(get_db_session)):
    return await CandidateKnowledgeRepository(session).add_evidence(data)


@router.patch("/candidate/evidence/{evidence_id}", response_model=EvidenceRead)
async def patch_evidence(evidence_id: UUID, data: EvidencePatch, session: AsyncSession = Depends(get_db_session)):
    return await CandidateKnowledgeRepository(session).patch_evidence(evidence_id, data)


@router.post("/application-answers/generate", response_model=AnswerGenerationResult)
async def generate_answer(data: GenerateRequest, service: ApplicationAnswerService = Depends(answer_service)):
    return await service.generate(data)


def draft_read(item, profile):
    return DraftRead.model_validate({**{k: getattr(item, k) for k in DraftRead.model_fields if k != "stale"},
                                     "stale": item.candidate_profile_version != profile.version})


@router.get("/application-answers/drafts", response_model=list[DraftRead])
async def list_drafts(offset: int = Query(0, ge=0, le=100000), limit: int = Query(25, ge=1, le=100),
                      session: AsyncSession = Depends(get_db_session)):
    repo = CandidateKnowledgeRepository(session)
    profile = await repo.profile()
    return [draft_read(i, profile) for i in await repo.drafts(profile.id, offset, limit)]


@router.patch("/application-answers/drafts/{draft_id}", response_model=DraftRead)
async def review_draft(draft_id: UUID, data: DraftReviewUpdate, session: AsyncSession = Depends(get_db_session)):
    repo = CandidateKnowledgeRepository(session)
    item = await repo.review_draft(draft_id, data.review_status)
    return draft_read(item, await repo.profile())
