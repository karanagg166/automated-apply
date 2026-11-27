"""Screening-question classifiers (regexes) and resolver protocols."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from backend.app.browser_v2.answers.facts import CandidateFacts


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
                               r"\bwhere do you (?:currently )?work\b|\bcompany you (?:currently )?work (?:for|at)\b|"
                               r"\b(?:current\s+or\s+(?:previous|most recent|last)|most recent|latest|last|previous)\s+"
                               r"(?:company|employer|organi[sz]ation)(?:\s+name)?\b",
                               re.IGNORECASE)
CURRENT_TITLE_Q = re.compile(r"\b(?:(?:current|present)(?:\s+or\s+(?:previous|most recent|last))?|most recent|latest|last|"
                             r"previous)\s+(?:job\s+)?(?:title|designation|role|position)\b", re.IGNORECASE)
HEAR_ABOUT_Q = re.compile(r"\bhow did you (?:hear|learn|find out) about\b|\bwhere did you (?:hear|find|learn) about\b|"
                          r"\bhow did you (?:find|discover) (?:this|the|our) (?:job|role|position|opportunity)\b|"
                          r"^\s*(?:application\s+)?source\s*\*?\s*\??\s*$", re.IGNORECASE)
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
