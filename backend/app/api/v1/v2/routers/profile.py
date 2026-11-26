"""v2 control plane: screening facts (stored in candidate_profiles.preferences) and the Phase 9D
portal profile-sync status / on-demand request (the sync itself only ever runs in the worker)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.app.api.v1.v2.deps import SessionDep, StoreDep
from backend.app.browser_v2.schemas import (
    SCREENING_FIELDS,
    ScreeningProfilePatch,
    ScreeningProfileRead,
)

router = APIRouter()


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


# --- Phase 9D: portal profile sync ------------------------------------------------------
WORKER_ONLY = {"code": "worker_only",
               "message": "Profile sync runs only inside the v2 worker (it owns the Brave profile). Start the "
                          "worker, or ask the Telegram agent / run `cli sync-profile` with the worker stopped."}


class ProfileSyncRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portals: list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{1,39}$")]] = Field(min_length=1, max_length=10)
    dry_run: bool = True


def get_profile_sync_requester() -> Any:
    """The worker's ProfileSyncRequester (scheduler). None in the API process -> 409 worker_only.

    Overridden via ``app.dependency_overrides`` when a requester is co-hosted (and in tests)."""
    return None


ProfileSyncRequesterDep = Annotated[Any, Depends(get_profile_sync_requester)]


@router.get("/profile-sync/status")
async def profile_sync_status(store: StoreDep) -> dict[str, Any]:
    from backend.app.browser_v2.profile_sync.status import sync_status

    return await sync_status(store)


@router.post("/profile-sync/request", status_code=202,
             responses={409: {"description": "No profile-sync scheduler in this process (worker_only)"},
                        422: {"description": "Unknown portal"}})
async def request_profile_sync(body: ProfileSyncRequestBody,
                               requester: ProfileSyncRequesterDep) -> dict[str, Any]:
    from backend.app.browser_v2.profile_sync.adapters import PROFILE_PORTALS

    unknown = sorted(set(body.portals) - set(PROFILE_PORTALS))
    if unknown:
        raise HTTPException(422, f"Unknown profile-sync portal(s): {', '.join(unknown)}")
    if requester is None:
        raise HTTPException(409, WORKER_ONLY)
    summary = await requester.request_sync(body.portals, dry_run=body.dry_run, trigger="dashboard")
    return {"queued": True, "portals": list(dict.fromkeys(body.portals)), "dry_run": body.dry_run,
            "summary": summary}
