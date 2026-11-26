"""Evidence-only provider parsing helpers (ported from v1 `services.job_sources`)."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit


def parse_date(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))  # noqa: FURB162 - verbatim v1


def remote_policy(text: Any) -> str:
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


def employment(text: Any) -> str | None:
    text = (text or "").lower().replace("-", "_").replace(" ", "_")
    for word in ("full_time", "part_time", "contract", "internship"):
        if word in text:
            return word
    return None


def salary_fields(raw: Any) -> dict[str, Any]:
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
    if not re.search(r"USD|INR|EUR|GBP|CAD|AUD|[$€£]", raw, re.IGNORECASE):
        return {}
    match = re.search(
        r"(?:USD|INR|EUR|GBP|CAD|AUD|[$€£])\s*([\d,]+(?:\.\d+)?)\s*([kKmM])?(?:\s*[-–—]\s*(?:USD|INR|EUR|GBP|CAD|AUD|[$€£])?\s*([\d,]+(?:\.\d+)?)\s*([kKmM])?)?",
        raw,
    )
    if not match:
        return {}

    def number(n: str, unit: str | None) -> float:
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


def structured_salary(minimum: Any, maximum: Any, currency: Any, interval: Any,
                      periods: dict[str, str]) -> dict[str, Any]:
    """Do not coerce strings, booleans, equity, or incompatible ranges into pay."""
    if any(
        value is not None
        and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 1e12
        )
        for value in (minimum, maximum)
    ):
        return {}
    if minimum is None and maximum is None:
        return {}
    if minimum is not None and maximum is not None and minimum > maximum:
        return {}
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        return {}
    period = periods.get(interval) if isinstance(interval, str) else None
    if not period:
        return {}
    return {
        "salary_min": minimum,
        "salary_max": maximum,
        "salary_currency": currency,
        "salary_period": period,
    }


def hosted_job_url(value: Any, board: str, source: str, host: str, *, application: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError("Missing hosted job URL")  # noqa: TRY004 - v1 contract (record error)
    parsed = urlsplit(value)
    suffix = r"(?:/apply)?" if source == "lever" else r"(?:/application)?"
    if (
        parsed.scheme != "https"
        or parsed.netloc != host
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(
            r"/"
            + "(?i:"
            + re.escape(board)
            + ")"
            + r"/[A-Za-z0-9-]{1,100}"
            + (suffix if application else ""),
            parsed.path.removesuffix("/"),
        )
    ):
        raise ValueError("Hosted job URL conflicts with configured board")
    return value
