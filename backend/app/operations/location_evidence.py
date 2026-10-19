"""Conservative listing location evidence; never proof of personal work authorization."""

import re


def regional_access(location, desired_locations):
    if not location or not desired_locations:
        return "requires_review"
    text = location.casefold()
    desired = [value.casefold() for value in desired_locations]
    supported = any(re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", text) for value in desired)
    # Restricted worldwide/time-zone statements cannot be treated as global eligibility.
    restriction = re.search(r"\bonly\b|\bresidents?\b|\brestricted\b|\bexcluding\b|\bexcept\b", text)
    if restriction:
        return "requires_review" if supported else "restricted_location"
    global_scope = re.fullmatch(r"(?:remote[\s:(-]*)?(?:worldwide|anywhere|global)[\s).!-]*", text)
    if supported or global_scope:
        return "listing_location_supported"
    return "requires_review"
