"""Generic base repository defining common async database interactions."""

from typing import Generic, TypeVar, Type, Any
from uuid import UUID
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.models.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """Generic async repository providing standard CRUD operations."""

    def __init__(self, model: Type[ModelType], session: AsyncSession) -> None:
        self.model = model
        self.session = session

    async def get_by_id(self, id_: UUID) -> ModelType | None:
        """Fetch a single record by its UUID primary key."""
        stmt = select(self.model).where(self.model.id == id_)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create(self, **kwargs: Any) -> ModelType:
        """Instantiate and persist a new record."""
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def delete(self, id_: UUID) -> bool:
        """Delete a record by UUID."""
        stmt = delete(self.model).where(self.model.id == id_)
        result = await self.session.execute(stmt)
        return result.rowcount > 0
