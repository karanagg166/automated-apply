"""Owner-declared screening disclosures (EEO, consent, NDA signature) as tier-0 answers.

These question families are normally refused by the BLOCKED / SENSITIVE gate and always go
to the human. When the owner has explicitly stored the matching fact in
``preferences.screening_disclosures`` the answer is filled here, before that gate. Nothing
is derived: a missing fact returns ``(False, None)`` and the old gate applies unchanged.
Credentials, OTPs, government IDs, bank data, sexual orientation, religion, e-mail/login
fields and legal declarations never reach a family matcher (``NEVER``).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date
from typing import TYPE_CHECKING, Any

from backend.app.browser_v2.answers.classifier import YES_NO_QUESTION
from backend.app.browser_v2.answers.deterministic import choose_text_option
from backend.app.browser_v2.answers.geography import (
    COUNTRIES,
    choose_country,
    countries_mentioned,
    country_of,
)
from backend.app.browser_v2.answers.normalizers import (
    _letters,
    choose_option,
    choose_yes_no,
)

if TYPE_CHECKING:
    from backend.app.browser_v2.answers.facts import CandidateFacts

I = re.IGNORECASE
NEVER = re.compile(
    r"password|passcode|verification code|one.time (?:code|password)|\botp\b|social security|\bssn\b|"
    r"government (?:id|identifier)|aadhaa?r|\bpan (?:card|number)|bank account|credit card|\bcvv\b|"
    r"sexual orientation|religio|\be-?mail\b|\blog ?in\b|\bsign ?in\b|legal declaration|perjury|"
    r"\bi (?:hereby )?(?:certify|declare)\b|passport\s*(?:number|no\b|#)|"
    r"\b(?:sms|text messages?|whatsapp|marketing|newsletters?|promotional)\b", I)
NDA_Q = re.compile(r"\bnda\b|non-?\s?disclosure|confidentiality agreement", I)
SIGN_BY_NAME = re.compile(r"\b(?:typ(?:e|ing)|enter(?:ing)?|writ(?:e|ing)|provid(?:e|ing)|print(?:ing)?)\b"
                          r".{0,60}\bname\b|\bsignature\b|\be-?sign\b|\bsign\b", I)
NOT_AN_AGREEMENT = re.compile(r"\bhave you\b|\bare you (?:bound|subject)\b|\bcurrent(?:ly)?\b|\bprevious\b|"
                              r"\bemployer\b", I)
CONSENT_VERB = re.compile(r"\b(?:agree|accept|consent|acknowledge|authori[sz]e|allow)\w*\b", I)
WILLING = re.compile(r"\b(?:willing|undergo|submit to|ok(?:ay)? with|comfortable with)\b", I)
BACKGROUND_Q = re.compile(r"\bbackground\s+(?:check|verification|screening|investigation)s?\b|\bbgv\b", I)
DATA_Q = re.compile(r"\bprivacy\b|\bpersonal (?:data|information)\b|\bdata (?:processing|protection|privacy)\b|"
                    r"\bprocess(?:ing)?\s+(?:of\s+)?(?:my|your)\s+(?:personal\s+)?(?:data|information)\b|"
                    r"\bgdpr\b|\bretain\w*\s+(?:my|your)\s+(?:data|information|application)\b", I)
TERMS_Q = re.compile(r"\bterms\s*(?:and|&)\s*conditions\b|\bterms\s+of\s+(?:use|service)\b|"
                     r"\b(?:the|these|our|above|all)\s+terms\b(?!\s+of\b)", I)
HISPANIC_Q = re.compile(r"\bhispanic\b|\blatin[oax]\b", I)
RACE_Q = re.compile(r"\brace\b(?!\s+conditions?)|\bracial\b|\bethnic(?:ity|al)?\b", I)
PRONOUN_Q = re.compile(r"\bpronouns?\b", I)
GENDER_Q = re.compile(r"\bgender\b|^\s*sex\s*\??\s*$|\bwhat is your sex\b", I)
VETERAN_Q = re.compile(r"\bveterans?\b|\bmilitary (?:service|status)\b|\barmed forces\b", I)
DISABILITY_Q = re.compile(r"\bdisabilit|\bhandicap", I)
ACCOMMODATION = re.compile(r"accommodat", I)
DOB_Q = re.compile(r"\bdate of birth\b|\bd\.?o\.?b\b|\bbirth\s?date\b|\bwhen were you born\b", I)
PASSPORT_Q = re.compile(r"\bpassport\b", I)
PASSPORT_DETAIL = re.compile(r"\bnumber\b|#|expir|\bissu(?:e|ed|ing)\b|\bcopy\b|\bscan|upload|attach|photo|"
                             r"details|which country", I)
CITIZEN_Q = re.compile(r"\bcitizenship\b|\bnationality\b|\bcitizen\b", I)
EMPLOYED_Q = re.compile(r"\bare you (?:currently |presently )?employed\b|"
                        r"\bare you (?:currently |presently )?working\s*(?:\?|$|anywhere\b)|"
                        r"^\s*(?:current\s+)?employment status\s*\??\s*$|^\s*currently employed\s*\??\s*$", I)
DATE_FORMAT = re.compile(r"\b(dd|mm|yyyy|yy)([/.\-])(dd|mm|yyyy|yy)\2(dd|mm|yyyy|yy)\b", I)
DECLINE = re.compile(r"\bdecline|prefer not|rather not|choose not|\bwish not\b|"
                     r"(?:do not|don'?t|not) (?:wish|want) to|not to (?:answer|disclose|say|self|identify)", I)
NEGATIVE = re.compile(r"\b(?:no|not|non|never|none|dont|cannot)\b|n't\b", I)
GENDER_ALIASES = {"male": ("man",), "man": ("male",), "female": ("woman",), "woman": ("female",)}
DEMONYMS = {"indian": "IN", "american": "US", "british": "GB", "canadian": "CA", "australian": "AU",
            "german": "DE", "singaporean": "SG"}

Handled = tuple[bool, str | None]
NOT_HANDLED: Handled = (False, None)


def disclosure_answer(question: str, options: tuple[str, ...], facts: CandidateFacts) -> Handled:
    """(handled, answer) for owner-declared EEO / consent / NDA questions.

    handled=False: not a disclosure question, or its fact is not stored -> the normal gate applies.
    handled=True with answer None: the fact is stored but no option fits safely -> human.
    """
    stored: dict[str, Any] = getattr(facts, "disclosures", None) or {}
    if not stored or not question.strip() or NEVER.search(question):
        return NOT_HANDLED
    for family in FAMILIES:
        result = family(question, options, stored)
        if result is not None:
            return result
    return NOT_HANDLED


# --- option pickers ----------------------------------------------------------------------------
def _kind(text: str) -> str:
    return "decline" if DECLINE.search(text) else "negative" if NEGATIVE.search(text) else "positive"


def _has_yes_no(options: tuple[str, ...]) -> bool:
    return any(re.match(r"^(?:yes|no)\b", o.strip(), I) for o in options)


def _yes_no_shape(question: str, options: tuple[str, ...]) -> bool:
    return _has_yes_no(options) if options else bool(YES_NO_QUESTION.search(question))


def _kind_option(options: tuple[str, ...], kind: str, stored: str = "") -> str | None:
    """The single option of the same polarity (positive / negative / decline) as the stored value."""
    hits = [o for o in options if _kind(o) == kind]
    if len(hits) > 1 and stored:
        hits = [o for o in hits if f" {_letters(stored)} " in f" {_letters(o)} "]  # option states it in full
    return hits[0] if len(hits) == 1 else None


def _polar_option(options: tuple[str, ...], stored: str) -> str | None:
    """"I am not a protected veteran" / "No" -> the one option with the same meaning."""
    if not options:
        return stored
    return choose_option(options, stored) or _kind_option(options, _kind(stored), stored)


def _agree(options: tuple[str, ...], yes: bool) -> str | None:
    return choose_yes_no(options, yes) or (_kind_option(options, "positive" if yes else "negative")
                                           if options else None)


def _ethnicity_option(options: tuple[str, ...], stored: str) -> str | None:
    """"Asian (Indian)" -> the single option naming "Asian" (qualifier breaks ties)."""
    exact = choose_text_option(options, stored)
    if exact is not None or not options:
        return exact
    if _kind(stored) == "decline":
        return _kind_option(options, "decline")
    head = _letters(re.sub(r"\([^)]*\)", " ", stored))
    qualifier = _letters(" ".join(re.findall(r"\(([^)]*)\)", stored)))
    hits = [o for o in options if head and f" {head} " in f" {_letters(o)} " and _kind(o) != "decline"]
    if len(hits) > 1 and qualifier:
        hits = [o for o in hits if all(f" {w} " in f" {_letters(o)} " for w in qualifier.split())]
    return hits[0] if len(hits) == 1 else None


def _gender_option(options: tuple[str, ...], stored: str) -> str | None:
    exact = choose_text_option(options, stored)
    if exact is not None or not options:
        return exact
    if _kind(stored) == "decline":
        return _kind_option(options, "decline")
    for alias in GENDER_ALIASES.get(_letters(stored), ()):
        hit = choose_text_option(options, alias)
        if hit is not None:
            return hit
    return None


def _country_code(text: str) -> tuple[str, str] | None:
    found = country_of(text)
    if found:
        return found
    key = " ".join(w for w in _letters(text).split() if w not in ("citizen", "national", "citizenship"))
    found = country_of(key)
    if found:
        return found
    code = DEMONYMS.get(key)
    names = [display for display, iso in COUNTRIES.values() if iso == code]
    return (names[0], code) if code and names else None


def _format_date(value: date, question: str) -> str:
    """ISO by default; "(DD/MM/YYYY)"-style hints in the question are honoured."""
    match = DATE_FORMAT.search(question)
    if match:
        parts = [match.group(1).lower(), match.group(3).lower(), match.group(4).lower()]
        if {"dd", "mm"} <= set(parts) and len(set(parts)) == 3:
            codes = {"dd": "%d", "mm": "%m", "yyyy": "%Y", "yy": "%y"}
            return value.strftime(match.group(2).join(codes[p] for p in parts))
    return value.isoformat()


# --- question families: None = not this family; (False, None) = fact not stored ----------------
def _nda(question: str, options: tuple[str, ...], d: dict[str, Any]) -> Handled | None:
    if not NDA_Q.search(question):
        return None
    name = d.get("nda_signature_name")
    if d.get("nda_auto_sign") is not True or not name or NOT_AN_AGREEMENT.search(question):
        return NOT_HANDLED
    if options:
        return (True, _agree(options, True)) if CONSENT_VERB.search(question) or SIGN_BY_NAME.search(question) \
            else NOT_HANDLED
    return (True, name) if SIGN_BY_NAME.search(question) else NOT_HANDLED


def _consent(question: str, options: tuple[str, ...], d: dict[str, Any]) -> Handled | None:
    needed = [key for key, pattern in (("consent_background_check", BACKGROUND_Q),
                                       ("consent_data_processing", DATA_Q), ("agree_terms", TERMS_Q))
              if pattern.search(question)]
    if not needed or not (CONSENT_VERB.search(question)
                          or (BACKGROUND_Q.search(question) and WILLING.search(question))):
        return None
    values = [d.get(key) for key in needed]
    if not all(isinstance(v, bool) for v in values):
        return NOT_HANDLED
    return True, _agree(options, all(values))


def _hispanic(question: str, options: tuple[str, ...], d: dict[str, Any]) -> Handled | None:
    if not HISPANIC_Q.search(question) or not _yes_no_shape(question, options):
        return None  # a race list that merely mentions "Not Hispanic or Latino" is _race's job
    ethnicity = d.get("ethnicity")
    if not ethnicity:
        return NOT_HANDLED
    if _kind(ethnicity) == "decline":
        return True, _kind_option(options, "decline") if options else ethnicity
    hispanic = bool(HISPANIC_Q.search(ethnicity)) and not re.search(r"\bnot\s+(?:hispanic|latin)", ethnicity, I)
    return True, choose_yes_no(options, hispanic)


def _text_family(pattern: re.Pattern[str], key: str,
                 pick: Callable[[tuple[str, ...], str], str | None]) -> Callable[..., Handled | None]:
    def family(question: str, options: tuple[str, ...], d: dict[str, Any]) -> Handled | None:
        if not pattern.search(question):
            return None
        value = d.get(key)
        return (True, pick(options, value)) if value else NOT_HANDLED
    return family


def _veteran(question: str, options: tuple[str, ...], d: dict[str, Any]) -> Handled | None:
    if not VETERAN_Q.search(question):
        return None
    if DISABILITY_Q.search(question) or not d.get("veteran_status"):
        return NOT_HANDLED  # a combined veteran + disability question is not one fact
    return True, _polar_option(options, d["veteran_status"])


def _disability(question: str, options: tuple[str, ...], d: dict[str, Any]) -> Handled | None:
    if not DISABILITY_Q.search(question):
        return None
    if ACCOMMODATION.search(question) or not d.get("disability_status"):
        return NOT_HANDLED  # "need an accommodation?" is a different question
    return True, _polar_option(options, d["disability_status"])


def _dob(question: str, options: tuple[str, ...], d: dict[str, Any]) -> Handled | None:
    if not DOB_Q.search(question):
        return None
    value = d.get("date_of_birth")
    if not isinstance(value, date):
        return NOT_HANDLED
    return True, None if options else _format_date(value, question)


def _passport(question: str, options: tuple[str, ...], d: dict[str, Any]) -> Handled | None:
    if not PASSPORT_Q.search(question):
        return None
    value = d.get("has_valid_passport")
    if not isinstance(value, bool) or PASSPORT_DETAIL.search(question) or not _yes_no_shape(question, options):
        return NOT_HANDLED
    return True, choose_yes_no(options, value)


def _citizenship(question: str, options: tuple[str, ...], d: dict[str, Any]) -> Handled | None:
    if not CITIZEN_Q.search(question):
        return None
    stored = d.get("citizenship")
    if not stored:
        return NOT_HANDLED
    country = _country_code(stored)
    if _yes_no_shape(question, options):
        mentioned = countries_mentioned(question)
        if len(mentioned) == 1 and country:
            return True, choose_yes_no(options, country[1] in mentioned)
        return True, None  # "dual citizenship?", unnamed country -> human
    if not options:
        return True, stored
    if country:
        hit = choose_country(options, country[0], country[1])
        demonym = next((word for word, code in DEMONYMS.items() if code == country[1]), None)
        hit = hit or (choose_text_option(options, demonym) if demonym else None)
        if hit:
            return True, hit
    return True, choose_text_option(options, stored)


def _employed(question: str, options: tuple[str, ...], d: dict[str, Any]) -> Handled | None:
    if not EMPLOYED_Q.search(question):
        return None
    value = d.get("currently_employed")
    if not isinstance(value, bool):
        return NOT_HANDLED
    if not options or _has_yes_no(options):
        return True, choose_yes_no(options, value)
    wanted = re.compile(r"^(?:currently\s+)?employed\b" if value else r"^(?:unemployed|not (?:currently )?employed)\b", I)
    hits = [o for o in options if wanted.match(o.strip())]
    return True, hits[0] if len(hits) == 1 else None


FAMILIES: tuple[Callable[[str, tuple[str, ...], dict[str, Any]], Handled | None], ...] = (
    _nda, _consent, _hispanic,
    _text_family(RACE_Q, "ethnicity", _ethnicity_option),
    _text_family(PRONOUN_Q, "pronouns", choose_text_option),
    _text_family(GENDER_Q, "gender", _gender_option),
    _veteran, _disability, _dob, _passport, _citizenship, _employed,
)
