"""Transaction-neutral profile persistence with atomic compare-and-swap updates."""

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.candidate_profile import CandidateProfile
from backend.app.schemas.candidate_profile import (
    CandidateProfileCreate,
    CandidateProfileUpdate,
)


class ProfileNotFoundError(Exception):
    pass


class ProfileConflictError(Exception):
    pass


class ProfilePreconditionError(Exception):
    pass


class CandidateProfileRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_primary_profile(self) -> CandidateProfile | None:
        return await self.session.scalar(select(CandidateProfile).where(
            CandidateProfile.singleton_key == "primary"
        ).execution_options(populate_existing=True))

    async def create_primary_profile(self, data: CandidateProfileCreate) -> CandidateProfile:
        insert = pg_insert if self.session.get_bind().dialect.name == "postgresql" else sqlite_insert
        statement = insert(CandidateProfile).values(**data.model_dump(mode="json")).on_conflict_do_nothing(
            index_elements=[CandidateProfile.singleton_key]
        ).returning(CandidateProfile)
        profile = (await self.session.execute(statement)).scalar_one_or_none()
        if profile is None:
            raise ProfileConflictError("Primary profile already exists")
        return profile

    async def _replace(self, current, data, expected_version):
        values = data.model_dump(mode="json")
        unchanged = all(getattr(current, key) == value for key, value in values.items())
        if expected_version is None:
            if unchanged:
                return current
            raise ProfilePreconditionError("Supply If-Match with the current profile version")
        if current.version != expected_version:
            raise ProfileConflictError("Profile version changed; retrieve it before retrying")
        # Even a no-op with a supplied version must check it atomically.
        changes = {"version": expected_version, "updated_at": current.updated_at} if unchanged else {
            **values, "version": expected_version + 1, "updated_at": datetime.now(timezone.utc)
        }
        result = await self.session.execute(update(CandidateProfile).where(
            CandidateProfile.id == current.id, CandidateProfile.version == expected_version
        ).values(**changes).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise ProfileConflictError("Profile version changed; retrieve it before retrying")
        await self.session.refresh(current)
        return current

    async def update_primary_profile(self, data: CandidateProfileUpdate, expected_version: int):
        current = await self.get_primary_profile()
        if current is None:
            raise ProfileNotFoundError("No candidate profile saved")
        values = CandidateProfileCreate.model_validate(current).model_dump(mode="json")
        patch = data.model_dump(mode="json", exclude_unset=True)
        if "preferences" in patch:
            patch["preferences"] = {**values["preferences"], **patch["preferences"]}
        values.update(patch)
        return await self._replace(current, CandidateProfileCreate.model_validate(values), expected_version)

    async def upsert_primary_profile(self, data: CandidateProfileCreate, expected_version: int | None = None):
        current = await self.get_primary_profile()
        if current is None:
            if expected_version is not None:
                raise ProfileConflictError("Profile no longer exists")
            return await self.create_primary_profile(data), True
        return await self._replace(current, data, expected_version), False
