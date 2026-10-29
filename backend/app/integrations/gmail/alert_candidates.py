"""Cross-account requisition deduplication. Candidates never establish vacancy facts."""

import hashlib

from sqlalchemy import text

from backend.app.dashboard.models import OwnerPreference
from backend.app.execution.naukri import normalized_url
from backend.app.integrations.token_store import ConnectionError
from backend.app.models.discovery import now


async def record_candidates(session, *, source, account, message_id, sender, links, monitoring_authorized=False):
    # A separate exact source policy is required; read/draft consent is not polling permission.
    if not monitoring_authorized:
        raise ConnectionError("job_alert_intake_authorization_required")
    from email.utils import parseaddr
    address = parseaddr(sender)[1].casefold()
    if not address.endswith("@naukri.com"):
        raise ConnectionError("official_naukri_sender_required")
    if source not in {"gmail", "apple_mail"} or not account or not message_id:
        raise ConnectionError("job_alert_source_reference_required")
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(text("SELECT pg_advisory_xact_lock(407054,2)"))
    results = []
    for link in links[:25]:
        try:
            url = normalized_url(link)
        except ValueError:
            continue
        requisition = url.rsplit("-", 1)[-1]
        key = "gm54_lead:" + hashlib.sha256(requisition.encode()).hexdigest()[:32]
        row = await session.get(OwnerPreference, key, with_for_update=True, populate_existing=True)
        value = dict(row.value) if row else {"requisition": requisition, "url": url, "sources": [],
            "state": "NEEDS_FACTUAL_AND_ORIGIN_REVIEW", "origin_authenticated": False, "submitted": False}
        reference = {"source": source, "account": account, "message_id": message_id}
        if reference not in value["sources"]:
            if len(value["sources"]) >= 100:
                raise ConnectionError("job_alert_source_reference_limit")
            value["sources"] = [*value["sources"], reference]
        value["observed_at"] = now().isoformat()
        if row:
            row.value = value
        else:
            session.add(OwnerPreference(key=key, value=value))
        await session.flush()
        results.append(value)
    return list({r["requisition"]: r for r in results}.values())
