import asyncio
import uuid
from backend.app.core.config import get_settings
from backend.app.models.discovery import DiscoveredPerson, now
from backend.app.repositories.company import CompanyRepository
from backend.app.schemas.discovery import DiscoveryError, DiscoveryStatus as Status
from backend.app.services.discovery_budget import insert_for
from backend.app.services.job_deduplication import ingestion_lock
from backend.app.services.people_discovery.normalizer import mark_ambiguities
from backend.app.services.people_discovery.public_search import PublicSearchAdapter


class PeopleDiscoveryService:
    def __init__(self, session, budget, settings=None, adapter=None):
        self.session, self.budget = session, budget
        self.settings = settings or get_settings()
        self.adapter = adapter

    async def search(self, query):
        result = {
            "company_name": query.company_name,
            "people": [],
            "status": "no_results",
            "errors": [],
        }
        if query.source == "linkedin":
            return {
                **result,
                "status": "authentication_required",
                "errors": [
                    "Direct LinkedIn collection unavailable; use permitted public_search or manual URLs"
                ],
            }
        if query.manual_people and query.source != "manual":
            raise ValueError("Manual people require source=manual")
        if query.source == "manual":
            people, errors = query.manual_people[: query.limit], []
            for person in people:
                person.source, person.verification_status = "manual", "requires_review"
        else:
            if not self.settings.PEOPLE_SEARCH_ENABLED:
                return {
                    **result,
                    "status": "configuration_required",
                    "errors": ["Public search is disabled"],
                }
            if not self.settings.SERPER_API_KEY:
                return {
                    **result,
                    "status": "missing_credentials",
                    "errors": ["Public search API key required"],
                }
            if not query.allow_paid:
                return {
                    **result,
                    "status": "authentication_required",
                    "errors": ["Explicit paid search approval required"],
                }
            reservation = "people_" + uuid.uuid4().hex
            try:
                await self.budget.reserve(
                    "serper", reservation, 1, self.settings.SERPER_MONTHLY_LIMIT
                )
                people, errors = await (
                    self.adapter or PublicSearchAdapter(self.settings.SERPER_API_KEY)
                ).search(query)
            except DiscoveryError as exc:
                if exc.status == Status.RATE_LIMITED:
                    await self.budget.cooldown("serper")
                await self.budget.finish(reservation, str(exc.status))
                return {**result, "status": str(exc.status), "errors": [str(exc)]}
            except asyncio.CancelledError:
                await asyncio.shield(self.budget.finish(reservation, "cancelled"))
                raise
            await self.budget.finish(reservation, "success")
        unique = {}
        for person in people:
            unique.setdefault(person.linkedin_url, person)
        people = mark_ambiguities(list(unique.values()))
        if people:
            await ingestion_lock(self.session)
            company, _ = await CompanyRepository(self.session).get_or_create(
                query.company_name, query.company_domain
            )
            for person in people:
                values = dict(
                    company_id=company.id,
                    name=person.name,
                    role=person.role,
                    linkedin_url=person.linkedin_url,
                    evidence_url=person.evidence_url,
                    source=person.source,
                    observed_at=now(),
                    verification_status=person.verification_status,
                    evidence={"text": person.evidence_text, "outreach_mode": "manual"},
                )
                await self.session.execute(
                    insert_for(self.session)(DiscoveredPerson)
                    .values(**values)
                    .on_conflict_do_update(
                        index_elements=[
                            DiscoveredPerson.company_id,
                            DiscoveredPerson.linkedin_url,
                        ],
                        set_={
                            k: values[k]
                            for k in ("observed_at", "evidence", "verification_status")
                        },
                    )
                )
        return {
            **result,
            "people": [p.model_dump() for p in people],
            "status": "partial" if errors else "success" if people else "no_results",
            "errors": errors,
        }
