"""Deterministic screening answers from verified profile facts only.

Anything not backed by a stored fact returns None so the caller raises a
WAITING_FOR_USER (HITL) request instead of guessing.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from backend.app.browser_v2.tech_terms import is_known_tech

# Ported from extension/naukri-chatbot.js + backend/app/knowledge/missing_input.py.
BLOCKED = re.compile(r"\b(?:email|e-mail|login|password|otp|consent|terms and conditions)\b", re.IGNORECASE)
SENSITIVE = re.compile(
    r"password|passcode|verification code|one.time (?:code|password)|social security|"
    r"government (?:id|identifier)|aadhaar|aadhar|pan (?:card|number)|passport|bank account|"
    r"credit card|\bcvv\b|\botp\b|sexual orientation|gender identity|ethnicity|disabilit|"
    r"veteran|religio|consent|legal declaration|terms and conditions", re.IGNORECASE)
TOTAL_EXPERIENCE = re.compile(
    r"\b(?:total|overall)\s+(?:years of\s+)?(?:work\s+|professional\s+)?experience\b|"
    r"\byears of (?:professional |work |total )?experience\b(?!\s+(?:in|with|using|on)\b)|"
    r"\bhow many years of experience do you have\b(?!\s+(?:in|with|using|on)\b)|"
    # Workstream 3 (2026-11-26): "Experience (in years)", "Work experience", "Experience in years".
    r"^\s*(?:total\s+|work\s+|professional\s+)?experience\s*(?:\(\s*(?:in\s+)?(?:years?|yrs)\s*\)|"
    r"in\s+years)?\s*\??$", re.IGNORECASE)
# "Do you have at least 3 years of (professional) experience [in Python]?" -> compare stored years.
YEARS_THRESHOLD = re.compile(
    r"(?P<op>at least|minimum(?:\s+of)?|min\.?|more than|over)?\s*(?P<n>\d+(?:\.\d+)?)\s*"
    r"(?P<plus>\+|plus|or more)?\s*(?:years?|yrs?)\b(?:\s+of)?\s+(?:total\s+|overall\s+|professional\s+)?"
    r"(?:work\s+|hands[- ]on\s+)?(?:experience|exp)\b(?P<rest>.*)$", re.IGNORECASE)
THRESHOLD_SKILL = re.compile(r"^\s*(?:in|with|using|on)\s+(?P<skill>[A-Za-z0-9.+#/ -]{1,40}?)\s*\??$", re.IGNORECASE)
SKILL_EXPERIENCE = re.compile(
    r"\b(?:experience|exp)\b.*?\b(?:in|with|using|on)\s+(?P<skill>[A-Za-z0-9.+#/ -]{1,40}?)\s*\??$",
    re.IGNORECASE)
SKILL_YES_NO = re.compile(
    r"\b(?:do you have|have you (?:worked|used)|are you (?:familiar|proficient|comfortable))\b"
    r".*?\b(?:with|in|on|using)?\s*(?P<skill>[A-Za-z0-9.+#/ -]{1,40}?)\s*(?:experience)?\s*\??$",
    re.IGNORECASE)
NOTICE = re.compile(r"\bnotice period\b|\bhow soon can you join\b|\bjoin(?:ing)? (?:date|time)\b", re.IGNORECASE)
START_WHEN = re.compile(r"\bwhen can you (?:start|join)\b|\bhow soon can you start\b|"
                        r"\bavailab(?:le|ility) to (?:start|join)\b", re.IGNORECASE)
CURRENT_CTC = re.compile(r"\bcurrent\s+(?:annual\s+|yearly\s+|fixed\s+|total\s+)?(?:ctc|salary|compensation|package)\b|"
                         r"\bcctc\b", re.IGNORECASE)
EXPECTED_CTC = re.compile(r"\bexpected\s+(?:annual\s+|yearly\s+|fixed\s+|total\s+)?(?:ctc|salary|compensation|package)\b|"
                          r"\bectc\b|\bsalary expectations?\b|\bdesired\s+(?:annual\s+)?(?:ctc|salary|compensation)\b",
                          re.IGNORECASE)
# Stored CTC is INR LPA: a question in another currency or per hour is never answered from it.
FOREIGN_PAY = re.compile(r"\b(?:usd|dollars?|eur|euros?|gbp|pounds?|aud|cad|sgd|aed)\b|[$€£]|"
                         r"\b(?:per hour|hourly)\b", re.IGNORECASE)
CURRENT_LOCATION = re.compile(r"\bcurrent(?:ly)?\s+(?:location|based|city|residing)\b|\bwhere are you (?:currently )?(?:located|based)\b|"
                              r"^\s*(?:your\s+)?location(?:\s*\(city\))?\s*\??$", re.IGNORECASE)
CITY_Q = re.compile(r"^\s*(?:current\s+|your\s+)?(?:city|town)(?:\s+of\s+residence)?\s*\??$|"
                    r"\bwhich city (?:are|do) you (?:currently )?(?:live|living|reside|residing|based|located)\b",
                    re.IGNORECASE)
STATE_Q = re.compile(r"^\s*(?:current\s+|your\s+)?(?:state|province)(?:\s*/\s*(?:province|region|ut|union territory))?"
                     r"(?:\s+of\s+residence)?\s*\??$|"
                     r"\bwhich state (?:are|do) you (?:currently )?(?:live|living|reside|residing|based|located)\b",
                     re.IGNORECASE)
COUNTRY_Q = re.compile(r"^\s*(?:current\s+|your\s+)?country(?:\s*/\s*region)?(?:\s+of\s+(?:residence|residency))?\s*\??$|"
                       r"\bcountry\s+of\s+(?:residence|residency)\b|"
                       r"\b(?:which|what)\s+country\s+(?:are|do)\s+you\s+(?:currently\s+)?"
                       r"(?:live|living|reside|residing|based|located|in)\b|"
                       r"\bcountry\s+(?:where\s+)?you\s+(?:currently\s+)?(?:live|reside|are based|are located)\b",
                       re.IGNORECASE)
CURRENT_COMPANY_Q = re.compile(r"\b(?:current|present)\s+(?:company|employer|organi[sz]ation)(?:\s+name)?\b|"
                               r"\bwhere do you (?:currently )?work\b|\bcompany you (?:currently )?work (?:for|at)\b",
                               re.IGNORECASE)
LINK_CONTEXT = re.compile(r"\bhear about\b|\bhow did you (?:find|learn|discover)\b|\bsource\b|\brefer", re.IGNORECASE)
LINKEDIN_Q = re.compile(r"^\s*linked\s?in(?:\s+(?:url|profile|link|page))*\s*\??$|"
                        r"\blinked\s?in\b.*\b(?:url|profile|link|page)\b|\b(?:url|profile|link)\b.*\blinked\s?in\b",
                        re.IGNORECASE)
GITHUB_Q = re.compile(r"^\s*git\s?hub(?:\s+(?:url|profile|link|page))*\s*\??$|"
                      r"\bgit\s?hub\b.*\b(?:url|profile|link|page|username)\b|\b(?:url|profile|link)\b.*\bgit\s?hub\b",
                      re.IGNORECASE)
PORTFOLIO_Q = re.compile(r"^\s*(?:personal\s+|portfolio\s+)?(?:website|portfolio|site)(?:\s+(?:url|link))?\s*\??$|"
                         r"\b(?:portfolio|personal (?:website|site))\b.*\b(?:url|link)\b|"
                         r"\b(?:url|link)\b.*\b(?:portfolio|personal (?:website|site))\b", re.IGNORECASE)
YES_NO_QUESTION = re.compile(r"^\s*(?:are|do|does|did|will|would|can|could|have|has|is)\b", re.IGNORECASE)
ENGLISH_Q = re.compile(r"\benglish\b.*\b(?:proficien\w*|fluen\w*|level|speak\w*|communicat\w*|rate)\b|"
                       r"\b(?:proficien\w*|fluen\w*)\b.*\benglish\b", re.IGNORECASE)
WORK_AUTH_Q = re.compile(r"\b(?:legally\s+)?(?:authori[sz]ed|eligible|permitted|allowed)\s+to\s+work\b|"
                         r"\bwork\s+(?:authori[sz]ation|permit)\b|\bright\s+to\s+work\b", re.IGNORECASE)
SPONSORSHIP_Q = re.compile(r"\bsponsor(?:ship|ed)?\b", re.IGNORECASE)
GENERIC_FIELDS = frozenset({"total", "overall", "years", "year", "total years", "it", "the it industry", "it industry", "industry",
                            "software", "software development", "this field", "the field",
                            "this role", "a similar role", "similar role"})
RELOCATE = re.compile(r"\b(?:relocat\w*|willing to (?:move|shift))\b", re.IGNORECASE)
RELOCATE_TARGET = re.compile(r"\b(?:relocat\w*|move|shift)\s+to\s+(?P<city>[A-Za-z .-]{2,40}?)\s*\??$", re.IGNORECASE)
LOCATED_IN = re.compile(
    r"\b(?:are you|do you)\s+(?:currently\s+)?(?:located|based|living|residing|stay(?:ing)?)\s+(?:in|at|near)\s+"
    r"(?P<city>[A-Za-z .-]{2,40}?)\s*\??$", re.IGNORECASE)
IMMEDIATE_JOINER = re.compile(r"\bimmediate(?:ly)?\s+(?:joiner|join|available|start)\b|\bjoin immediately\b", re.IGNORECASE)
JOIN_WITHIN = re.compile(r"\b(?:join|start)\b.*?\bwithin\s+(?P<n>\d+)\s*(?P<unit>days?|weeks?|months?)\b", re.IGNORECASE)
LAKH_UNIT = re.compile(r"\b(?:lakhs?|lacs?|lpa|l\.p\.a)\b", re.IGNORECASE)
RUPEE_UNIT = re.compile(r"\b(?:in rupees|in inr|inr|rupees)\b|₹", re.IGNORECASE)
MONTHLY = re.compile(r"\b(?:per month|monthly|in hand per month|/\s*month)\b", re.IGNORECASE)


class ResolvedLike(Protocol):
    @property
    def answer(self) -> str | None: ...

    @property
    def source(self) -> str: ...

    @property
    def reason(self) -> str: ...


class ScreeningResolver(Protocol):
    """Tiered resolver (ai_v2.screening.ScreeningAnswerer); Tier 0 is always resolve_answer()."""

    async def resolve(self, question: str, options: tuple[str, ...], facts: CandidateFacts,
                      context: dict[str, Any] | None = None) -> ResolvedLike: ...


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9+#.]+", " ", text.lower()).strip()


IDENTITY_KEYS = ("full_name", "email", "phone", "linkedin_url", "github_url", "portfolio_url",
                 "personal_website")


def identity_fields(profile: dict[str, Any]) -> dict[str, str]:
    """Stored identity values only (first/last name split from full_name); never invented."""
    values = {key: profile[key].strip() for key in IDENTITY_KEYS
              if isinstance(profile.get(key), str) and profile[key].strip()}
    prefs = profile.get("preferences") or {}
    location = prefs.get("current_location") if isinstance(prefs, dict) else None
    if isinstance(location, str) and location.strip():
        values["current_location"] = location.strip()
    name = values.get("full_name", "")
    if name:
        first, _, last = name.partition(" ")
        values["first_name"] = first
        if last.strip():
            values["last_name"] = last.strip()
    if "portfolio_url" not in values and "personal_website" in values:
        values["portfolio_url"] = values["personal_website"]
    return values


# --- geography (Workstream 3): deterministic place facts, never guessed ---------------------
def _letters(text: str) -> str:
    return re.sub(r"[^a-z]+", " ", (text or "").lower()).strip()


# normalized alias -> (display name, ISO code). Bare "us"/"in" are deliberately NOT aliases for
# question scanning ("authorized to work for us?"), only for exact option/fact equality.
COUNTRIES: dict[str, tuple[str, str]] = {
    "india": ("India", "IN"), "bharat": ("India", "IN"),
    "united states": ("United States", "US"), "united states of america": ("United States", "US"),
    "usa": ("United States", "US"), "u s": ("United States", "US"), "u s a": ("United States", "US"),
    "america": ("United States", "US"),
    "united kingdom": ("United Kingdom", "GB"), "uk": ("United Kingdom", "GB"), "u k": ("United Kingdom", "GB"),
    "great britain": ("United Kingdom", "GB"), "britain": ("United Kingdom", "GB"),
    "england": ("United Kingdom", "GB"),
    "canada": ("Canada", "CA"), "germany": ("Germany", "DE"), "singapore": ("Singapore", "SG"),
    "australia": ("Australia", "AU"), "united arab emirates": ("United Arab Emirates", "AE"),
    "uae": ("United Arab Emirates", "AE"), "netherlands": ("Netherlands", "NL"), "ireland": ("Ireland", "IE"),
    "france": ("France", "FR"), "japan": ("Japan", "JP"),
}
_CODE_ONLY = {"us": "US", "in": "IN", "gb": "GB"}
_FOREIGN_PLACES = frozenset({"london", "berlin", "dubai", "new york", "san francisco", "seattle", "toronto",
                             "amsterdam", "dublin", "sydney", "tokyo", "paris", "munich", "melbourne"})
_NOT_A_CITY = frozenset({"remote", "anywhere", "wfh", "work from home", "na", "n a", "none", "any"})
_CITY_ALIASES = {"bangalore": "bengaluru", "bombay": "mumbai", "gurugram": "gurgaon", "madras": "chennai",
                 "calcutta": "kolkata", "new delhi": "delhi", "trivandrum": "thiruvananthapuram",
                 "mysore": "mysuru", "poona": "pune", "cochin": "kochi", "vizag": "visakhapatnam",
                 "mangalore": "mangaluru", "delhi ncr": "delhi", "ncr": "delhi"}
INDIAN_STATES = frozenset({
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", "goa", "gujarat", "haryana",
    "himachal pradesh", "jharkhand", "karnataka", "kerala", "madhya pradesh", "maharashtra", "manipur",
    "meghalaya", "mizoram", "nagaland", "odisha", "orissa", "punjab", "rajasthan", "sikkim", "tamil nadu",
    "telangana", "tripura", "uttar pradesh", "uttarakhand", "west bengal", "delhi", "jammu and kashmir",
    "ladakh", "puducherry", "pondicherry", "chandigarh"})
# Canonical Indian city -> its state (geographic fact, used only to answer "State" questions).
INDIAN_CITY_STATE = {
    "bengaluru": "Karnataka", "mysuru": "Karnataka", "mangaluru": "Karnataka", "mumbai": "Maharashtra",
    "pune": "Maharashtra", "nagpur": "Maharashtra", "thane": "Maharashtra", "navi mumbai": "Maharashtra",
    "nashik": "Maharashtra", "delhi": "Delhi", "gurgaon": "Haryana", "faridabad": "Haryana",
    "noida": "Uttar Pradesh", "ghaziabad": "Uttar Pradesh", "lucknow": "Uttar Pradesh", "kanpur": "Uttar Pradesh",
    "varanasi": "Uttar Pradesh", "hyderabad": "Telangana", "chennai": "Tamil Nadu", "coimbatore": "Tamil Nadu",
    "madurai": "Tamil Nadu", "kolkata": "West Bengal", "ahmedabad": "Gujarat", "vadodara": "Gujarat",
    "surat": "Gujarat", "jaipur": "Rajasthan", "chandigarh": "Chandigarh", "mohali": "Punjab",
    "ludhiana": "Punjab", "amritsar": "Punjab", "kochi": "Kerala", "thiruvananthapuram": "Kerala",
    "indore": "Madhya Pradesh", "bhopal": "Madhya Pradesh", "visakhapatnam": "Andhra Pradesh",
    "vijayawada": "Andhra Pradesh", "bhubaneswar": "Odisha", "dehradun": "Uttarakhand", "patna": "Bihar",
    "ranchi": "Jharkhand", "guwahati": "Assam", "raipur": "Chhattisgarh", "goa": "Goa", "panaji": "Goa",
}


def _city_key(text: str) -> str:
    key = _letters(text)
    return _CITY_ALIASES.get(key, key)


def country_of(text: str | None, *, allow_codes: bool = False) -> tuple[str, str] | None:
    """Exact country name/alias (or ISO code when allowed) -> (display, code)."""
    key = _letters(text or "")
    if key in COUNTRIES:
        return COUNTRIES[key]
    code = (text or "").strip().upper()
    if allow_codes and re.fullmatch(r"[A-Z]{2}", code):
        for display, iso in COUNTRIES.values():
            if iso == code:
                return display, iso
    return None


def countries_mentioned(question: str) -> set[str]:
    """ISO codes of countries named in a question (whole words; never bare 'us'/'in')."""
    text = f" {_letters(question)} "
    return {code for alias, (_, code) in COUNTRIES.items() if f" {alias} " in text}


@dataclass(frozen=True)
class PlaceFacts:
    city: str | None = None
    state: str | None = None
    country: str | None = None
    country_code: str | None = None
    country_source: str | None = None  # explicit | location | phone


def place_facts(location: str | None, explicit_country: str | None, phone: str | None) -> PlaceFacts:
    """City/state/country from stored facts only.

    Country precedence: explicit stored country > a country named in current_location >
    "India" when current_location is a recognizable Indian city/state > "India" when the stored
    phone starts with +91 (and the location does not name a foreign place). Otherwise unknown.
    """
    parts = [p.strip() for p in (location or "").split(",") if p.strip()]
    city = state = None
    named_country: tuple[str, str] | None = None
    indian = foreign = False
    for index, part in enumerate(parts):
        key = _city_key(part)
        found = country_of(part)
        if found:
            named_country = named_country or found
            continue
        if key in INDIAN_STATES and (index > 0 or key not in INDIAN_CITY_STATE):
            state = state or part
            indian = True
            continue
        if index == 0 and key not in _NOT_A_CITY:
            city = part
        if key in INDIAN_CITY_STATE:
            indian = True
            if index == 0 and state is None:
                state = INDIAN_CITY_STATE[key]
        if key in _FOREIGN_PLACES:
            foreign = True
    if explicit_country and explicit_country.strip():
        found = country_of(explicit_country, allow_codes=True)
        display, code = found if found else (explicit_country.strip(), None)
        return PlaceFacts(city, state, display, code, "explicit")
    if named_country:
        return PlaceFacts(city, state if named_country[1] == "IN" else None, *named_country, "location")
    if indian:
        return PlaceFacts(city, state, "India", "IN", "location")
    digits = re.sub(r"[\s().-]+", "", phone or "")
    if digits.startswith("+91") and not foreign:
        return PlaceFacts(city, None, "India", "IN", "phone")
    return PlaceFacts(city, None, None, None, None)


@dataclass(frozen=True)
class WorkAuthorization:
    country_code: str
    authorized: bool | None
    requires_sponsorship: bool | None


def _work_authorizations(value: Any) -> tuple[WorkAuthorization, ...]:
    rows: list[WorkAuthorization] = []
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        code = item.get("country_code")
        if not isinstance(code, str) or not code.strip():
            found = country_of(str(item.get("country_name") or ""))
            code = found[1] if found else None
        if code:
            authorized = item.get("authorized_to_work")
            sponsor = item.get("requires_sponsorship_now_or_future")
            rows.append(WorkAuthorization(code.strip().upper(), authorized if isinstance(authorized, bool) else None,
                                          sponsor if isinstance(sponsor, bool) else None))
    return tuple(rows)


def _lpa_from_compensation(value: Any) -> str | None:
    """INR yearly CTC fact (preferences.*_compensation) -> LPA text; other currencies/periods: None."""
    if not isinstance(value, dict) or value.get("currency") != "INR" or value.get("period") != "year" \
            or value.get("kind") not in ("ctc", "total_compensation"):
        return None
    amount = _float(value.get("amount"))
    return _years(amount / 100_000) if amount is not None and amount >= 0 else None


@dataclass
class CandidateFacts:
    experience_years: float | None = None
    skills: tuple[str, ...] = ()
    skill_years: dict[str, float] = field(default_factory=dict)
    notice_period_days: int | None = None
    current_ctc: str | None = None  # LPA ("12" or legacy free text like "8 LPA")
    expected_ctc: str | None = None
    current_location: str | None = None
    willing_to_relocate: bool | None = None
    saved_answers: dict[str, str] = field(default_factory=dict)
    # Phase 6A: identity fields typed deterministically into hosted ATS forms (never sent
    # to an LLM) and the owner's local resume PDFs (preferences.resume_files).
    identity: dict[str, str] = field(default_factory=dict)
    resume_files: dict[str, Any] = field(default_factory=dict)
    # Workstream 3: place / employer / authorization facts (stored or deterministically derived).
    city: str | None = None
    state: str | None = None
    country: str | None = None
    country_code: str | None = None
    country_source: str | None = None
    relocation_locations: tuple[str, ...] = ()
    current_company: str | None = None
    work_authorization: str | None = None
    work_authorizations: tuple[WorkAuthorization, ...] = ()
    english_proficiency: str | None = None

    @classmethod
    def from_profile(cls, profile: dict[str, Any],
                     reviewed_answers: list[tuple[str, str]] | None = None) -> CandidateFacts:
        prefs = profile.get("preferences") or {}
        if not isinstance(prefs, dict):
            prefs = {}
        skills = []
        for item in profile.get("verified_skills") or []:
            name = item.get("name") if isinstance(item, dict) else item
            if isinstance(name, str) and name.strip():
                skills.append(name.strip())
        skill_years: dict[str, float] = {}
        for key, value in (prefs.get("skill_years") or {}).items():
            years = _float(value)
            if isinstance(key, str) and normalize(key) and years is not None:
                skill_years[normalize(key)] = years
        total = _float(prefs.get("total_experience_years"))
        location = _text(prefs.get("current_location"))
        place = place_facts(location, _text(prefs.get("country") or profile.get("country")),
                            _text(profile.get("phone")))
        # willing_to_relocate (v2 key) wins; the dashboard's open_to_relocation is the same fact.
        relocate = next((prefs.get(k) for k in ("willing_to_relocate", "open_to_relocation")
                         if isinstance(prefs.get(k), bool)), None)
        identity = identity_fields(profile)
        company = _text(prefs.get("current_company") or profile.get("current_company"))
        for key, value in (("city", place.city), ("state", place.state), ("country", place.country),
                           ("current_company", company)):
            if value:
                identity.setdefault(key, value)
        # Only explicitly stored facts: never derive expected CTC from min_ctc.
        return cls(
            experience_years=total if total is not None else _float(profile.get("verified_experience_years")),
            skills=tuple(skills),
            skill_years=skill_years,
            notice_period_days=_int(prefs.get("notice_period_days")),
            current_ctc=_text(prefs.get("current_ctc")) or _lpa_from_compensation(prefs.get("current_compensation")),
            expected_ctc=_text(prefs.get("expected_ctc"))
            or _lpa_from_compensation(prefs.get("expected_compensation")),
            current_location=location,
            willing_to_relocate=relocate,
            saved_answers={normalize(q): a for q, a in reviewed_answers or []},
            identity=identity,
            resume_files=dict(prefs.get("resume_files") or {}) if isinstance(prefs.get("resume_files"), dict)
            else {},
            city=place.city, state=place.state, country=place.country, country_code=place.country_code,
            country_source=place.country_source,
            relocation_locations=tuple(x.strip() for x in prefs.get("relocation_locations") or ()
                                       if isinstance(x, str) and x.strip()),
            current_company=company,
            work_authorization=_text(prefs.get("work_authorization")),
            work_authorizations=_work_authorizations(prefs.get("work_authorizations")),
            english_proficiency=_text(prefs.get("english_proficiency")),
        )

    def has_skill(self, skill: str) -> bool:
        wanted = normalize(skill)
        if self.skill_years.get(wanted, 0) > 0:
            return True
        return any(normalize(s) == wanted for s in self.skills)


def _float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None and str(value).strip() != "" else None
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None


def _years(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


def choose_option(options: tuple[str, ...], answer: str) -> str | None:
    """Pick the option that exactly or numerically matches `answer`."""
    if not options:
        return answer
    wanted = normalize(answer)
    for option in options:
        if normalize(option) == wanted:
            return option
    return None


def match_option(answer: str, options: tuple[str, ...]) -> str | None:
    """Owner reply -> exact option: 1-based index, exact text, or case-insensitive match.

    Stricter than choose_option on purpose: a human reply that is not clearly one
    of the options is rejected (the HITL stays OPEN) instead of guessed.
    """
    text = " ".join((answer or "").split())
    if not options:
        return text or None
    if text.isdigit() and 1 <= int(text) <= len(options):
        return options[int(text) - 1]
    folded = text.casefold()
    for option in options:
        if " ".join(option.split()).casefold() == folded:
            return option
    return None


def hitl_override(question: str, options: tuple[str, ...], answers: dict[str, str] | None) -> str | None:
    """Owner answer resolved through Telegram/dashboard HITL for this exact question."""
    wanted = normalize(question)
    if not answers or not wanted:
        return None
    for asked, answer in reversed(list(answers.items())):
        if normalize(asked) == wanted:
            return match_option(answer, options) or match_multi(answer, options)
    return None


MULTI_SPLIT = re.compile(r"\s*(?:,|;|\||\band\b)\s*", re.IGNORECASE)


def match_multi(answer: str, options: tuple[str, ...]) -> str | None:
    """Multi-select answer ("Python, Go"): every part must match an option; canonical ", "-joined."""
    parts = [p for p in MULTI_SPLIT.split(answer or "") if p.strip()]
    if len(parts) < 2 or not options:
        return None
    matched = [match_option(part, options) for part in parts]
    if not all(matched):
        return None
    return ", ".join(dict.fromkeys(m for m in matched if m))


def choose_yes_no(options: tuple[str, ...], yes: bool) -> str | None:
    pattern = re.compile(r"^(?:yes|y)\b" if yes else r"^(?:no|n)\b", re.IGNORECASE)
    matches = [o for o in options if pattern.match(o.strip())]
    return matches[0] if len(matches) == 1 else (None if options else ("Yes" if yes else "No"))


def choose_notice(options: tuple[str, ...], days: int) -> str | None:
    if not options:
        return str(days)
    best: tuple[int, str] | None = None
    for option in options:
        text = option.lower()
        if re.search(r"immediate|serving|\b0 days?\b", text):
            limit = 0
        else:
            numbers = [int(n) for n in re.findall(r"\d+", text)]
            if not numbers:
                continue
            factor = 30 if "month" in text else 7 if "week" in text else 1
            limit = max(numbers) * factor
            if re.search(r"more than|above|\+|over", text):
                limit = 10_000
        if limit >= days and (best is None or limit < best[0]):
            best = (limit, option)
    return best[1] if best else None


def lakhs(value: str | None) -> float | None:
    """Stored CTC (LPA) as a number; legacy text like "8 LPA" is accepted."""
    if value is None:
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?|lacs?|l)?\s*", value, re.IGNORECASE)
    return float(match.group(1)) if match else None


def ctc_answer(question: str, options: tuple[str, ...], stored: str | None) -> str | None:
    """CTC in the unit the question asks for. Monthly / hourly / non-INR figures need a human."""
    if stored is None or MONTHLY.search(question) or FOREIGN_PAY.search(question) \
            or any(FOREIGN_PAY.search(o) for o in options):
        return None
    amount = lakhs(stored)
    if amount is None:
        return choose_option(options, stored)
    if options:
        return _ctc_option(options, amount)
    if LAKH_UNIT.search(question):
        return _years(amount)
    if RUPEE_UNIT.search(question):
        return str(round(amount * 100_000))
    return f"{_years(amount)} LPA"


def _ctc_option(options: tuple[str, ...], amount: float) -> str | None:
    for option in options:
        numbers = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", option)]
        if not numbers:
            continue
        # Rupee-denominated options ("5,00,000 - 10,00,000") are converted to lakhs.
        numbers = [n / 100_000 if n >= 1000 else n for n in numbers]
        low, high = (numbers[0], numbers[-1]) if len(numbers) > 1 else (numbers[0], numbers[0])
        text = option.lower()
        if re.search(r"\+|more than|above|over", text):
            high = float("inf")
        if re.search(r"less than|below|under|upto|up to", text):
            low, high = 0.0, numbers[0]
        if low <= amount <= high:
            return option
    return None


def _same_place(a: str, b: str) -> bool:
    left, right = _city_key(a), _city_key(b)
    return bool(left) and (left == right or left in right.split() or right in left.split())


def place_match(target: str, facts: CandidateFacts) -> bool | None:
    """Is the candidate in `target` (city, Indian state or country)? None when unknown."""
    country = country_of(target)
    if country is not None:
        return None if facts.country_code is None and facts.country is None else (
            country[1] == facts.country_code or _letters(country[0]) == _letters(facts.country or ""))
    if _city_key(target) in INDIAN_STATES and _city_key(target) not in INDIAN_CITY_STATE:
        return None if facts.state is None else _city_key(target) == _city_key(facts.state)
    if facts.current_location:
        return any(_same_place(target, part) for part in facts.current_location.split(",") if part.strip()) \
            or _same_place(target, facts.current_location)
    return None


def choose_place(options: tuple[str, ...], place: str) -> str | None:
    """Exact option, else the single option whose leading place part is the same place."""
    exact = choose_option(options, place)
    if exact is not None or not options:
        return exact
    wanted = _city_key(place.split(",")[0])
    hits = [o for o in options if wanted and _city_key(re.split(r"[,(/|-]", o)[0]) == wanted]
    return hits[0] if len(hits) == 1 else None


def choose_country(options: tuple[str, ...], display: str, code: str | None) -> str | None:
    """Country option: exact name/alias ("India"), else a single "India (+91)" / "India +91" style option.

    Never a substring hit such as "British Indian Ocean Territory" or "Indiana"."""
    if not options:
        return display
    aliases = {alias for alias, (_, iso) in COUNTRIES.items() if iso == code} | {_letters(display)}
    exact = [o for o in options if not re.search(r"\d", o) and _letters(o) in aliases]
    if exact:
        return exact[0]  # every hit is an alias of the same country ("United States" / "USA")
    dialing = [o for o in options if re.search(r"\d", o) and _letters(o) in aliases]
    if len(dialing) == 1:
        return dialing[0]
    if code:
        coded = [o for o in options if o.strip().upper() == code]
        if len(coded) == 1:
            return coded[0]
    return None


def choose_text_option(options: tuple[str, ...], answer: str) -> str | None:
    """Stored free-text fact -> exact option, else the single option containing it (word-bounded)."""
    exact = choose_option(options, answer)
    if exact is not None or not options:
        return exact
    wanted = _letters(answer)
    hits = [o for o in options if wanted and (f" {wanted} " in f" {_letters(o)} "
                                              or f" {_letters(o)} " in f" {wanted} ")]
    return hits[0] if len(hits) == 1 else None


def _threshold_answer(question: str, options: tuple[str, ...], facts: CandidateFacts) -> tuple[bool, str | None]:
    """(handled, answer) for "at least N years of experience [in X]?" yes/no questions."""
    match = YEARS_THRESHOLD.search(question)
    if not match or (options and not _yes_no_only(options)) or not YES_NO_QUESTION.search(question):
        return False, None
    rest = match.group("rest")
    skill = THRESHOLD_SKILL.match(rest) if rest.strip(" ?.") else None
    if rest.strip(" ?.") and skill is None:
        return True, None  # "... experience as a team lead?" - not a stored fact
    if skill is not None and normalize(skill.group("skill")) not in GENERIC_FIELDS:
        years = facts.skill_years.get(normalize(skill.group("skill")))
    else:
        years = facts.experience_years
    if years is None:
        return True, None  # never claim N years we cannot verify
    needed = float(match.group("n"))
    strict = (match.group("op") or "").lower() in ("more than", "over")
    return True, choose_yes_no(options, years > needed if strict else years >= needed)


def _authorization_answer(question: str, options: tuple[str, ...], facts: CandidateFacts) -> tuple[bool, str | None]:
    """Work authorization / sponsorship from preferences.work_authorizations (per country) or the
    free-text preferences.work_authorization status. Unknown country -> human."""
    sponsorship = bool(SPONSORSHIP_Q.search(question))
    if not sponsorship and not WORK_AUTH_Q.search(question):
        return False, None
    yes_no = not options or _yes_no_only(options)
    mentioned = countries_mentioned(question)
    if yes_no and len(mentioned) == 1:
        code = next(iter(mentioned))
        row = next((r for r in facts.work_authorizations if r.country_code == code), None)
        if row is None:
            return True, None
        value = row.requires_sponsorship if sponsorship else row.authorized
        return True, None if value is None else choose_yes_no(options, value)
    if facts.work_authorization and not sponsorship and not mentioned and (not options or not yes_no) \
            and not YES_NO_QUESTION.search(question):
        return True, choose_text_option(options, facts.work_authorization)
    return True, None


def _link_answer(question: str, options: tuple[str, ...], facts: CandidateFacts) -> tuple[bool, str | None]:
    if options or LINK_CONTEXT.search(question) or YES_NO_QUESTION.search(question):
        return False, None
    for pattern, key in ((LINKEDIN_Q, "linkedin_url"), (GITHUB_Q, "github_url"), (PORTFOLIO_Q, "portfolio_url")):
        if pattern.search(question):
            return True, facts.identity.get(key)
    return False, None


def resolve_answer(question: str, options: tuple[str, ...], facts: CandidateFacts) -> str | None:
    """Return an exact option/text answer, or None when a human must answer."""
    if BLOCKED.search(question) or SENSITIVE.search(question):
        return None
    saved = facts.saved_answers.get(normalize(question))
    if saved:
        return choose_option(options, saved)
    if facts.notice_period_days is not None:
        within = JOIN_WITHIN.search(question)
        if within:
            unit = within.group("unit").lower()
            limit = int(within.group("n")) * (30 if unit.startswith("month") else 7 if unit.startswith("week") else 1)
            return choose_yes_no(options, facts.notice_period_days <= limit)
        if IMMEDIATE_JOINER.search(question) and (not options or _yes_no_only(options)):
            return choose_yes_no(options, facts.notice_period_days == 0)
        if NOTICE.search(question):
            return choose_notice(options, facts.notice_period_days)
        if START_WHEN.search(question):
            if options:
                return choose_notice(options, facts.notice_period_days)
            return "Immediately" if facts.notice_period_days == 0 else f"Within {facts.notice_period_days} days"
    if CURRENT_CTC.search(question):
        return ctc_answer(question, options, facts.current_ctc)
    if EXPECTED_CTC.search(question):
        return ctc_answer(question, options, facts.expected_ctc)
    handled, answer = _authorization_answer(question, options, facts)
    if handled:
        return answer
    located = LOCATED_IN.search(question)
    if located:
        matched = place_match(located.group("city"), facts)
        if matched is not None:
            return choose_yes_no(options, matched)
        if not facts.current_location:
            return None
    if COUNTRY_Q.search(question):
        return choose_country(options, facts.country, facts.country_code) if facts.country else None
    if STATE_Q.search(question):
        return choose_place(options, facts.state) if facts.state else None
    if CITY_Q.search(question):
        return choose_place(options, facts.city) if facts.city else None
    if CURRENT_LOCATION.search(question):
        return choose_place(options, facts.current_location) if facts.current_location else None
    if CURRENT_COMPANY_Q.search(question):
        return choose_text_option(options, facts.current_company) if facts.current_company else None
    if ENGLISH_Q.search(question):
        return choose_text_option(options, facts.english_proficiency) if facts.english_proficiency else None
    handled, answer = _link_answer(question, options, facts)
    if handled:
        return answer
    if RELOCATE.search(question):
        target = RELOCATE_TARGET.search(question)
        if target:
            place = target.group("city")
            if place_match(place, facts) or any(_same_place(place, loc) for loc in facts.relocation_locations):
                return choose_yes_no(options, True)
        if facts.willing_to_relocate is not None:
            return choose_yes_no(options, facts.willing_to_relocate)
        return None
    handled, answer = _threshold_answer(question, options, facts)
    if handled:
        return answer
    skill_match = SKILL_EXPERIENCE.search(question) or SKILL_YES_NO.search(question)
    if skill_match and normalize(skill_match.group("skill")) in GENERIC_FIELDS:
        skill_match = None
    if options and _yes_no_only(options) and skill_match:
        skill = skill_match.group("skill")
        if facts.has_skill(skill):
            return choose_yes_no(options, True)
        # "No" only for a recognizable technology; "comfortable with on-call rotations?" is not a
        # skill, so it falls through to the cache / LLM / human instead of a fabricated "No".
        return choose_yes_no(options, False) if is_known_tech(skill) else None
    if skill_match:
        years = facts.skill_years.get(normalize(skill_match.group("skill")))
        if years is None:
            return None
        return _numeric_option(options, years) if options else _years(years)
    if TOTAL_EXPERIENCE.search(question) and facts.experience_years is not None:
        return (_numeric_option(options, facts.experience_years) if options
                else _years(facts.experience_years))
    return None


def _yes_no_only(options: tuple[str, ...]) -> bool:
    return all(re.match(r"^(?:yes|no|y|n)\b", o.strip(), re.IGNORECASE) for o in options)


def _numeric_option(options: tuple[str, ...], years: float) -> str | None:
    for option in options:
        numbers = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", option)]
        if not numbers:
            continue
        low, high = (numbers[0], numbers[-1]) if len(numbers) > 1 else (numbers[0], numbers[0])
        if re.search(r"\+|more than|above", option.lower()):
            high = float("inf")
        if re.search(r"less than|below|under", option.lower()):
            low, high = 0.0, numbers[0]
        if low <= years <= high:
            return option
    return None
