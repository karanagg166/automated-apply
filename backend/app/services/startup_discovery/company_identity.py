"""Domain and source identities are stronger than display-name spelling."""

import hashlib

from sqlalchemy import select

from backend.app.models.company import Company
from backend.app.models.startup import CompanySourceObservation
from backend.app.repositories.company import CompanyRepository
from backend.app.services.job_deduplication import ingestion_lock


def identity_key(item):
    return hashlib.sha256(
        (
            "id:" + item.source_company_id
            if item.source_company_id
            else "domain:" + item.domain
            if item.domain
            else "url:" + str(item.source_url)
        ).encode()
    ).hexdigest()


async def resolve_company(session, item):
    await ingestion_lock(session)
    prior = await session.scalar(
        select(CompanySourceObservation)
        .where(
            CompanySourceObservation.source == item.source,
            CompanySourceObservation.identity_key == identity_key(item),
        )
        .limit(1)
    )
    by_domain = (
        await CompanyRepository(session).get_by_domain(item.domain)
        if item.domain
        else None
    )
    if prior:
        company = await session.get(Company, prior.company_id)
        if not item.source_company_id and not item.domain and " ".join(company.name.casefold().split()) != " ".join(item.name.casefold().split()):
            raise ValueError("Unqualified source URL does not establish company identity")
        if (by_domain and by_domain.id != company.id) or (
            item.domain and company.domain and company.domain != item.domain
        ):
            raise ValueError("Source company identity conflicts with domain")
        if item.domain and not company.domain:
            if (company.metadata_ or {}).get("identity_review_required"):
                raise ValueError(
                    "Ambiguous company association requires employer review"
                )
            company.domain = item.domain
        return company
    if by_domain:
        return by_domain
    # Display-name equality never proves identity. A new domain/source identity
    # stays separate until an owner reconciles it with attributable evidence.
    company = Company(name=item.name, domain=item.domain, metadata_={})
    session.add(company)
    await session.flush()
    return company
