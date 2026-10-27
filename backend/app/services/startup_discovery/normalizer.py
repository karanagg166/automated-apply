"""No estimated headcounts or stage-to-size conversions."""

import re
from datetime import timezone

BANDS = {
    "1-10": (1, 10),
    "2-10": (2, 10),
    "11-50": (11, 50),
    "51-200": (51, 200),
    "201-500": (201, 500),
    "500+": (501, None),
}


def utc(value):
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def size_band(count):
    if count is None:
        return "unknown"
    return next(
        b
        for b, (low, high) in BANDS.items()
        if count >= low and (high is None or count <= high)
    )


def size_allowed(size, filters):
    if filters.exact_employee_count and size["employee_count"] is None:
        return False
    if filters.min_employees is not None:
        minimum = size["employee_count"] or BANDS.get(size["team_size_band"], (None, None))[0]
        if minimum is None or minimum < filters.min_employees:
            return False
    if size["team_size_band"] == "unknown":
        return filters.include_unknown_size
    if filters.size_bands and size["team_size_band"] not in filters.size_bands:
        return False
    if filters.max_employees is None:
        return True
    # A band straddling a strict maximum cannot establish eligibility.
    maximum = size["employee_count"] or BANDS[size["team_size_band"]][1]
    return maximum is not None and maximum <= filters.max_employees


def role_allowed(title, roles):
    return not roles or any(role.casefold() in title.casefold() for role in roles)


def location_allowed(locations, remotes, filters):
    """Shared explicit search filter, usable for company or individual job evidence."""
    remote_match = filters.remote_preference == "remote" and "remote" in remotes
    if (
        filters.locations
        and not remote_match
        and not any(
            loc.casefold() in (value or "").casefold()
            for loc in filters.locations
            for value in locations
        )
    ):
        return False
    return (
        filters.remote_preference in (None, "any")
        or filters.remote_preference in remotes
    )


def industry_allowed(industry, requested):
    """Industry words are explicit evidence; AI must never match 'retail'."""
    aliases = {"ai": ["ai", "artificial intelligence"],
               "saas": ["saas", "software as a service"],
               "fintech": ["fintech", "financial technology"],
               "developer tools": ["developer tools", "developer tooling", "devtools"]}
    value = (industry or "").casefold()
    return not requested or any(
        re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", value)
        for item in requested for term in aliases.get(item.casefold(), [item.casefold()])
    )
