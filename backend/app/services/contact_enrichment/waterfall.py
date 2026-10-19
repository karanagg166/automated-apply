"""Pure policy: local first, no automatic empty-result cascade or uncertain retry."""

from backend.app.services.contact_enrichment.schemas import State
from backend.app.services.contact_enrichment.verification import (
    email_observed_at,
    fresh,
)

RELIABLE_STATUSES = {"verified", "provider_reported"}


def needs_lookup(contact, ttl_days):
    if (
        contact.do_not_contact
        or contact.human_corrected
        or (contact.metadata_ or {}).get("identity_review_required")
    ):
        return False
    if fresh(contact.last_checked_at, ttl_days):
        if (
            contact.email
            and contact.email_status in RELIABLE_STATUSES
            and fresh(email_observed_at(contact), ttl_days)
        ):
            return False
        if (contact.metadata_ or {}).get(
            "evidence_strength"
        ) == "strong" and contact.linkedin_url:
            return False
    return True


def fallback_justified(previous, allow_fallback, has_identifier):
    # Never cascade for transport/auth/empty/error. Only a usable first result with
    # missing business email may justify a separately authorized lookup.
    return bool(
        allow_fallback
        and has_identifier
        and previous.status == State.COMPLETED
        and previous.contacts
        and not any(p.email for p in previous.contacts)
    )
