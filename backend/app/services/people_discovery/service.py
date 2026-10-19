import asyncio
import hashlib
import uuid

from backend.app.core.config import get_settings
from backend.app.models.discovery import DiscoveredPerson, now
from backend.app.repositories.company import CompanyRepository
from backend.app.schemas.discovery import DiscoveryError
from backend.app.schemas.discovery import DiscoveryStatus as Status
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
        if query.official_people:
            if query.source != "manual" or not query.permission_confirmed:
                raise ValueError(
                    "Official evidence requires manual import and confirmed retention rights"
                )
            if len(query.official_people) > query.limit:
                raise ValueError("Official evidence exceeds result limit")
            return await self.persist_official(query, query.official_people)
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
            if (
                not self.settings.PUBLIC_SEARCH_RIGHTS_REVIEWED
                or not self.settings.PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL
            ):
                return {
                    **result,
                    "status": "authentication_required",
                    "errors": [
                        "Public search retention rights and permission evidence must be reviewed"
                    ],
                }
            from pydantic import TypeAdapter

            from backend.app.core.urls import PublicHTTPSURL

            try:
                TypeAdapter(PublicHTTPSURL).validate_python(
                    self.settings.PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL
                )
            except ValueError:
                return {
                    **result,
                    "status": "configuration_required",
                    "errors": ["Invalid retention permission evidence URL"],
                }
            if (
                query.research_mode == "public_profiles"
                and not self.settings.LINKEDIN_SEARCH_RETENTION_AUTHORIZED
            ):
                return {
                    **result,
                    "status": "authentication_required",
                    "errors": ["LinkedIn-related result retention is not authorized"],
                }
            if query.research_mode == "official_company" and (
                not query.company_domain
                or query.company_domain
                not in self.settings.PUBLIC_SEARCH_ALLOWED_DOMAINS
            ):
                return {
                    **result,
                    "status": "authentication_required",
                    "errors": ["Official domain collection rights must be reviewed"],
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
                adapter = self.adapter or PublicSearchAdapter(
                    self.settings.SERPER_API_KEY
                )
                people, errors = await (
                    adapter.search_official(query)
                    if query.research_mode == "official_company"
                    else adapter.search(query)
                )
            except DiscoveryError as exc:
                if exc.status == Status.RATE_LIMITED:
                    await self.budget.cooldown("serper")
                await self.budget.finish(reservation, str(exc.status))
                return {**result, "status": str(exc.status), "errors": [str(exc)]}
            except asyncio.CancelledError:
                await asyncio.shield(self.budget.finish(reservation, "cancelled"))
                raise
            await self.budget.finish(reservation, "success")
            if query.research_mode == "official_company":
                for item in people:
                    item.permission_evidence_url = (
                        self.settings.PUBLIC_SEARCH_ALLOWED_DOMAINS[
                            query.company_domain
                        ]
                    )
                return await self.persist_official(query, people)
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
                statement = (
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
                        where=DiscoveredPerson.verification_status != "human_confirmed",
                    )
                    .returning(DiscoveredPerson.id)
                )
                person_id = (await self.session.execute(statement)).scalar_one_or_none()
                if person_id and person.name and person.role:
                    from backend.app.services.contact_enrichment.schemas import (
                        PersonObservation,
                    )
                    from backend.app.services.contact_enrichment.service import (
                        ContactEnrichmentService,
                    )

                    contact, conflicts = await ContactEnrichmentService(
                        self.session,
                        getattr(self.budget, "factory", None),
                        self.settings,
                    ).persist(
                        company.id,
                        PersonObservation(
                            full_name=person.name,
                            role_title=person.role,
                            company_domain=company.domain,
                            linkedin_url=person.linkedin_url,
                            evidence_url=person.evidence_url,
                            source=person.source,
                            permission_evidence_url=self.settings.PUBLIC_SEARCH_PERMISSION_EVIDENCE_URL
                            if query.source != "manual"
                            else None,
                            discovered_person_id=person_id,
                            evidence_strength="weak",
                        ),
                    )
                    if (
                        contact
                        and not contact.do_not_contact
                        and not contact.human_corrected
                        and not (contact.metadata_ or {}).get(
                            "identity_human_confirmed"
                        )
                    ):
                        contact.metadata_ = {
                            **contact.metadata_,
                            "identity_review_required": True,
                        }
        return {
            **result,
            "people": [p.model_dump() for p in people],
            "status": "partial" if errors else "success" if people else "no_results",
            "errors": errors,
        }

    async def persist_official(self, query, observations):
        from urllib.parse import urlsplit

        from backend.app.services.contact_enrichment.schemas import PersonObservation
        from backend.app.services.contact_enrichment.service import (
            ContactEnrichmentService,
        )

        await ingestion_lock(self.session)
        company, _ = await CompanyRepository(self.session).get_or_create(
            query.company_name, query.company_domain
        )
        records, errors = [], []
        for item in observations:
            if not query.company_domain or urlsplit(
                str(item.evidence_url)
            ).hostname not in {query.company_domain, "www." + query.company_domain}:
                errors.append("Official evidence employer domain requires review")
                continue
            observation = PersonObservation(
                full_name=item.full_name,
                role_title=item.role_title,
                company_domain=query.company_domain,
                professional_url=item.professional_url,
                permission_evidence_url=item.permission_evidence_url,
                provider_person_id=None
                if item.professional_url
                else hashlib.sha256(
                    (str(item.evidence_url) + item.full_name.casefold()).encode()
                ).hexdigest(),
                evidence_url=item.evidence_url,
                source="official_company"
                if query.source == "manual"
                else "public_search",
                observed_at=item.observed_at,
                evidence_strength="strong" if item.human_confirmed else "weak",
                human_confirmed=item.human_confirmed,
            )
            contact, conflicts = await ContactEnrichmentService(
                self.session, getattr(self.budget, "factory", None), self.settings
            ).persist(company.id, observation)
            if contact is None:
                errors.extend(conflicts)
                continue
            if not contact.do_not_contact and not contact.human_corrected:
                contact.metadata_ = {
                    **contact.metadata_,
                    "identity_review_required": bool(conflicts)
                    or (
                        not item.human_confirmed
                        and not (contact.metadata_ or {}).get(
                            "identity_human_confirmed"
                        )
                    ),
                    "identity_human_confirmed": item.human_confirmed
                    or (contact.metadata_ or {}).get("identity_human_confirmed", False),
                }
            records.append(
                {
                    "contact_id": str(contact.id),
                    "evidence_url": str(item.evidence_url),
                    "verification_status": "human_confirmed"
                    if item.human_confirmed and not conflicts
                    else "requires_review",
                    "identity_independently_confirmed": item.human_confirmed,
                    "email_known": bool(contact.email),
                    "suppressed": contact.do_not_contact,
                }
            )
        return {
            "company_name": query.company_name,
            "status": "partial" if errors else "success" if records else "no_results",
            "people": records,
            "errors": errors,
        }
