"""Pure builders for the application proof receipt (no I/O).

Everything is reduced to a whitelist exactly like `application_views`: answers keep question/answer/
source (+ cache similarity / entry id when the filler recorded them), the screenshot is its FILE NAME
only, and timing comes from the receipt's `timing` block with state-event fallbacks.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

from backend.app.api.v1.v2.routers.application_views import (
    MAX_ANSWERS,
    _timestamp,
    safe_text,
    safe_token,
)
from backend.app.browser_v2.schemas import ApplicationRead
from backend.app.browser_v2.schemas.proof import (
    ApplicationProof,
    ProofAnswer,
    ProofDraft,
    ProofMailEvent,
    ProofTiming,
)
from backend.app.browser_v2.store import ApplicationRecord

STALE_AFTER = timedelta(hours=24)
FACT_SOURCES = frozenset({"profile", "profile_identity", "deterministic", "deterministic_only", "owner_disclosure",
                          "profile_fact", "facts"})
HUMAN_SOURCES = frozenset({"human_hitl", "human", "hitl", "hitl_owner_answer", "owner"})
FIXED_LABELS = {"llm": "Tier 4 LLM", "resume_picker": "Resume", "composer": "Composer", "skip_optional": "Skipped"}


def _float(value: Any) -> float | None:
    try:
        return None if value is None or isinstance(value, bool) else round(float(value), 4)
    except (TypeError, ValueError):
        return None


def tier_label(source: str | None, similarity: float | None = None, match: str | None = None) -> str:
    if source in FACT_SOURCES:
        return "Tier 1 Fact"
    if source == "semantic_cache":
        if match == "exact" or (similarity is not None and similarity >= 0.999):
            return "Tier 2 Exact"
        return f"Tier 3 Semantic {similarity:.2f}" if similarity is not None else "Tier 3 Semantic"
    if source in HUMAN_SOURCES:
        return "HITL Human"
    return FIXED_LABELS.get(source or "", "Unknown")


def proof_answers(raw: Any) -> list[ProofAnswer]:
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for item in raw[:MAX_ANSWERS]:
        if not isinstance(item, Mapping):
            continue
        question, answer = safe_text(item.get("question")), safe_text(item.get("answer"))
        if question is None and answer is None:
            continue
        source = safe_token(item.get("source"))
        similarity = _float(item.get("similarity"))
        out.append(ProofAnswer(question=question or "Unlabelled field", answer=answer or "", source=source,
                               tier_label=tier_label(source, similarity, safe_token(item.get("cache_match"))),
                               similarity=similarity, cache_entry_id=safe_token(item.get("cache_entry_id"))))
    return out


def _first_event(events: list[dict[str, Any]], to_state: str) -> datetime | None:
    return next((_timestamp(e.get("created_at")) for e in events if e.get("to_state") == to_state
                 and e.get("from_state") != to_state), None)


def _apply_event(events: list[dict[str, Any]]) -> Mapping[str, Any]:
    return next((e["payload"] for e in reversed(events) if isinstance(e.get("payload"), Mapping)
                 and ("answers" in e["payload"] or "clicked_apply" in e["payload"])), None) or {}


def _int(value: Any) -> int | None:
    number = _float(value)
    return None if number is None else int(number)


def build_proof(record: ApplicationRecord, events: list[dict[str, Any]], *, now: datetime,
                mail_events: list[Any] | None = None, draft: Any = None) -> ApplicationProof:
    receipt: Mapping[str, Any] = record.receipt if isinstance(record.receipt, Mapping) else {}
    raw_timing = receipt.get("timing")
    timing_raw: Mapping[str, Any] = raw_timing if isinstance(raw_timing, Mapping) else {}
    timing = ProofTiming(
        posted_at=_timestamp(timing_raw.get("posted_at")) or record.posted_at,
        discovered_at=_timestamp(timing_raw.get("discovered_at")) or record.created_at,
        queued_at=_first_event(events, "SCORED") or record.created_at,
        started_at=_timestamp(timing_raw.get("started_at")) or _first_event(events, "APPLYING"),
        submitted_at=_timestamp(timing_raw.get("submitted_at")) or record.applied_at,
        first_mover_lag_seconds=_int(timing_raw.get("first_mover_lag_seconds")))
    apply_event = _apply_event(events)
    answers = proof_answers(receipt.get("answers")) or proof_answers(apply_event.get("answers"))
    resume = safe_text(receipt.get("resume_variant_used"), 120) or safe_text(receipt.get("resume_variant"), 120) \
        or safe_text(receipt.get("resume"), 120) \
        or next((a.answer for a in answers if a.source == "resume_picker"), None)
    shot = receipt.get("screenshot") or apply_event.get("screenshot")
    screenshot = PurePosixPath(str(shot).replace("\\", "/")).name[:200] if isinstance(shot, str) and shot else None
    mails = [ProofMailEvent(kind=str(m.kind), subject=safe_text(m.subject, 300), sender=safe_text(m.sender, 200),
                            received_at=m.received_at) for m in (mail_events or [])]
    outreach = ProofDraft(id=str(draft.id), status=str(draft.status), recipient_email=draft.recipient_email,
                          created_at=draft.created_at) if draft is not None else None
    stale = record.state.value == "SUBMISSION_UNKNOWN" and record.updated_at is not None \
        and record.updated_at < now - STALE_AFTER
    return ApplicationProof(
        application=ApplicationRead(**record.public()), timing=timing, answers=answers, resume_variant_used=resume,
        screenshot=screenshot, mail_events=mails, outreach_draft=outreach,
        email_verified=bool(receipt.get("email_verified")), confirmed_at=_timestamp(receipt.get("confirmed_at")),
        needs_reconciliation=stale)
