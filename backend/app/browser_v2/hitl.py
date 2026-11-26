"""Shared human-in-the-loop resolution (Phase 4).

Telegram (buttons, swipe-replies, slash commands), the dashboard HITL inbox and
FastMCP all call this one service, so an answer behaves identically everywhere:

- QUESTION answers are validated against the form options (index, exact text or
  case-insensitive match); an invalid choice leaves the request OPEN.
- A verified QUESTION answer is learned into the semantic cache as source='user'
  (outranks profile/LLM answers) unless the owner chose "answer once", the
  question is sensitive, or the request is CAPTCHA/OTP.
- The linked application moves WAITING_FOR_USER -> SCORED with retry_after=now()
  so the worker re-runs it before new discoveries. APPLIED and
  SUBMISSION_UNKNOWN are never re-enqueued.
- Skip cancels the request and moves the job to FILTERED_OUT.
- Resume resets portal auth to UNKNOWN so the next tick re-checks the session.
- Phase 8: stale requests expire (OTP 30 min, CAPTCHA 24 h, QUESTION/ERROR 7 days) so
  nothing leaks forever; the linked WAITING_FOR_USER job becomes FILTERED_OUT
  (`hitl_expired`, never replayed). AUTH requests never expire: they close when the
  portal session is OK again or the owner sends /resume.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from backend.app.browser_v2.answers import BLOCKED, SENSITIVE, match_multi, match_option
from backend.app.browser_v2.state import (
    NEVER_REPLAY,
    TRANSITIONS,
    ApplicationState,
    InvalidTransition,
)
from backend.app.browser_v2.store import HitlRecord, Store

if TYPE_CHECKING:
    from backend.app.ai_v2.semantic_cache import SemanticCache

logger = logging.getLogger(__name__)
S = ApplicationState

MAX_ANSWER_CHARS = 1000
ANSWERABLE_KINDS = frozenset({"QUESTION", "OTP", "CAPTCHA"})
REQUEUE_FROM = frozenset({S.WAITING_FOR_USER, S.FAILED})
REQUEUE_REASON = "hitl_resolved_requeued"
SKIP_REASON = "skipped_by_owner_hitl"
EXPIRED_REASON = "hitl_expired"
HITL_TTL: dict[str, timedelta] = {"OTP": timedelta(minutes=30), "CAPTCHA": timedelta(hours=24),
                                  "QUESTION": timedelta(days=7), "ERROR": timedelta(days=7)}


def cacheable_question(question: str) -> bool:
    """Never learn answers to blocked (email/login/OTP/consent) or sensitive questions."""
    return bool((question or "").strip()) and not BLOCKED.search(question) and not SENSITIVE.search(question)


@dataclass
class Resolution:
    ok: bool
    code: str  # answered | skipped | retried | not_found | ambiguous_ref | already_resolved |
    #            invalid_option | empty_answer | answer_too_long | wrong_kind
    message: str
    hitl: HitlRecord | None = None
    answer: str | None = None
    cached: bool = False
    requeued: bool = False
    application_state: str | None = None
    options: tuple[str, ...] = ()

    def public(self) -> dict[str, Any]:
        return {"ok": self.ok, "code": self.code, "message": self.message, "answer": self.answer,
                "cached": self.cached, "requeued": self.requeued,
                "application_state": self.application_state, "options": list(self.options),
                "hitl": self.hitl.public() if self.hitl else None}


@dataclass
class PortalResume:
    ok: bool
    platform: str
    message: str
    auth_status: str | None = None
    resolved: list[HitlRecord] = field(default_factory=list)

    def public(self) -> dict[str, Any]:
        return {"ok": self.ok, "platform": self.platform, "message": self.message,
                "auth_status": self.auth_status, "resolved_auth_requests": len(self.resolved)}


def _label(hitl: HitlRecord) -> str:
    parts = [p for p in (hitl.company, hitl.title) if p]
    return " · ".join(parts) if parts else hitl.platform


class HITLResolutionService:
    def __init__(self, store: Store, cache: SemanticCache | None = None, *,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.store = store
        self.cache = cache
        self.clock = clock or (lambda: datetime.now(UTC))

    # --- lookup -------------------------------------------------------------------
    async def by_ref(self, ref: str) -> tuple[HitlRecord | None, Resolution | None]:
        """Resolve a short ref (>= 4 hex chars) to exactly one OPEN request."""
        matches = await self.store.find_open_hitl_by_ref(ref)
        if not matches:
            return None, Resolution(False, "not_found", f"No open request with ref {ref!s:.12}. Send /pending.")
        if len(matches) > 1:
            return None, Resolution(False, "ambiguous_ref",
                                    f"Ref {ref} matches {len(matches)} requests; use more characters.")
        return matches[0], None

    async def _open(self, hitl_id: str) -> tuple[HitlRecord | None, Resolution | None]:
        hitl = await self.store.get_hitl(hitl_id)
        if hitl is None:
            return None, Resolution(False, "not_found", "That request no longer exists.")
        if hitl.status != "OPEN":
            return None, Resolution(False, "already_resolved",
                                    f"Already {hitl.status.lower()} ({hitl.ref}); nothing changed.", hitl=hitl)
        return hitl, None

    # --- actions ------------------------------------------------------------------
    async def answer(self, hitl_id: str, answer: str, *, cache_answer: bool = True,
                     via: str = "dashboard") -> Resolution:
        hitl, problem = await self._open(hitl_id)
        if problem is not None:
            return problem
        assert hitl is not None
        if hitl.kind == "AUTH":
            return Resolution(False, "wrong_kind", f"Log in with login-setup, then send /resume {hitl.platform}.",
                              hitl=hitl)
        if hitl.kind not in ANSWERABLE_KINDS:
            return Resolution(False, "wrong_kind", f"Use /retry {hitl.ref} or /skip {hitl.ref}.", hitl=hitl)
        text = (answer or "").strip()
        if not text:
            return Resolution(False, "empty_answer", "Send a non-empty answer.", hitl=hitl)
        if len(text) > MAX_ANSWER_CHARS:
            return Resolution(False, "answer_too_long", f"Answers are limited to {MAX_ANSWER_CHARS} characters.",
                              hitl=hitl)
        options = hitl.options if hitl.kind == "QUESTION" else ()
        if options:
            mapped = match_option(text, options)
            if mapped is None and hitl.context.get("input_kind") == "multi":
                mapped = match_multi(text, options)  # Naukri multi-select checkboxes
            if mapped is None:
                listed = "\n".join(f"{i}. {o}" for i, o in enumerate(options, 1))
                return Resolution(False, "invalid_option",
                                  f"That is not one of the options. Reply with a number or the exact text:\n{listed}",
                                  hitl=hitl, options=options)
            text = mapped
        learn = hitl.kind == "QUESTION" and cache_answer and cacheable_question(hitl.prompt_text)
        closed = await self.store.close_hitl(hitl.id, "ANSWERED", text, via)
        if closed is None:  # raced with another channel / double click
            return Resolution(False, "already_resolved", f"Already resolved ({hitl.ref}); nothing changed.",
                              hitl=await self.store.get_hitl(hitl.id))
        cached = False
        if learn and self.cache is not None:
            try:
                await self.cache.store_verified_user_answer(hitl.prompt_text, text)
                cached = True
            except Exception as exc:  # noqa: BLE001 - the answer still re-enqueues the job
                logger.warning("hitl cache_store_failed ref=%s error=%s", hitl.ref, type(exc).__name__)
        shown = text if hitl.kind == "QUESTION" and cacheable_question(hitl.prompt_text) else "[redacted]"
        requeued, state = await self._requeue(closed, {"hitl_id": closed.id, "kind": closed.kind, "via": via,
                                                       "question": closed.prompt_text[:300], "answer": shown,
                                                       "cached": cached})
        note = " Saved to semantic cache." if cached else " Not cached (one-time)." if hitl.kind == "QUESTION" \
            else ""
        tail = " Job re-queued with priority." if requeued else self._not_requeued(state)
        return Resolution(True, "answered", f"Answered {closed.ref} ({_label(closed)}).{note}{tail}",
                          hitl=await self.store.get_hitl(closed.id) or closed, answer=text, cached=cached,
                          requeued=requeued, application_state=state)

    async def answer_option(self, hitl_id: str, index: int, *, via: str = "telegram") -> Resolution:
        hitl, problem = await self._open(hitl_id)
        if problem is not None:
            return problem
        assert hitl is not None
        if not 0 <= index < len(hitl.options):
            return Resolution(False, "invalid_option", "That option is no longer valid.", hitl=hitl,
                              options=hitl.options)
        return await self.answer(hitl.id, hitl.options[index], cache_answer=True, via=via)

    async def retry(self, hitl_id: str, *, via: str = "dashboard") -> Resolution:
        """ERROR/CAPTCHA (or any non-AUTH request): close it and re-run the job with priority."""
        hitl, problem = await self._open(hitl_id)
        if problem is not None:
            return problem
        assert hitl is not None
        if hitl.kind == "AUTH":
            return Resolution(False, "wrong_kind", f"Send /resume {hitl.platform} after login-setup.", hitl=hitl)
        closed = await self.store.close_hitl(hitl.id, "ANSWERED", None, via)
        if closed is None:
            return Resolution(False, "already_resolved", f"Already resolved ({hitl.ref}).", hitl=hitl)
        requeued, state = await self._requeue(closed, {"hitl_id": closed.id, "kind": closed.kind, "via": via,
                                                       "action": "retry"})
        tail = " Job re-queued with priority." if requeued else self._not_requeued(state)
        return Resolution(True, "retried", f"Retrying {closed.ref} ({_label(closed)}).{tail}",
                          hitl=await self.store.get_hitl(closed.id) or closed, requeued=requeued,
                          application_state=state)

    async def skip(self, hitl_id: str, *, via: str = "dashboard") -> Resolution:
        hitl, problem = await self._open(hitl_id)
        if problem is not None:
            return problem
        assert hitl is not None
        closed = await self.store.close_hitl(hitl.id, "CANCELLED", None, via)
        if closed is None:
            return Resolution(False, "already_resolved", f"Already resolved ({hitl.ref}).", hitl=hitl)
        state = None
        record = await self.store.get_application(closed.application_id) if closed.application_id else None
        if record is not None:
            state = record.state.value
            if record.state not in NEVER_REPLAY and S.FILTERED_OUT in TRANSITIONS[record.state]:
                try:
                    record = await self.store.transition(record, S.FILTERED_OUT, SKIP_REASON,
                                                         payload={"hitl_id": closed.id, "via": via})
                    state = record.state.value
                except InvalidTransition:
                    logger.warning("hitl skip transition raced ref=%s", closed.ref)
        return Resolution(True, "skipped", f"Skipped {closed.ref} ({_label(closed)}).",
                          hitl=await self.store.get_hitl(closed.id) or closed, application_state=state)

    async def resume_portal(self, platform: str, *, via: str = "dashboard") -> PortalResume:
        platform = (platform or "").strip().lower()
        known = {rules.platform for rules in await self.store.list_rules()}
        if platform not in known:
            return PortalResume(False, platform, f"Unknown portal '{platform[:40]}'. Known: {', '.join(sorted(known))}.")
        resolved: list[HitlRecord] = []
        open_rows, _ = await self.store.list_hitl("OPEN", platform, limit=50)
        for row in open_rows:
            if row.kind == "AUTH":
                closed = await self.store.close_hitl(row.id, "ANSWERED", "owner_resumed", via)
                if closed is not None:
                    resolved.append(closed)
        # UNKNOWN (not OK): the worker re-runs check_session() on its next tick.
        await self.store.record_auth(platform, "UNKNOWN")
        return PortalResume(True, platform, f"{platform} resumed: the worker re-checks the session on its next tick.",
                            auth_status="UNKNOWN", resolved=resolved)

    async def expire_stale(self, now: datetime | None = None,
                           ttl: dict[str, timedelta] | None = None) -> list[HitlRecord]:
        """Expire OPEN requests past their TTL; their jobs leave WAITING_FOR_USER (never replayed)."""
        now = now or self.clock()
        expired: list[HitlRecord] = []
        for kind, age in (ttl or HITL_TTL).items():
            expired.extend(await self.store.expire_stale_hitl(kind, now - age))
        for hitl in expired:
            if not hitl.application_id:
                continue
            record = await self.store.get_application(hitl.application_id)
            if record is None or record.state is not S.WAITING_FOR_USER:
                continue
            try:
                await self.store.transition(record, S.FILTERED_OUT, EXPIRED_REASON,
                                            payload={"hitl_id": hitl.id, "kind": hitl.kind})
            except InvalidTransition:
                logger.info("hitl expiry transition raced ref=%s", hitl.ref)
        if expired:
            logger.info("hitl expired %d stale request(s)", len(expired))
        return expired

    # --- helpers ------------------------------------------------------------------
    async def _requeue(self, hitl: HitlRecord, payload: dict[str, Any]) -> tuple[bool, str | None]:
        if not hitl.application_id:
            return False, None
        record = await self.store.get_application(hitl.application_id)
        if record is None:
            return False, None
        if record.state in NEVER_REPLAY or record.state not in REQUEUE_FROM:
            return False, record.state.value  # never re-enqueue a possibly-submitted application
        try:
            moved = await self.store.transition(record, S.SCORED, REQUEUE_REASON, payload=payload,
                                                retry_after=self.clock())
        except InvalidTransition:
            current = await self.store.get_application(hitl.application_id)
            return False, current.state.value if current else None
        return True, moved.state.value

    @staticmethod
    def _not_requeued(state: str | None) -> str:
        if state in {s.value for s in NEVER_REPLAY}:
            return f" Job is {state}; never re-applied."
        return f" Job state {state} unchanged." if state else ""
