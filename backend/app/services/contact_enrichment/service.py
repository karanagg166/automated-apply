"""Local-first orchestration with durable run, lookup and independent budget commits."""

import asyncio
import hashlib
import json
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from backend.app.core.config import get_settings
from backend.app.models.company import Company
from backend.app.models.contact import Contact
from backend.app.models.contact_enrichment import (
    ContactEnrichmentRun,
    ContactEvidence,
    ContactLookup,
)
from backend.app.models.discovery import DiscoveredPerson, DiscoveryMonthlyBudget, now
from backend.app.schemas.discovery import DiscoveryError
from backend.app.services.contact_enrichment.contact_identity import (
    ContactIdentityResolver,
    IdentityConflict,
    normalized_url,
)
from backend.app.services.contact_enrichment.provider_factory import (
    PROVIDERS,
    get_provider,
)
from backend.app.services.contact_enrichment.schemas import (
    ContactEnrichmentRequest,
    PersonObservation,
    State,
)
from backend.app.services.contact_enrichment.verification import business_email, fresh
from backend.app.services.contact_enrichment.waterfall import (
    fallback_justified,
    needs_lookup,
)
from backend.app.services.credit_manager import CreditManager
from backend.app.services.discovery_budget import DiscoveryBudget, insert_for
from backend.app.services.email_candidate_generator import EmailCandidateGenerator


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def role_matches(role, filters):
    aliases = {
        "cto": ["cto", "chief technology"],
        "ceo": ["ceo", "chief executive"],
        "hr": ["hr", "human resources"],
        "recruiter": ["recruit", "talent acquisition"],
    }
    value = (role or "").casefold().replace("-", " ")
    return not filters or any(
        any(
            word in value
            for word in aliases.get(f.casefold(), [f.casefold().replace("_", " ")])
        )
        for f in filters
    )


class ContactEnrichmentService:
    def __init__(self, session, factory, settings=None, providers=None):
        self.session, self.factory = session, factory
        self.settings = settings or get_settings()
        self.budget = DiscoveryBudget(factory)
        self.production_providers = providers is None
        self.providers = (
            providers
            if providers is not None
            else {name: get_provider(name, self.settings) for name in PROVIDERS}
        )

    async def company(self, company_id):
        company = await self.session.get(Company, company_id)
        if company is None:
            raise LookupError("Company not found")
        return company

    async def local(self, company_id, request):
        records = (
            await self.session.scalars(
                select(Contact)
                .where(Contact.company_id == company_id)
                .order_by(Contact.id)
                .limit(1000)
            )
        ).all()
        people = (
            await self.session.scalars(
                select(DiscoveredPerson)
                .where(DiscoveredPerson.company_id == company_id)
                .order_by(DiscoveredPerson.observed_at.desc())
                .limit(100)
            )
        ).all()
        return [
            c for c in records if role_matches(c.role_title, request.target_roles)
        ], [p for p in people if role_matches(p.role, request.target_roles)]

    async def provider_status(self):
        month = now().strftime("%Y-%m")
        result = []
        for name, provider in self.providers.items():
            row = await self.session.get(DiscoveryMonthlyBudget, (name, month))
            maximum = self.settings.get_provider_monthly_limit(name)
            cost = getattr(self.settings, name.upper() + "_CREDITS_PER_LOOKUP")
            result.append(
                {
                    "provider": name,
                    "enabled": provider.enabled,
                    "credentials_configured": bool(
                        provider.api_key and provider.api_key.strip()
                    ),
                    "configuration_status": provider.validate_configuration(),
                    "capabilities": provider.get_capabilities().model_dump(),
                    "budget": {
                        "monthly_limit": maximum,
                        "reserved_estimate": float(row.reserved) if row else 0,
                        "remaining_local_budget": max(0, maximum - float(row.reserved))
                        if row
                        else maximum,
                        "provider_balance": None,
                        "credits_per_lookup_estimate": cost or None,
                        "per_run_limit": getattr(
                            self.settings, name.upper() + "_PER_RUN_LIMIT"
                        ),
                        "cooldown_until": row.cooldown_until.isoformat()
                        if row and row.cooldown_until
                        else None,
                    },
                    "live_verification": "not_checked",
                    "billing_configuration_required": cost == 0,
                }
            )
        return result

    async def preview(self, company_id, request):
        company = await self.company(company_id)
        contacts, people = await self.local(company_id, request)
        maximum = min(
            request.max_people, self.settings.CONTACT_ENRICHMENT_MAX_PEOPLE_PER_RUN
        )
        targets = [
            c for c in contacts if needs_lookup(c, self.settings.CONTACT_CACHE_TTL_DAYS)
        ]
        unmapped = [
            p
            for p in people
            if p.name and not any(c.linkedin_url == p.linkedin_url for c in contacts)
        ]
        count = min(maximum, len(targets) + len(unmapped))
        if (
            not contacts
            and not people
            and company.domain
            and request.providers
            and request.providers[0] == "apollo"
        ):
            count = maximum
        estimates = []
        for name in request.providers:
            provider = self.providers[name]
            cost = getattr(self.settings, name.upper() + "_CREDITS_PER_LOOKUP")
            cap = getattr(self.settings, name.upper() + "_PER_RUN_LIMIT")
            estimates.append(
                {
                    "provider": name,
                    "lookup_count_upper_bound": count,
                    "reserved_credit_upper_bound": min(count * cost, cap)
                    if cost
                    else None,
                    "cost_basis": "operator_configured_account_estimate",
                    "configured": provider.validate_configuration() == State.COMPLETED,
                    "billable_authorization_present": request.allow_paid,
                    "fallback_requires_opt_in": name != request.providers[0],
                    "search_if_no_targets": name == "apollo"
                    and not contacts
                    and not people
                    and bool(company.domain),
                    "search_credits": 0 if name == "apollo" else None,
                }
            )
        company_evidence = (
            await self.session.scalars(
                select(ContactEvidence)
                .where(
                    ContactEvidence.company_id == company_id,
                    ContactEvidence.contact_id.is_(None),
                    ContactEvidence.expires_at > now(),
                )
                .order_by(ContactEvidence.collected_at.desc())
                .limit(100)
            )
        ).all()
        return {
            "company_id": str(company_id),
            "company_evidence": [
                {
                    "id": str(e.id),
                    "source": e.source,
                    "type": e.evidence_type,
                    "url": e.evidence_url,
                    "collected_at": e.collected_at,
                    "provenance": {
                        k: v
                        for k, v in e.provenance.items()
                        if k in {"email", "email_kind", "full_name", "requires_review"}
                    },
                }
                for e in company_evidence
            ],
            "cached_contacts": [
                {
                    "id": str(c.id),
                    "name": c.full_name,
                    "role": c.role_title,
                    "email_status": c.email_status,
                }
                for c in contacts[:100]
            ],
            "discovered_people": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "role": p.role,
                    "linkedin_url": p.linkedin_url,
                }
                for p in people
            ],
            "targets": [str(c.id) for c in targets[:maximum]],
            "discovered_targets": [str(p.id) for p in unmapped[:maximum]],
            "no_lookup_needed": [str(c.id) for c in contacts if c not in targets][:100],
            "provider_plan": estimates,
            "max_people": maximum,
            "read_only": True,
            "billable_calls": 0,
        }

    async def persist(self, company_id, observation):
        try:
            async with self.session.begin_nested():
                contact, _, conflicts = await ContactIdentityResolver(
                    self.session, self.settings.CONTACT_CACHE_TTL_DAYS
                ).reconcile(company_id, observation)
                return contact, conflicts
        except IdentityConflict:
            affected = (
                await self.session.scalars(
                    select(Contact).where(Contact.company_id == company_id)
                )
            ).all()
            for existing in affected:
                if (
                    observation.linkedin_url
                    and normalized_url(existing.linkedin_url)
                    == observation.linkedin_url
                ) or (
                    observation.email
                    and existing.email
                    and existing.email.casefold() == observation.email.casefold()
                ):
                    existing.metadata_ = {
                        **(existing.metadata_ or {}),
                        "identity_review_required": True,
                    }
            self.session.add(
                ContactEvidence(
                    company_id=company_id,
                    source=observation.source,
                    evidence_type="identity_conflict",
                    evidence_url=str(observation.evidence_url)
                    if observation.evidence_url
                    else observation.linkedin_url,
                    observed_role=observation.role_title,
                    observed_company=observation.company_domain,
                    strength="weak",
                    expires_at=now()
                    + timedelta(days=self.settings.CONTACT_CACHE_TTL_DAYS),
                    provenance={
                        "requires_review": True,
                        "full_name": observation.full_name,
                        "email": business_email(
                            observation.email, observation.company_domain
                        ),
                    },
                )
            )
            return None, ["Identity conflict requires human review"]

    async def record_unmatched(self, company_id, contact, observation):
        contact.metadata_ = {
            **(contact.metadata_ or {}),
            "identity_review_required": True,
        }
        self.session.add(
            ContactEvidence(
                company_id=company_id,
                source=observation.source,
                evidence_type="identity_conflict",
                evidence_url=observation.linkedin_url,
                observed_role=observation.role_title,
                observed_company=observation.company_domain,
                strength="weak",
                expires_at=now() + timedelta(days=self.settings.CONTACT_CACHE_TTL_DAYS),
                provenance={
                    "requires_review": True,
                    "target_contact_id": str(contact.id),
                    "full_name": observation.full_name,
                    "email": business_email(
                        observation.email, observation.company_domain
                    ),
                },
            )
        )

    async def claim_lookup(self, company_id, provider, identity):
        # Unique durable claim, committed BEFORE the remote request. Uncertain claims
        # are never automatically recycled after crashes, retries or process restarts.
        reservation = "contact_" + uuid.uuid4().hex
        key = digest(identity)
        async with self.factory() as session:
            row = (
                await session.execute(
                    insert_for(session)(ContactLookup)
                    .values(
                        id=uuid.uuid4(),
                        company_id=company_id,
                        provider=provider,
                        identity_key=key,
                        reservation_id=reservation,
                        state="running",
                        expires_at=now()
                        + timedelta(days=self.settings.CONTACT_CACHE_TTL_DAYS),
                    )
                    .on_conflict_do_nothing()
                    .returning(ContactLookup.id)
                )
            ).scalar_one_or_none()
            if row is None:
                previous = await session.scalar(
                    select(ContactLookup)
                    .where(
                        ContactLookup.company_id == company_id,
                        ContactLookup.provider == provider,
                        ContactLookup.identity_key == key,
                    )
                    .with_for_update()
                )
                if previous.state not in {"completed", "not_found"} or fresh(
                    previous.expires_at, 0
                ):
                    return None
                previous.reservation_id, previous.state = reservation, "running"
                previous.expires_at = now() + timedelta(
                    days=self.settings.CONTACT_CACHE_TTL_DAYS
                )
            await session.commit()
        return reservation

    async def call(self, company, name, request, run, spent, operation="enrich_person"):
        provider = self.providers[name]
        if provider.validate_configuration() != State.COMPLETED:
            return provider.result(
                State.NOT_CONFIGURED,
                errors=["Provider disabled or credentials missing"],
            )
        cost = (
            getattr(self.settings, name.upper() + "_CREDITS_PER_LOOKUP")
            if operation == "enrich_person"
            else 0
        )
        if operation == "enrich_person" and cost == 0:
            return provider.result(
                State.NOT_CONFIGURED,
                errors=[
                    "Confirm account-specific maximum credits per lookup before execution"
                ],
            )
        if spent.get(name, 0) + cost > getattr(
            self.settings, name.upper() + "_PER_RUN_LIMIT"
        ):
            return provider.result(
                State.BUDGET_EXHAUSTED, errors=["Per-run credit cap reached"]
            )
        if name == "signalhire" and not (
            request.linkedin_url or request.provider_person_id
        ):
            return provider.result(
                State.UNSUPPORTED,
                errors=["SignalHire requires a supported person identifier"],
            )
        cooldown = await self.session.scalar(
            select(func.max(DiscoveryMonthlyBudget.cooldown_until)).where(
                DiscoveryMonthlyBudget.provider == name
            )
        )
        if cooldown and fresh(cooldown, 0):
            return provider.result(
                State.RATE_LIMITED, errors=["Provider is cooling down"]
            )
        target_key = (
            json.dumps(request.target_roles, sort_keys=True)
            if operation == "search_people"
            else request.linkedin_url
            or request.provider_person_id
            or "name:" + (request.full_name or "").casefold()
        )
        identity = operation + ":" + target_key
        reservation = await self.claim_lookup(company.id, name, identity)
        if reservation is None:
            return provider.result(
                State.RUNNING,
                errors=[
                    "Durable lookup already exists; reuse cached evidence or review prior run"
                ],
            )
        monthly_limit = self.settings.get_provider_monthly_limit(name)
        if name == "apollo":
            from backend.app.services.contact_enrichment.apollo_capabilities import (
                preflight,
            )
            from backend.app.services.contact_enrichment.base import ProviderError
            # Fixture providers explicitly replace the transport. Production adapters
            # always inspect the actual account immediately before dispatch.
            if self.production_providers:
                try:
                    from backend.app.services.startup_discovery.connectivity import (
                        claim_access,
                    )
                    await self.session.commit()
                    await claim_access(self.factory, "apollo_capability")
                    capability = await preflight(provider, self.settings, operation, cost)
                    monthly_limit = min(monthly_limit, capability["credits"]["remaining"])
                except DiscoveryError:
                    await self.finish_lookup(reservation, State.RATE_LIMITED)
                    return provider.result(State.RATE_LIMITED, errors=["Apollo local capability interval has not elapsed"])
                except ProviderError as exc:
                    await self.finish_lookup(reservation, exc.state)
                    return provider.error_result(exc)
        if cost:
            try:
                await self.budget.reserve(
                    name,
                    reservation,
                    cost,
                    monthly_limit,
                )
            except DiscoveryError as exc:
                await self.finish_lookup(reservation, str(exc.status))
                return provider.result(
                    State.RATE_LIMITED
                    if str(exc.status) == "rate_limited"
                    else State.BUDGET_EXHAUSTED,
                    errors=["Provider budget unavailable or cooling down"],
                )
        spent[name] = spent.get(name, 0) + cost
        try:
            result = await getattr(provider, operation)(request)
        except asyncio.CancelledError:
            await asyncio.shield(self.finish_lookup(reservation, State.UNCERTAIN))
            raise
        except Exception:
            result = provider.result(
                State.UNCERTAIN,
                errors=[
                    "Provider execution interrupted; manual reconciliation required"
                ],
            )
        if result.status == State.RATE_LIMITED:
            async with self.factory() as audit:
                await audit.execute(
                    insert_for(audit)(DiscoveryMonthlyBudget)
                    .values(provider=name, month=now().strftime("%Y-%m"), reserved=0)
                    .on_conflict_do_nothing()
                )
                await audit.commit()
            await self.budget.cooldown(name, result.retry_after_seconds or 60)
        # Independent usage transaction survives a later ingestion rollback.
        async with self.factory() as audit:
            await CreditManager(audit).record_usage(
                name,
                result.credits_used or 0,
                endpoint=operation,
                is_success=result.status == State.COMPLETED,
                error_message="; ".join(result.errors) or None,
            )
            await audit.commit()
        await self.finish_lookup(reservation, result.status)
        if cost:
            await self.budget.finish(reservation, result.status, result.credits_used)
        usage = {
            "provider": name,
            "operation": operation,
            "state": result.status,
            "reserved_estimate": cost,
            "confirmed_provider_credits": result.credits_used,
            "reservation_id": reservation,
            "provider_run_id": result.provider_run_id,
        }
        run.usage = [*run.usage, usage]
        await self.session.commit()
        return result

    async def finish_lookup(self, reservation, state):
        async with self.factory() as session:
            row = await session.scalar(
                select(ContactLookup).where(ContactLookup.reservation_id == reservation)
            )
            if row:
                row.state = str(state)
            await session.commit()

    async def enrich(self, company_id, request):
        company = await self.company(company_id)
        request_hash = digest(
            str(company_id) + request.model_dump_json(exclude={"idempotency_key"})
        )
        run_id = uuid.uuid4()
        claimed = (
            await self.session.execute(
                insert_for(self.session)(ContactEnrichmentRun)
                .values(
                    id=run_id,
                    company_id=company_id,
                    request_hash=request_hash,
                    target_roles=request.target_roles,
                    provider_plan=request.providers,
                    state="running",
                    contact_ids=[],
                    counts={},
                    usage=[],
                    errors=[],
                    idempotency_key=request.idempotency_key,
                )
                .on_conflict_do_nothing()
                .returning(ContactEnrichmentRun.id)
            )
        ).scalar_one_or_none()
        if not claimed:
            run = await self.session.scalar(
                select(ContactEnrichmentRun).where(
                    ContactEnrichmentRun.idempotency_key == request.idempotency_key
                )
            )
            if run.request_hash != request_hash:
                raise IdentityConflict("Idempotency key belongs to a different request")
            return run
        await self.session.commit()
        run = await self.session.get(ContactEnrichmentRun, run_id)
        maximum = min(
            request.max_people, self.settings.CONTACT_ENRICHMENT_MAX_PEOPLE_PER_RUN
        )
        contacts, people = await self.local(company_id, request)
        selected = {c.id: c for c in contacts[:maximum]}
        errors, spent, outcomes = [], {}, []
        blocked_providers = set()
        # Bridge Phase 2B observations. Public snippets do not prove mailbox validity.
        for person in people[:maximum]:
            if not person.name or person.verification_status == "requires_review":
                continue
            if len(selected) >= maximum and not any(
                normalized_url(c.linkedin_url) == normalized_url(person.linkedin_url)
                for c in selected.values()
            ):
                continue
            try:
                observation = PersonObservation(
                    full_name=person.name,
                    role_title=person.role,
                    linkedin_url=person.linkedin_url,
                    source=person.source,
                    evidence_url=person.evidence_url,
                    company_domain=company.domain,
                    observed_at=person.observed_at,
                    discovered_person_id=person.id,
                    evidence_strength="moderate",
                )
                contact, issues = await self.persist(company_id, observation)
                errors.extend(issues)
                if (
                    contact
                    and role_matches(contact.role_title, request.target_roles)
                    and len(selected) < maximum
                ):
                    selected[contact.id] = contact
            except ValueError:
                errors.append("Invalid discovered-person evidence requires review")
        await self.session.commit()
        # Only explicit reviewed, already-stored public business evidence is consumed.
        # This service never fetches submitted evidence URLs or extracts generic inboxes.
        for contact in selected.values():
            if contact.do_not_contact or contact.human_corrected:
                continue
            public = (
                await self.session.scalars(
                    select(ContactEvidence)
                    .where(
                        ContactEvidence.contact_id == contact.id,
                        ContactEvidence.evidence_type == "public_business_contact",
                        ContactEvidence.user_confirmed.is_(True),
                        ContactEvidence.expires_at > now(),
                    )
                    .order_by(ContactEvidence.collected_at.desc())
                    .limit(10)
                )
            ).all()
            for evidence in public:
                email = business_email(evidence.provenance.get("email"), company.domain)
                if (
                    not email
                    or evidence.provenance.get("email_kind") != "person_specific"
                ):
                    continue
                observation = PersonObservation(
                    full_name=contact.full_name,
                    role_title=contact.role_title,
                    company_domain=company.domain,
                    linkedin_url=contact.linkedin_url,
                    email=email,
                    email_status="provider_reported",
                    source="public_evidence",
                    evidence_url=evidence.evidence_url,
                    observed_at=evidence.collected_at,
                    evidence_strength=evidence.strength,
                )
                _, issues = await self.persist(company_id, observation)
                errors.extend(issues)
                break
        await self.session.commit()
        if request.allow_paid and request.providers and not selected and company.domain:
            primary = request.providers[0]
            if self.providers[primary].get_capabilities().search_people:
                query = ContactEnrichmentRequest(
                    company_id=company_id,
                    company_domain=company.domain,
                    target_roles=request.target_roles,
                    max_people=maximum,
                    allow_paid=True,
                )
                result = await self.call(
                    company, primary, query, run, spent, "search_people"
                )
                outcomes.append(result.status)
                errors.extend(result.errors)
                for observation in result.contacts[:maximum]:
                    if role_matches(observation.role_title, request.target_roles):
                        contact, issues = await self.persist(company_id, observation)
                        errors.extend(issues)
                        if contact:
                            selected[contact.id] = contact
                await self.session.commit()
        if request.allow_paid:
            for contact in list(selected.values())[:maximum]:
                if not needs_lookup(contact, self.settings.CONTACT_CACHE_TTL_DAYS):
                    continue
                # Names alone cannot safely reconcile paid results to an existing person.
                if not contact.linkedin_url:
                    errors.append(
                        "Person needs a professional profile identifier before paid enrichment"
                    )
                    continue
                previous = None
                for index, name in enumerate(request.providers):
                    if name in blocked_providers:
                        break
                    if index and (
                        (contact.metadata_ or {}).get("identity_review_required")
                        or not fallback_justified(
                            previous, request.allow_fallback, contact.linkedin_url
                        )
                    ):
                        break
                    query = ContactEnrichmentRequest(
                        company_id=company_id,
                        person_id=contact.id,
                        full_name=contact.full_name,
                        company_domain=company.domain,
                        linkedin_url=contact.linkedin_url,
                        target_roles=request.target_roles,
                        allow_paid=True,
                    )
                    result = await self.call(company, name, query, run, spent)
                    previous = result
                    outcomes.append(result.status)
                    if result.status in {
                        State.AUTHORIZATION_REQUIRED,
                        State.RATE_LIMITED,
                        State.UNCERTAIN,
                        State.FAILED,
                    }:
                        blocked_providers.add(name)
                    errors.extend(result.errors)
                    for observation in result.contacts[:1]:
                        if (
                            observation.linkedin_url
                            and observation.linkedin_url
                            != normalized_url(contact.linkedin_url)
                        ):
                            await self.record_unmatched(
                                company_id, contact, observation
                            )
                            errors.append(
                                "Provider returned conflicting profile identity; human review required"
                            )
                            continue
                        if not observation.linkedin_url:
                            # A paid query is not a verified mapping. Do not merge on the request alone.
                            await self.record_unmatched(
                                company_id, contact, observation
                            )
                            errors.append(
                                "Provider did not return a supporting profile identity"
                            )
                            continue
                        resolved, issues = await self.persist(company_id, observation)
                        errors.extend(issues)
                        if resolved and resolved.id != contact.id:
                            errors.append(
                                "Provider identity resolved separately; human review required"
                            )
                    await self.session.commit()
                    if not needs_lookup(
                        contact, self.settings.CONTACT_CACHE_TTL_DAYS
                    ) and not fallback_justified(
                        result, request.allow_fallback, contact.linkedin_url
                    ):
                        break
        run.contact_ids = [str(c.id) for c in selected.values()][:maximum]
        candidates = []
        if request.include_candidates and company.domain:
            for c in selected.values():
                if (
                    c.email
                    or c.do_not_contact
                    or (c.metadata_ or {}).get("identity_review_required")
                ):
                    continue
                parts = c.full_name.split(" ", 1)
                candidates.append(
                    {
                        "contact_id": str(c.id),
                        "candidates": [
                            p.model_dump()
                            for p in EmailCandidateGenerator.generate_candidates(
                                parts[0],
                                parts[1] if len(parts) > 1 else "",
                                company.domain,
                            )[:6]
                        ],
                    }
                )
        run.counts = {
            "contacts": len(run.contact_ids),
            "candidate_research": candidates,
            "outbound_messages_sent": 0,
        }
        run.errors = list(dict.fromkeys(errors))[:50]
        states = outcomes
        run.state = (
            str(states[-1]) if states and states[-1] != State.COMPLETED else "completed"
        )
        run.completed_at = now()
        await self.session.commit()
        return run
