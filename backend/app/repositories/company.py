"""Repository for Company entity operations."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.company import Company
from backend.app.repositories.base import BaseRepository


class CompanyRepository(BaseRepository[Company]):
    """Data access repository for companies."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Company, session)

    async def get_by_domain(self, domain: str) -> Company | None:
        """Find company by domain name (case-insensitive)."""
        if not domain:
            return None
        cleaned = domain.strip().lower()
        stmt = select(Company).where(Company.domain == cleaned)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def get_by_name(self, name: str) -> Company | None:
        """Find company by exact or lower-cased name."""
        if not name:
            return None
        cleaned = name.strip()
        stmt = select(Company).where(func.lower(Company.name) == cleaned.lower())
        candidates = list((await self.session.scalars(stmt.limit(2))).all())
        return candidates[0] if len(candidates) == 1 else None

    async def get_or_create(
        self,
        name: str,
        domain: str | None = None,
        linkedin_url: str | None = None,
        email_pattern: str | None = None,
        is_catch_all: bool = False,
    ) -> tuple[Company, bool]:
        """Look up existing company by domain or name, or create a new one.
        Returns (company, was_created).
        """
        existing = None
        if domain:
            existing = await self.get_by_domain(domain)
        ambiguous_name = False
        if not existing:
            matches = list(
                (
                    await self.session.scalars(
                        select(Company)
                        .where(func.lower(Company.name) == name.strip().lower())
                        .limit(2)
                    )
                ).all()
            )
            ambiguous_name = len(matches) > 1
            candidate = matches[0] if len(matches) == 1 else None
            if ambiguous_name and not domain:
                unresolved = list(
                    (
                        await self.session.scalars(
                            select(Company)
                            .where(
                                func.lower(Company.name) == name.strip().lower(),
                                Company.domain.is_(None),
                            )
                            .limit(2)
                        )
                    ).all()
                )
                candidate = unresolved[0] if len(unresolved) == 1 else None
            if (
                candidate
                and domain
                and (candidate.metadata_ or {}).get("identity_review_required")
            ):
                candidate = None
            # Equal display names do not override conflicting known company domains.
            if candidate and (
                not domain
                or not candidate.domain
                or candidate.domain == domain.strip().lower()
            ):
                existing = candidate

        if existing:
            # Update missing attributes if discovered
            updated = False
            if domain and not existing.domain:
                existing.domain = domain.strip().lower()
                updated = True
            if linkedin_url and not existing.linkedin_url:
                existing.linkedin_url = linkedin_url
                updated = True
            if email_pattern and not existing.email_pattern:
                existing.email_pattern = email_pattern
                existing.is_catch_all = is_catch_all
                updated = True
            if updated:
                await self.session.flush()
            return existing, False

        # Create new
        new_company = await self.create(
            name=name.strip(),
            domain=domain.strip().lower() if domain else None,
            linkedin_url=linkedin_url,
            email_pattern=email_pattern,
            is_catch_all=is_catch_all,
            metadata_={
                "identity_review_required": True,
                "identity_resolution": "ambiguous_name_without_domain",
            }
            if ambiguous_name and not domain
            else {},
        )
        return new_company, True
