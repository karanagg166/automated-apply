"""Conservative reconciliation; caller commits short company-locked transactions."""

import hashlib
from datetime import timedelta, timezone

from sqlalchemy import select

from backend.app.models.company import Company
from backend.app.models.contact import Contact
from backend.app.models.contact_enrichment import ContactEvidence, ContactIdentity
from backend.app.models.discovery import now
from backend.app.services.contact_enrichment.verification import (
    business_email,
    email_kind,
)
from backend.app.services.people_discovery.normalizer import normalize_linkedin_url


class IdentityConflict(ValueError):
    pass


def folded(value):
    return " ".join((value or "").casefold().split())


def normalized_url(value):
    try:
        return normalize_linkedin_url(value) if value else None
    except ValueError:
        return None


class ContactIdentityResolver:
    def __init__(self, session, ttl_days=30):
        self.session, self.ttl_days = session, ttl_days

    async def reconcile(self, company_id, observation):
        await self.session.flush()
        # Short row lock protects legacy records too, before they have identity mappings.
        company = await self.session.scalar(
            select(Company).where(Company.id == company_id).with_for_update()
        )
        if company is None:
            raise ValueError("Company not found")
        if observation.company_domain and folded(observation.company_domain) != folded(
            company.domain
        ):
            raise IdentityConflict("Company association requires review")
        email = business_email(observation.email, company.domain)
        kind = email_kind(email) if email else observation.email_kind
        keys = []
        if observation.professional_url:
            keys.append(("professional_url", str(observation.professional_url)))
            keys.append(
                (
                    "suppressed_professional_url",
                    hashlib.sha256(
                        str(observation.professional_url).encode()
                    ).hexdigest(),
                )
            )
        if observation.linkedin_url:
            keys.append(("linkedin", observation.linkedin_url))
            keys.append(
                (
                    "suppressed_linkedin",
                    hashlib.sha256(observation.linkedin_url.encode()).hexdigest(),
                )
            )
        if observation.provider_person_id:
            keys.append((observation.source, observation.provider_person_id))
            keys.append(
                (
                    "suppressed_provider_" + observation.source,
                    hashlib.sha256(observation.provider_person_id.encode()).hexdigest(),
                )
            )
        if observation.discovered_person_id:
            keys.append(("discovered_person", str(observation.discovered_person_id)))
        if email and kind == "person_specific":
            keys.append(
                ("suppressed_email", hashlib.sha256(email.encode()).hexdigest())
            )
        matches = {}
        for namespace, key in keys:
            mapping = await self.session.scalar(
                select(ContactIdentity).where(
                    ContactIdentity.company_id == company_id,
                    ContactIdentity.namespace == namespace,
                    ContactIdentity.identity_key == key,
                )
            )
            if mapping:
                contact = await self.session.get(
                    Contact, mapping.contact_id, populate_existing=True
                )
                matches[contact.id] = contact
        records = list(
            (
                await self.session.scalars(
                    select(Contact)
                    .where(Contact.company_id == company_id)
                    .execution_options(populate_existing=True)
                )
            ).all()
        )
        for contact in records:
            same_url = (
                observation.linkedin_url
                and normalized_url(contact.linkedin_url) == observation.linkedin_url
            )
            same_email = (
                email
                and kind == "person_specific"
                and contact.email
                and contact.email.casefold() == email
            )
            if same_url or same_email:
                if not contact.human_corrected and folded(contact.full_name) != folded(
                    observation.full_name
                ):
                    raise IdentityConflict(
                        "Identity key has incompatible names; human review required"
                    )
                if (
                    same_email
                    and observation.linkedin_url
                    and normalized_url(contact.linkedin_url)
                    and normalized_url(contact.linkedin_url) != observation.linkedin_url
                ):
                    raise IdentityConflict(
                        "Email and profile identities conflict; human review required"
                    )
                matches[contact.id] = contact
        if len(matches) > 1:
            raise IdentityConflict(
                "Multiple contact identities conflict; human review required"
            )
        contact = next(iter(matches.values()), None)
        if (
            contact
            and not contact.do_not_contact
            and not contact.human_corrected
            and folded(contact.full_name) != folded(observation.full_name)
        ):
            raise IdentityConflict(
                "Provider identity has incompatible names; human review required"
            )
        strength = "strong" if contact else observation.evidence_strength
        if contact is None and observation.evidence_url:
            # Moderate identity requires the exact supporting source, full name AND role.
            supported = []
            for existing in records:
                if (
                    folded(existing.full_name) == folded(observation.full_name)
                    and folded(existing.role_title) == folded(observation.role_title)
                    and not (
                        normalized_url(existing.linkedin_url)
                        and observation.linkedin_url
                        and normalized_url(existing.linkedin_url)
                        != observation.linkedin_url
                    )
                ):
                    support = await self.session.scalar(
                        select(ContactEvidence.id).where(
                            ContactEvidence.contact_id == existing.id,
                            ContactEvidence.evidence_url
                            == str(observation.evidence_url),
                            ContactEvidence.user_confirmed.is_(True),
                        )
                    )
                    if support:
                        supported.append(existing)
            if len(supported) == 1:
                contact = supported[0]
                strength = "moderate"
        created = contact is None
        if created:
            contact = Contact(
                company_id=company_id,
                full_name=observation.full_name,
                role_title=observation.role_title or "Unknown",
                linkedin_url=observation.linkedin_url,
                enrichment_source=observation.source,
                confidence_score=0,
                metadata_={},
            )
            self.session.add(contact)
            await self.session.flush()
        if contact.do_not_contact:
            return contact, created, ["suppressed"]
        conflicts = []
        email_added = False
        if (
            email
            and kind == "person_specific"
            and observation.email_kind == "person_specific"
        ):
            if contact.email and contact.email.casefold() != email:
                conflicts.append("conflicting_email")
            elif not contact.human_corrected and not contact.email:
                contact.email = email
                email_added = True
                contact.enrichment_source = observation.source
                # These adapters never establish independently verified mailbox evidence.
                contact.email_status = (
                    "candidate"
                    if observation.email_status == "candidate"
                    else "provider_reported"
                    if observation.email_status in {"provider_reported", "verified"}
                    else observation.email_status
                )
            elif (
                not contact.human_corrected
                and contact.email_status == "candidate"
                and observation.email_status == "provider_reported"
            ):
                contact.email_status = "provider_reported"
                contact.enrichment_source = observation.source
                email_added = True
        if (
            email
            and contact.email == email
            and not contact.human_corrected
            and observation.email_status in {"provider_reported", "verified"}
        ):
            email_added = True
            if contact.email_status == "invalid":
                conflicts.append("conflicting_email_validity")
        if not contact.human_corrected and (
            not (contact.metadata_ or {}).get("identity_human_confirmed")
            or observation.human_confirmed
        ):
            if observation.role_title and (
                observation.observed_at is None
                or contact.last_checked_at is None
                or observation.observed_at.replace(tzinfo=timezone.utc)
                >= contact.last_checked_at.replace(tzinfo=timezone.utc)
            ):
                contact.role_title = observation.role_title
            if observation.linkedin_url and not contact.linkedin_url:
                contact.linkedin_url = observation.linkedin_url
        checked = observation.observed_at or now()
        if (
            not (contact.metadata_ or {}).get("identity_human_confirmed")
            or observation.human_confirmed
        ) and (
            contact.last_checked_at is None
            or checked.replace(tzinfo=timezone.utc)
            > contact.last_checked_at.replace(tzinfo=timezone.utc)
        ):
            contact.last_checked_at = checked
        email_metadata = (
            {
                "email_observed_at": checked.isoformat(),
                "email_source": observation.source,
            }
            if email_added
            else {}
        )
        publication_metadata = {}
        if email and email == contact.email and observation.email_publication_url and observation.source == "official_company" and observation.human_confirmed and not conflicts:
            from urllib.parse import urlsplit
            if urlsplit(str(observation.email_publication_url)).hostname in {company.domain, "www." + (company.domain or "")}:
                publication_metadata = {"email_publication_url": str(observation.email_publication_url),
                                        "email_publication_confirmed": True,
                                        "email_observed_at": checked.isoformat()}
        contact.metadata_ = {
            **(contact.metadata_ or {}),
            **email_metadata,
            **publication_metadata,
            "evidence_strength": strength,
            "identity_review_required": bool(conflicts)
            or bool((contact.metadata_ or {}).get("identity_review_required")),
        }
        for namespace, key in keys:
            if namespace.startswith("suppressed_"):
                continue
            present = await self.session.scalar(
                select(ContactIdentity.id).where(
                    ContactIdentity.company_id == company_id,
                    ContactIdentity.namespace == namespace,
                    ContactIdentity.identity_key == key,
                )
            )
            if not present:
                self.session.add(
                    ContactIdentity(
                        company_id=company_id,
                        contact_id=contact.id,
                        namespace=namespace,
                        identity_key=key,
                        discovered_person_id=observation.discovered_person_id,
                    )
                )
        self.session.add(
            ContactEvidence(
                company_id=company_id,
                contact_id=contact.id if kind == "person_specific" else None,
                source=observation.source,
                evidence_type="professional_observation"
                if kind == "person_specific"
                else "company_business_inbox",
                evidence_url=str(observation.evidence_url)
                if observation.evidence_url
                else observation.linkedin_url,
                observed_role=observation.role_title,
                observed_company=company.domain,
                provider_verification_claim=observation.provider_verification_claim,
                user_confirmed=observation.human_confirmed,
                strength=strength,
                collected_at=observation.observed_at or now(),
                expires_at=(observation.observed_at or now())
                + timedelta(days=self.ttl_days),
                provenance={
                    "permission_evidence_url": str(observation.permission_evidence_url)
                    if observation.permission_evidence_url
                    else None,
                    "professional_url": str(observation.professional_url)
                    if observation.professional_url
                    else None,
                    "email": email,
                    "email_kind": kind,
                    "email_status": observation.email_status,
                    "conflicts": conflicts,
                    "provider_person_id": observation.provider_person_id,
                    "discovered_person_id": str(observation.discovered_person_id)
                    if observation.discovered_person_id
                    else None,
                },
            )
        )
        await self.session.flush()
        return contact, created, conflicts
