"""Append-only normalized snapshots with durable replay deduplication."""

import hashlib
import json

from backend.app.models.startup import CompanySourceObservation
from backend.app.services.discovery_budget import insert_for
from backend.app.services.startup_discovery.company_identity import (
    identity_key,
    resolve_company,
)


async def ingest_company(session, item, run_id=None):
    company = await resolve_company(session, item)
    attributes = item.model_dump(mode="json")
    digest = hashlib.sha256(json.dumps(attributes, sort_keys=True).encode()).hexdigest()
    await session.execute(
        insert_for(session)(CompanySourceObservation)
        .values(
            company_id=company.id,
            run_id=run_id,
            source=item.source,
            identity_key=identity_key(item),
            content_hash=digest,
            source_url=str(item.source_url),
            observed_at=item.observed_at,
            attributes=attributes,
            verification_status=item.verification_status,
        )
        .on_conflict_do_nothing()
    )
    return company
