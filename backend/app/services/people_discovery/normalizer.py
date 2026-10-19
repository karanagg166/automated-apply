import re
from urllib.parse import unquote, urlsplit, urlunsplit

from backend.app.core.job_urls import canonical_job_url


def normalize_linkedin_url(value, *, allow_company=False):
    parsed = urlsplit(canonical_job_url(value))
    if parsed.hostname not in {
        "linkedin.com",
        "www.linkedin.com",
        "in.linkedin.com",
        "uk.linkedin.com",
        "us.linkedin.com",
    }:
        raise ValueError("A LinkedIn public profile URL is required")
    kind = "(?:in|company)" if allow_company else "in"
    if not re.fullmatch(r"/" + kind + r"/[A-Za-z0-9_%~-]+", unquote(parsed.path)):
        raise ValueError("Unsupported LinkedIn profile path")
    return urlunsplit(("https", "www.linkedin.com", parsed.path + "/", "", ""))


def mark_ambiguities(people):
    names = {}
    for person in people:
        if person.name:
            names.setdefault(person.name.casefold(), set()).add(person.linkedin_url)
    for person in people:
        if person.name and len(names[person.name.casefold()]) > 1:
            person.verification_status = "requires_review"
    return people
