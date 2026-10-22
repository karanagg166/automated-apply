"""Deterministic factual answers. Never infer current/expected pay from a search minimum."""

import re
from dataclasses import dataclass
from decimal import Decimal

from backend.app.services.profile_link_resolver import normalize


@dataclass(frozen=True)
class FactAnswer:
    handled: bool
    answer: str | None = None
    field: str | None = None
    category: str = "personal_details"


def number(value):
    return format(Decimal(str(value)).normalize(), "f")


def resolve_fact(profile, question, category):
    prefs = profile.preferences
    q = normalize(question).strip(" ?.:*")
    simple = re.sub(
        r"^(?:(?:what is|what are|please provide|please specify|please enter|provide|enter) )?(?:your )?",
        "",
        q,
    )
    money = re.fullmatch(
        r"(current|present|expected|desired) (?:(annual|yearly|monthly|hourly) )?(ctc|salary|compensation)(?: (?:in )?(inr|usd|eur|gbp|lpa))?",
        simple,
    )
    if money:
        when, period, kind, unit = money.groups()
        field = (
            "current_compensation"
            if when in {"current", "present"}
            else "expected_compensation"
        )
        value = prefs.get(field)
        if not value:
            return FactAnswer(True, field=field, category="compensation")
        expected_period = {
            "annual": "year",
            "yearly": "year",
            "monthly": "month",
            "hourly": "hour",
        }.get(period)
        if (
            (expected_period and value["period"] != expected_period)
            or (kind == "ctc" and value["kind"] != "ctc")
            or (kind == "salary" and value["kind"] != "base_salary")
            or (unit and unit != "lpa" and unit.upper() != value["currency"])
        ):
            return FactAnswer(True, field=field, category="compensation")
        if unit == "lpa":
            answer = (
                number(Decimal(value["amount"]) / 100000)
                if value["currency"] == "INR" and value["period"] == "year"
                else None
            )
        else:
            answer = f"{number(value['amount'])} {value['currency']} per {value['period']} ({value['kind'].replace('_', ' ')})"
        return FactAnswer(True, answer, field, "compensation")
    if re.fullmatch(
        r"(?:when can you start|when are you available(?: to start)?|available from|availability date|earliest start date|start date|availability)",
        simple,
    ):
        return FactAnswer(True, prefs.get("availability_date"), "availability_date")
    if re.fullmatch(r"(?:current location|current city|city of residence)", simple):
        return FactAnswer(True, prefs.get("current_location"), "current_location")
    if re.fullmatch(
        r"(?:are you |would you be )?(?:willing|open) to (?:relocate|relocation)(?: to .+)?",
        simple,
    ):
        specific = re.search(r"(?:relocate|relocation) to (.+)$", simple)
        if specific:
            target = specific[1]
            value = (
                True
                if target
                in {normalize(v) for v in prefs.get("relocation_locations", [])}
                else None
            )
        else:
            value = prefs.get("open_to_relocation")
        return FactAnswer(
            True,
            None if value is None else "Yes" if value else "No",
            "open_to_relocation",
        )
    if category == "work_authorization" or "eligible to work" in q:
        rows = [
            row
            for row in prefs.get("work_authorizations", [])
            if (
                re.search(r"\b" + re.escape(normalize(row["country_name"])) + r"\b", q)
                or re.search(
                    r"\bin (?:the )?" + re.escape(row["country_code"].lower()) + r"\b",
                    q,
                )
            )
        ]
        if len(rows) != 1:
            return FactAnswer(
                True, field="work_authorizations", category="work_authorization"
            )
        row = rows[0]
        country = (
            "(?:"
            + re.escape(normalize(row["country_name"]))
            + "|"
            + re.escape(row["country_code"].lower())
            + ")"
        )
        if re.fullmatch(
            r"(?:do you require|will you require|will you now or in (?:the )?future require) (?:visa )?sponsorship (?:to work )?in (?:the )?"
            + country,
            q,
        ):
            value = row.get("requires_sponsorship_now_or_future")
        elif re.fullmatch(
            r"(?:are you |are you legally |are you currently )?(?:legally )?(?:authorized|authorised|eligible) to work in (?:the )?"
            + country,
            q,
        ):
            value = row["authorized_to_work"]
        else:
            value = None
        return FactAnswer(
            True,
            None if value is None else "Yes" if value else "No",
            "work_authorizations",
            "work_authorization",
        )
    return FactAnswer(False)
