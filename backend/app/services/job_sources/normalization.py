"""Small evidence-only provider parsing helpers."""

import re
from datetime import datetime, timezone


def parse_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, timezone.utc)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def remote_policy(text):
    text = (text or "").lower()
    if re.search(r"no remote|not remote|onsite only|on-site only", text):
        return "onsite"
    if "hybrid" in text:
        return "hybrid"
    if "remote" in text:
        return "remote"
    if "onsite" in text or "on-site" in text:
        return "onsite"
    return "unknown"


def employment(text):
    text = (text or "").lower().replace("-", "_").replace(" ", "_")
    for word in ("full_time", "part_time", "contract", "internship"):
        if word in text:
            return word
    return None


def salary_fields(raw):
    """Only explicit units/currencies; '$' alone is deliberately ambiguous."""
    if not raw or not isinstance(raw, str):
        return {}
    text = raw.lower()
    currency = next(
        (c for c in ("USD", "INR", "EUR", "GBP", "CAD", "AUD") if c.lower() in text),
        None,
    )
    if not currency:
        currency = "EUR" if "€" in raw else "GBP" if "£" in raw else None
    period = next(
        (
            p
            for p, pattern in {
                "year": r"\byear|annual|p\.a\.|\bpa\b",
                "month": r"\bmonth",
                "hour": r"\bhour|/hr\b",
                "week": r"\bweek",
                "day": r"\bday",
            }.items()
            if re.search(pattern, text)
        ),
        None,
    )
    # Never parse equity percentages as salary. Require an explicit monetary marker.
    if not re.search(r"USD|INR|EUR|GBP|CAD|AUD|[$€£]", raw, re.I):
        return {}
    match = re.search(
        r"(?:USD|INR|EUR|GBP|CAD|AUD|[$€£])\s*([\d,]+(?:\.\d+)?)\s*([kKmM])?(?:\s*[-–—]\s*(?:USD|INR|EUR|GBP|CAD|AUD|[$€£])?\s*([\d,]+(?:\.\d+)?)\s*([kKmM])?)?",
        raw,
    )
    if not match:
        return {}

    def number(n, unit):
        return float(n.replace(",", "")) * {"k": 1000, "m": 1000000}.get(
            (unit or "").lower(), 1
        )

    minimum = number(match[1], match[2])
    maximum = number(match[3], match[4]) if match[3] else None
    if maximum is not None and minimum > maximum:
        return {}
    return {
        "salary_min": minimum,
        "salary_max": maximum,
        "salary_currency": currency,
        "salary_period": period,
    }
