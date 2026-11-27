"""Post-apply mail funnel (Milestone 2, pure: no I/O): classify one read-only mail and match it to
one recent application.

Kinds, checked in this order (a rejection usually also says "thank you for applying"):
  REJECTED > OA_INVITE > INTERVIEW_INVITE > CONFIRMATION > RECRUITER_REPLY.
Matching is conservative because a CONFIRMATION can turn a SUBMISSION_UNKNOWN row into APPLIED:
the employer's normalized name must appear in the subject/body (or be the sender's domain label),
the mail must arrive after the submit, and ties between applications at the same company are broken
by role-title overlap or else refused (ambiguous -> no change).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from backend.app.mail_v2.read_models import OTP_CONTEXT, MailMessage

CONFIRMATION = "CONFIRMATION"
OA_INVITE = "OA_INVITE"
INTERVIEW_INVITE = "INTERVIEW_INVITE"
RECRUITER_REPLY = "RECRUITER_REPLY"
REJECTED = "REJECTED"
FUNNEL_KINDS = (REJECTED, OA_INVITE, INTERVIEW_INVITE, CONFIRMATION, RECRUITER_REPLY)
# mail_events.kind stored per funnel kind (INTERVIEW_INVITE keeps the 004 'INTERVIEW' label).
EVENT_KIND = {CONFIRMATION: "CONFIRMATION", OA_INVITE: "OA_INVITE", INTERVIEW_INVITE: "INTERVIEW",
              RECRUITER_REPLY: "RECRUITER_REPLY", REJECTED: "REJECTED"}
# Before followup 008 only the 004 kinds exist: an OA is stored as INTERVIEW, the rest are not stored.
LEGACY_EVENT_KIND = {OA_INVITE: "INTERVIEW", INTERVIEW_INVITE: "INTERVIEW", RECRUITER_REPLY: "RECRUITER_REPLY"}

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (REJECTED, re.compile(
        r"\bunfortunately\b|\bregret to inform\b|\bnot (?:be )?(?:moving|move) forward\b|"
        r"\bdecided (?:not )?to (?:move|proceed) (?:forward )?with other candidates\b|\bnot been selected\b|"
        r"\bnot selected\b|\bposition has (?:been|now been) filled\b|\bwill not be progressing\b|"
        r"\bpursue other candidates\b", re.IGNORECASE)),
    (OA_INVITE, re.compile(
        r"\bonline assessment\b|\bcoding (?:assessment|challenge|test|round)\b|\bhackerrank\b|\bcodility\b|"
        r"\bcodesignal\b|\bhackerearth\b|\btestgorilla\b|\btake[- ]home\b|\bassessment (?:invitation|invite|link)\b|"
        r"\bcomplete (?:the|this|an|your) (?:\w+ )?assessment\b", re.IGNORECASE)),
    (INTERVIEW_INVITE, re.compile(
        r"\binterview\b|\bschedule (?:a|your|an) (?:call|chat|conversation|time)\b|\bcalendly\.com\b|"
        r"\bphone screen\b|\bnext round\b|\bshortlisted\b|\bmeet (?:with )?the team\b", re.IGNORECASE)),
    (CONFIRMATION, re.compile(
        r"\bthank(?:s| you) for (?:applying|your application|your interest)\b|\bapplication (?:has been )?received\b|"
        r"\bwe(?:'ve| have) received your application\b|\bapplication (?:was |has been )?submitted\b|"
        r"\bsuccessfully applied\b|\bapplication confirmation\b|\breceived your application\b", re.IGNORECASE)),
    (RECRUITER_REPLY, re.compile(
        r"\brecruit(?:er|ing|ment)\b|\btalent acquisition\b|\bhiring (?:manager|team)\b|^re:", re.IGNORECASE)),
)
ATS_SENDERS = re.compile(r"(?:^|\.)(?:greenhouse(?:-mail)?\.io|lever\.co|hire\.lever\.co|ashbyhq\.com|"
                         r"smartrecruiters\.com|myworkday(?:jobs)?\.com|workablemail\.com|workable\.com|"
                         r"naukri\.com|instahyre\.com|internshala\.com|wellfound\.com)$", re.IGNORECASE)
COMPANY_SUFFIXES = frozenset({"inc", "llc", "ltd", "pvt", "private", "limited", "technologies", "technology",
                              "labs", "corp", "corporation", "co", "gmbh", "solutions", "software", "systems",
                              "the", "india", "group", "holdings", "hq", "ai"})
STOPWORDS = frozenset({"and", "of", "the", "for", "a", "an", "to", "in", "with", "at", "i", "ii", "iii", "sr", "jr"})
ARRIVAL_SLACK = timedelta(minutes=30)
TEXT_CHARS = 4000
MIN_COMPANY_CHARS = 3


def _words(value: str | None) -> list[str]:
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def normalize_company(name: str | None) -> str:
    words = _words(name)
    while words and words[-1] in COMPANY_SUFFIXES:
        words.pop()
    while words and words[0] == "the":
        words.pop(0)
    return " ".join(words)


def classify(message: MailMessage) -> str | None:
    text = f"{message.subject}\n{(message.body or '')[:TEXT_CHARS]}"
    if OTP_CONTEXT.search(text[:1500]):
        return None  # security / verification-code mails are the OTP resolver's, never the funnel's
    for kind, pattern in PATTERNS:
        if kind == RECRUITER_REPLY:
            if pattern.search(message.subject) or pattern.search(text[:TEXT_CHARS]):
                return kind
            continue
        if pattern.search(text):
            return kind
    return None


def _domain_label(domain: str) -> str:
    labels = [p for p in domain.lower().split(".") if p]
    if len(labels) >= 3 and labels[-2] in {"co", "com"} and len(labels[-1]) == 2:
        return labels[-3]  # acme.co.in -> acme
    return labels[-2] if len(labels) >= 2 else (labels[0] if labels else "")


def company_mentioned(company: str | None, message: MailMessage) -> bool:
    normalized = normalize_company(company)
    if not normalized:
        return False
    slug = normalized.replace(" ", "")
    if slug and _domain_label(message.sender_domain) == slug and not ATS_SENDERS.search(message.sender_domain):
        return True
    if len(normalized) < MIN_COMPANY_CHARS:
        return False
    haystack = " " + " ".join(_words(f"{message.subject} {message.sender} {(message.body or '')[:TEXT_CHARS]}")) + " "
    return f" {normalized} " in haystack


def title_overlap(title: str | None, message: MailMessage) -> float:
    wanted = {w for w in _words(title) if w not in STOPWORDS}
    if not wanted:
        return 0.0
    seen = set(_words(f"{message.subject} {(message.body or '')[:TEXT_CHARS]}"))
    return len(wanted & seen) / len(wanted)


def submitted_at(record: Any) -> datetime | None:
    return getattr(record, "applied_at", None) or getattr(record, "updated_at", None)


@dataclass(frozen=True)
class FunnelMatch:
    record: Any
    kind: str
    title_score: float


def match_application(message: MailMessage, kind: str, candidates: Sequence[Any]) -> FunnelMatch | None:
    """The single application this mail belongs to, or None (no company match / ambiguous / too early)."""
    hits: list[tuple[float, Any]] = []
    for record in candidates:
        if not company_mentioned(getattr(record, "company_name", None), message):
            continue
        sent = submitted_at(record)
        if message.received_at is not None and sent is not None and message.received_at < sent - ARRIVAL_SLACK:
            continue  # the mail predates this application: it belongs to an earlier one
        hits.append((title_overlap(getattr(record, "role_title", None), message), record))
    if not hits:
        return None
    hits.sort(key=lambda item: item[0], reverse=True)
    best_score, best = hits[0]
    if len(hits) > 1 and hits[1][0] >= best_score:
        return None  # two applications at the same company and nothing tells them apart
    return FunnelMatch(best, kind, best_score)


def processed_keys(events: Iterable[dict[str, Any]] | None) -> set[str]:
    """Message keys already applied to an application (from its timeline payloads)."""
    keys: set[str] = set()
    for event in events or ():
        payload = event.get("payload") if isinstance(event, dict) else None
        if isinstance(payload, dict) and isinstance(payload.get("message_key"), str):
            keys.add(payload["message_key"])
    return keys
