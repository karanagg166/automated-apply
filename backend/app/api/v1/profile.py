"""Authenticated primary profile API. Transaction ownership stays in get_db_session."""

from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import ValidationError
from backend.app.core.security import require_api_token
from backend.app.db.session import get_db_session
from backend.app.repositories.candidate_profile import (
    ProfileConflictError, ProfileNotFoundError, ProfilePreconditionError,
)
from backend.app.repositories.job import JobRepository
from backend.app.schemas.candidate_profile import CandidateProfileCreate, CandidateProfileRead, CandidateProfileUpdate
from backend.app.services.application_assistant import ApplicationAssistant, JobMatchResult
from backend.app.services.candidate_profile_service import CandidateProfileService


class ProtectedProfileRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def protected(request: Request):
            # Authenticate before reading or validating potentially sensitive request data.
            await require_api_token(request)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 65536:
                    raise HTTPException(413, "Profile request exceeds 64 KiB")
            request._body = bytes(body)
            try:
                response = await handler(request)
            except ValidationError as exc:
                raise HTTPException(422, "Resulting profile is invalid or exceeds 64 KiB") from exc
            except ProfileNotFoundError as exc:
                raise HTTPException(404, str(exc)) from exc
            except ProfileConflictError as exc:
                raise HTTPException(409, str(exc)) from exc
            except ProfilePreconditionError as exc:
                raise HTTPException(428, str(exc)) from exc
            response.headers["Cache-Control"] = "no-store"
            return response
        return protected


router = APIRouter(prefix="/api/v1", tags=["Candidate profile"], route_class=ProtectedProfileRoute,
                   dependencies=[Depends(require_api_token)],
                   responses={401: {"description": "Missing or invalid bearer token"},
                              503: {"description": "API token is not configured"},
                              404: {"description": "Profile or job not found"},
                              409: {"description": "Profile version conflict"},
                              428: {"description": "If-Match version required"},
                              413: {"description": "Payload exceeds 64 KiB"}})


def parse_version(value: str | None, required: bool = False) -> int | None:
    if value is None:
        if required:
            raise HTTPException(428, "Supply If-Match with the current profile version")
        return None
    # Accept a strong quoted numeric ETag, as returned by GET/PUT/PATCH.
    if len(value) < 3 or len(value) > 12 or not value.startswith('"') or not value.endswith('"') or not value[1:-1].isascii() or not value[1:-1].isdigit():
        raise HTTPException(422, 'If-Match must be a quoted positive integer, e.g. "1"')
    version = int(value[1:-1])
    if version < 1 or version > 2147483646:
        raise HTTPException(422, "Invalid profile version")
    return version


@router.get("/profile", response_model=CandidateProfileRead)
async def get_profile(response: Response, session: AsyncSession = Depends(get_db_session)):
    profile = await CandidateProfileService(session).get_profile()
    response.headers["ETag"] = f'"{profile.version}"'
    return profile


@router.put("/profile", response_model=CandidateProfileRead, responses={201: {"description": "Profile created"}})
async def put_profile(data: CandidateProfileCreate, response: Response,
                      if_match: str | None = Header(default=None),
                      session: AsyncSession = Depends(get_db_session)):
    profile, created = await CandidateProfileService(session).upsert_profile(data, parse_version(if_match))
    response.status_code = 201 if created else 200
    response.headers["ETag"] = f'"{profile.version}"'
    return profile


@router.patch("/profile", response_model=CandidateProfileRead)
async def patch_profile(data: CandidateProfileUpdate, response: Response,
                        if_match: str | None = Header(default=None),
                        session: AsyncSession = Depends(get_db_session)):
    profile = await CandidateProfileService(session).update_profile(data, parse_version(if_match, required=True))
    response.headers["ETag"] = f'"{profile.version}"'
    return profile


@router.post("/jobs/{job_id}/match", response_model=JobMatchResult)
async def match_saved_profile(job_id: UUID, session: AsyncSession = Depends(get_db_session)):
    job = await JobRepository(session).get_by_id(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    profile = await CandidateProfileService(session).to_application_profile()
    # Return the result without persisting candidate-derived details in public job routes.
    return ApplicationAssistant(session).calculate_match(job, profile)
