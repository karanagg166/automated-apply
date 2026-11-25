"""Tailored recruiter outreach: free LLM router (task="email_draft") with a deterministic
template fallback, so quota-hit drafting still works fully offline / keyless.

Only the PII-scrubbed professional profile and a bounded JD summary reach the LLM (the
router scrubs every prompt again). The greeting and the sign-off (name, email, phone,
links) are injected locally AFTER generation and never leave the machine.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from backend.app.ai_v2.pii import build_safe_llm_profile
from backend.app.browser_v2.portals import portal_label
from backend.app.browser_v2.rules import contains_term, normalize_text
from backend.app.mail_v2.message import DraftContent

logger = logging.getLogger(__name__)

MIN_WORDS, MAX_WORDS = 60, 230
JD_SUMMARY_CHARS = 1_500
BUZZWORDS = re.compile(r"\b(?:rockstar|ninja|guru|synergy|synergies|thought leader|game[- ]changer|"
                       r"world[- ]class|10x|crush(?:ing)?|unicorn)\b", re.IGNORECASE)
PLACEHOLDER = re.compile(r"\[[^\]]{2,40}\]|\{[^}]{1,40}\}|<[A-Z _]{2,40}>|REDACTED|lorem ipsum", re.IGNORECASE)
GREETING = re.compile(r"^\s*(?:hi|hello|dear|hey|greetings)\b[^\n]{0,60}[,!:]?\s*\n+", re.IGNORECASE)
CLOSING = re.compile(r"\n\s*(?:best regards|kind regards|warm regards|regards|best|thanks|thank you|sincerely|"
                     r"cheers)[,!.]?\s*(?:\n.*)?$", re.IGNORECASE | re.DOTALL)

SYSTEM_PROMPT = (
    "You write short, specific cold emails from a software engineer to a recruiter about one open role. "
    "Rules: 120-180 words; plain text; 2-3 short paragraphs; confident and concrete, no hype; mention 2-3 "
    "skills or projects from the candidate profile that match the job; never invent employers, dates, "
    "degrees, numbers, certifications, salary or visa facts that are not in the profile; no buzzwords; "
    "no greeting line and no sign-off (both are added later); end with one low-pressure ask for a short "
    "conversation. Return ONLY JSON: {\"subject\": \"...\", \"body\": \"...\"}. The subject is under "
    "70 characters and names the role.")


class EmailDraftModel(BaseModel):
    subject: str = Field(min_length=5, max_length=120)
    body: str = Field(min_length=120, max_length=2_500)


@dataclass(frozen=True)
class DraftJob:
    role_title: str | None
    company_name: str | None
    platform: str | None = None
    job_url: str | None = None
    jd_text: str | None = None
    recipient_first_name: str | None = None


def _strings(values: Any, limit: int = 8) -> list[str]:
    if not isinstance(values, (list, tuple)):
        return []
    return [v.strip() for v in values if isinstance(v, str) and v.strip()][:limit]


def _years(profile: Mapping[str, Any]) -> float | None:
    prefs = profile.get("preferences") or {}
    for value in (prefs.get("total_experience_years") if isinstance(prefs, Mapping) else None,
                  profile.get("verified_experience_years")):
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            continue
        try:
            number = float(value)
        except ValueError:
            continue
        if 0 <= number <= 50:
            return number
    return None


def signature(profile: Mapping[str, Any]) -> str:
    lines = ["Best regards,"]
    for key in ("full_name", "phone", "email", "linkedin_url", "github_url", "portfolio_url"):
        value = profile.get(key)
        if isinstance(value, str) and value.strip():
            lines.append(value.strip())
    return "\n".join(lines)


def greeting(job: DraftJob) -> str:
    name = (job.recipient_first_name or "").strip()
    if name and re.fullmatch(r"[A-Za-z][A-Za-z'-]{1,30}", name):
        return f"Hi {name},"
    company = (job.company_name or "").strip()
    return f"Hi {company} hiring team," if company else "Hello,"


def _role(job: DraftJob) -> str:
    return (job.role_title or "the open role").strip()[:100]


def matched_skills(profile: Mapping[str, Any], jd_text: str | None, limit: int = 3) -> list[str]:
    """Verified skills / tech stack that also appear in the JD (whole-word match)."""
    prefs = profile.get("preferences") or {}
    pool = _strings(profile.get("verified_skills"), 30) + _strings(
        prefs.get("tech_stack") if isinstance(prefs, Mapping) else [], 30)
    text = normalize_text(jd_text)
    seen: list[str] = []
    for skill in pool:
        if skill.lower() not in (s.lower() for s in seen) and (not text or contains_term(text, skill)):
            seen.append(skill)
        if len(seen) >= limit:
            break
    return seen


def template_draft(job: DraftJob, profile: Mapping[str, Any], *, has_attachment: bool) -> DraftContent:
    """Deterministic, truthful outreach built only from verified profile fields."""
    role, company = _role(job), (job.company_name or "your team").strip()[:100]
    skills = matched_skills(profile, job.jd_text) or _strings(profile.get("verified_skills"), 3)
    years = _years(profile)
    where = f" on {portal_label(job.platform)}" if job.platform else ""
    paragraphs = [f"I came across the {role} opening at {company}{where} and would like to be considered."]
    if skills and years is not None:
        paragraphs.append(f"I have {years:g} years of hands-on experience, mostly with {', '.join(skills)}.")
    elif skills:
        paragraphs.append(f"My day-to-day work is centred on {', '.join(skills)}.")
    projects = [p for p in profile.get("projects") or [] if isinstance(p, Mapping)]
    names = [str(p.get("name") or p.get("title")).strip() for p in projects if (p.get("name") or p.get("title"))]
    if names:
        listed = " and ".join(names[:2])
        paragraphs[-1] += f" Recent work includes {listed}."
    if job.jd_text and skills:
        paragraphs.append(f"The role's focus on {skills[0]} lines up closely with what I build, so I believe "
                          f"I could contribute quickly.")
    paragraphs.append(("My resume is attached. " if has_attachment else "")
                      + "Would you be open to a short conversation about the role?")
    return DraftContent(subject=f"Application: {role} at {company}"[:120], body="\n\n".join(paragraphs),
                        composer="template")


def clean_llm_body(body: str) -> str | None:
    text = body.replace("\r\n", "\n").strip()
    text = GREETING.sub("", text, count=1)
    text = CLOSING.sub("", text).strip()
    words = len(text.split())
    if not (MIN_WORDS <= words <= MAX_WORDS) or PLACEHOLDER.search(text) or BUZZWORDS.search(text):
        return None
    return text


class DraftComposer:
    def __init__(self, router: Any | None = None) -> None:
        self.router = router  # ai_v2.router.LLMRouter or None (template only)

    async def compose(self, job: DraftJob, profile: Mapping[str, Any], *,
                      has_attachment: bool = False) -> DraftContent:
        content = await self._llm(job, profile) if self.router is not None else None
        if content is None:
            content = template_draft(job, profile, has_attachment=has_attachment)
        elif has_attachment and "attach" not in content.body.lower():
            content = DraftContent(content.subject, content.body + "\n\nMy resume is attached.",
                                   content.composer, content.provider)
        body = f"{greeting(job)}\n\n{content.body}\n\n{signature(profile)}"
        return DraftContent(subject=content.subject, body=body, composer=content.composer,
                            provider=content.provider)

    async def _llm(self, job: DraftJob, profile: Mapping[str, Any]) -> DraftContent | None:
        from backend.app.ai_v2.router import AllLLMProvidersExhaustedError

        router = self.router
        if router is None or not getattr(router, "any_configured", False):
            return None
        safe = build_safe_llm_profile(profile)
        user = json.dumps({
            "job": {"title": job.role_title, "company": job.company_name,
                    "portal": portal_label(job.platform) if job.platform else None,
                    "description_excerpt": (job.jd_text or "")[:JD_SUMMARY_CHARS]},
            "candidate_profile": safe}, ensure_ascii=False)
        try:
            result = await router.generate_json("email_draft", SYSTEM_PROMPT, user, EmailDraftModel,
                                                     max_output_tokens=500)
        except AllLLMProvidersExhaustedError:
            logger.info("email_draft: LLM chain exhausted, using deterministic template")
            return None
        body = clean_llm_body(result.value.body)
        subject = " ".join(result.value.subject.split())[:120]
        if body is None or PLACEHOLDER.search(subject) or BUZZWORDS.search(subject):
            logger.info("email_draft: LLM output rejected by local checks, using template")
            return None
        return DraftContent(subject=subject, body=body, composer="llm", provider=result.provider)
