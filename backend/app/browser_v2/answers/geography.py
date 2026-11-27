"""Deterministic place facts (city / state / country), never guessed."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.app.browser_v2.answers.normalizers import _letters, choose_option

if TYPE_CHECKING:
    from backend.app.browser_v2.answers.facts import CandidateFacts


# --- geography (Workstream 3): deterministic place facts, never guessed ---------------------

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


# "work in the US", "U.S. person", "US citizen": the bare lowercase "us" stays ambiguous ("tell us"),
# but an upper-case US / U.S. token or "the us" names the United States.
_US_TOKEN = re.compile(r"(?<![A-Za-z])U\.?S\.?(?:A\.?)?(?![A-Za-z])")


def countries_mentioned(question: str) -> set[str]:
    """ISO codes of countries named in a question (whole words; never a bare lower-case 'us'/'in')."""
    text = f" {_letters(question)} "
    found = {code for alias, (_, code) in COUNTRIES.items() if f" {alias} " in text}
    if _US_TOKEN.search(question or "") or " the us " in text:
        found.add("US")
    return found


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
