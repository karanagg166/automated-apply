"""Owner-authenticated candidate context, project configuration and answer retrieval."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.candidate_context.common import ContextError
from backend.app.candidate_context.configuration import (
    CandidateConfiguration,
)
from backend.app.candidate_context.persistence import SQLRecordStore
from backend.app.candidate_context.repository import AuthorizedCheckoutReader
from backend.app.candidate_context.service import CandidateContextService
from backend.app.candidate_context.templates import load_project_facts
from backend.app.dashboard.router import OwnerRoute
from backend.app.db.session import get_db_session

router = APIRouter(prefix="/candidate-context", tags=["Candidate Context"], route_class=OwnerRoute)


class ConfigurationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configuration: CandidateConfiguration
    expected_revision: int = Field(ge=0)


class ProjectApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: str = Field(min_length=1, max_length=120)
    fact_ids: list[str] = Field(min_length=1, max_length=100)
    owner_confirmed: bool = True


class ProjectBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_configuration_revision: int = Field(ge=0)


def get_service(session: AsyncSession) -> CandidateContextService:
    reader = AuthorizedCheckoutReader({
        # Map configured repositories to local checkouts when authorized
    })
    return CandidateContextService(SQLRecordStore(session), reader=reader)



@router.get("/configuration")
async def get_configuration(session: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    service = get_service(session)
    record = await service.configuration()
    return record.model_dump(mode="json")


@router.put("/configuration")
async def update_configuration(
    data: ConfigurationUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    service = get_service(session)
    try:
        updated = await service.save_configuration(
            data.configuration,
            expected_revision=data.expected_revision,
            owner_ref="owner",
            source="owner_dashboard",
        )
        return updated.model_dump(mode="json")
    except ContextError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/projects")
async def list_projects(session: AsyncSession = Depends(get_db_session)) -> list[dict[str, Any]]:
    service = get_service(session)
    config_record = await service.configuration()
    results = []
    for p in config_record.configuration.projects:
        pk = await service.project(p.id)
        results.append({
            "project": p.model_dump(mode="json"),
            "revision": pk.revision,
            "candidate_revision": pk.candidate.revision if pk.candidate else None,
            "approved_revision": pk.approved.revision if pk.approved else None,
            "last_checked_commit": pk.last_checked_commit,
            "built_at": pk.built_at,
            "fact_count": len(pk.candidate.facts) if pk.candidate else 0,
            "approved_fact_count": len(pk.approved.facts) if pk.approved else 0,
        })
    return results


@router.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    service = get_service(session)
    try:
        pk = await service.project(project_id)
        return pk.model_dump(mode="json")
    except ContextError as exc:
        raise HTTPException(400, str(exc)) from None


@router.post("/projects/{project_id}/build")
async def build_project(
    project_id: str,
    data: ProjectBuildRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    service = get_service(session)
    root = Path(__file__).resolve().parents[3]
    config_record = await service.configuration()
    project = next((p for p in config_record.configuration.projects if p.id == project_id), None)
    if not project:
        raise HTTPException(404, "project_not_found")
    owner_facts = ()
    if project.context_file:
        try:
            owner_facts = load_project_facts(root, project)
        except ContextError as exc:
            raise HTTPException(422, str(exc)) from None
    try:
        status_code, knowledge = await service.build(
            project_id,
            expected_configuration_revision=data.expected_configuration_revision,
            owner_facts=owner_facts,
        )
        return {"status": status_code, "project": knowledge.model_dump(mode="json")}
    except ContextError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/projects/{project_id}/approve")
async def approve_project(
    project_id: str,
    data: ProjectApproveRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    service = get_service(session)
    try:
        approval = await service.approve(
            project_id,
            expected_revision=data.expected_revision,
            fact_ids=tuple(data.fact_ids),
            owner_ref="owner",
            owner_confirmed=data.owner_confirmed,
        )
        return approval.model_dump(mode="json")
    except ContextError as exc:
        raise HTTPException(409, str(exc)) from None


@router.get("/answer")
async def get_answer(
    question: str = Query(..., min_length=1, max_length=2000),
    project_rank: int | None = Query(None, ge=1, le=30),
    max_words: int = Query(100, ge=10, le=500),
    max_characters: int = Query(2000, ge=50, le=10000),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    service = get_service(session)
    answer = await service.answer(
        question,
        project_rank=project_rank,
        max_words=max_words,
        max_characters=max_characters,
    )
    return answer.model_dump(mode="json")
