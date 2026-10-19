"""Validation is not mailbox verification. Never infer verification from presence."""

import re
from urllib.parse import urlsplit

ROLE_INBOXES = {
    "careers",
    "jobs",
    "hr",
    "recruitment",
    "recruiting",
    "talent",
    "hiring",
    "info",
    "hello",
    "contact",
    "support",
    "team",
    "admin",
    "sales",
    "office",
    "people",
    "noreply",
    "no-reply",
}


def domain(value):
    if not isinstance(value, str):
        return None
    host = urlsplit(value if "://" in value else "https://" + value).hostname
    return host.removeprefix("www.").casefold() if host else None


def business_email(value, company_domain):
    if (
        not isinstance(value, str)
        or len(value) > 255
        or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value)
    ):
        return None
    email = value.strip().casefold()
    return email if email.split("@")[1] == domain(company_domain) else None


def email_kind(email):
    local = email.split("@")[0].split("+")[0]
    return (
        "role_based"
        if local in ROLE_INBOXES
        or re.match(r"^(careers|jobs|recruiting|hr|hiring)[._-]", local)
        else "person_specific"
    )


def candidate_confidence_percent(value):
    if not 0 <= value <= 1:
        raise ValueError("EmailCandidate confidence must be between zero and one")
    return round(value * 100, 2)


def fresh(timestamp, days=30):
    from datetime import datetime, timedelta, timezone

    if timestamp is None:
        return False
    return timestamp.replace(tzinfo=timezone.utc) >= datetime.now(
        timezone.utc
    ) - timedelta(days=days)


def email_observed_at(contact):
    from datetime import datetime

    raw = (contact.metadata_ or {}).get("email_observed_at")
    if raw:
        try:
            return datetime.fromisoformat(raw)
        except (TypeError, ValueError):
            return None
    return contact.last_checked_at
