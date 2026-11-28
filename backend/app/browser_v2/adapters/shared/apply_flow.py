"""Confirmation / submit helpers and the hosted Greenhouse / Lever applier."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from backend.app.browser_v2.adapters.base import ApplyResult, HitlQuestion, JobDetail
from backend.app.browser_v2.adapters.shared.dom_scripts import FORM_STATE_JS
from backend.app.browser_v2.adapters.shared.external_handoff import (
    SUPPORTED_ATS,
    ats_form_url,
    ats_of_host,
    classify_ats,
)
from backend.app.browser_v2.adapters.shared.form_filler import HostedFormFiller
from backend.app.browser_v2.adapters.shared.security_code import (
    CodeProvider,
    code_question,
    needs_security_code,
    obtain_code,
    type_code,
)
from backend.app.browser_v2.adapters.shared.text import S
from backend.app.browser_v2.answers import CandidateFacts
from backend.app.browser_v2.receipts import capture
from backend.app.browser_v2.submit_marker import mark_submit_attempted

# --- confirmation + submit helpers ----------------------------------------------------------
CONFIRM_TEXT = (r"thank(?:s| you) for (?:your )?appl(?:ying|ication)|application (?:has been |was )?(?:submitted|received|sent)"
                r"|we(?:'ve| have) received your application|successfully (?:submitted|applied)|you(?:'ve| have) applied"
                r"|applied successfully|your application is on its way")
SUBMIT_TEXT = (r"^(?:submit(?: (?:your )?application)?|send(?: application)?|apply(?: now)?|"
               r"submit & apply|finish|complete(?: application)?|confirm(?: application)?)$")
NEXT_TEXT = r"^(?:next|continue|save (?:and|&) continue|proceed)$"

logger = logging.getLogger(__name__)


def off_ats_host(page: Any, ats: str) -> str | None:
    """The current host when the page left the vetted ATS host (redirect to a careers site etc.)."""
    current = str(getattr(page, "url", "") or "")
    if ats_of_host(current) == ats:
        return None
    return (urlsplit(current).hostname or "unknown")[:80]


async def form_state(page: Any, root: str | None, *, submit_re: str = SUBMIT_TEXT,
                     confirm_re: str = CONFIRM_TEXT) -> dict[str, Any]:
    return await page.evaluate(FORM_STATE_JS, {"root": root, "submitRe": submit_re, "confirmRe": confirm_re})


def button_locator(page: Any, root: str | None, pattern: str) -> Any:
    scope = page.locator(root) if root else page
    return scope.locator("button, input[type=submit], [role=button], a[role=button]").filter(
        has_text=re.compile(pattern, re.IGNORECASE))


async def visible_buttons(page: Any, root: str | None, pattern: str) -> Any:
    locator = button_locator(page, root, pattern)
    count = await locator.count()
    visible = []
    for index in range(min(count, 10)):
        item = locator.nth(index)
        try:
            if await item.is_visible() and await item.is_enabled():
                visible.append(item)
        except Exception:  # noqa: BLE001, S112
            continue
    if not visible:  # <input type=submit value="Submit application"> has no inner text
        scope = page.locator(root) if root else page
        inputs = scope.locator("input[type=submit]")
        for index in range(min(await inputs.count(), 5)):
            item = inputs.nth(index)
            value = (await item.get_attribute("value")) or ""
            if re.search(pattern, value.strip(), re.IGNORECASE) and await item.is_visible():
                visible.append(item)
    return visible


_IN_FORM_JS = "e => e.type === 'submit' || !!e.closest('form')"


async def form_submit_buttons(page: Any, root: str | None, pattern: str) -> Any:
    """Visible submit controls, narrowed to the form's own when the page adds look-alikes.

    Greenhouse job-boards render a page-level "Apply" button (it only scrolls to the
    form) next to the form's real "Submit application"; counting both made every
    hosted Greenhouse form fail with ats_submit_control_2.
    """
    buttons = await visible_buttons(page, root, pattern)
    if len(buttons) <= 1:
        return buttons
    narrowed = []
    for item in buttons:
        try:
            if await item.evaluate(_IN_FORM_JS):
                narrowed.append(item)
        except Exception:  # noqa: BLE001, S112 - a detached node is simply not a candidate
            continue
    return narrowed or buttons


async def poll_state(page: Any, root: str | None, done: Callable[[dict[str, Any]], bool], timeout_s: float,
                     **kwargs: Any) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_s
    state = await form_state(page, root, **kwargs)
    while not done(state) and loop.time() < deadline:
        await page.wait_for_timeout(250)
        state = await form_state(page, root, **kwargs)
    return state


CONFIRM_URL = re.compile(r"/(?:confirmation|thank[-_]?you|thanks|submitted|success|applied)\b", re.IGNORECASE)


def confirmation_source(state: dict[str, Any], start_url: str | None = None) -> str | None:
    if state.get("confirmed"):
        match = re.search(CONFIRM_TEXT, state.get("body") or "", re.IGNORECASE)
        return "confirmation_text:" + (match.group(0) if match else "match")
    url = str(state.get("url") or "")
    if url != (start_url or "") and CONFIRM_URL.search(urlsplit(url).path):
        return "confirmation_url"
    return None


class HostedAtsApplier:
    """Greenhouse / Lever hosted application forms (also used as an external-ATS delegate)."""

    def __init__(self, filler: HostedFormFiller | None = None, *, settle_ms: int = 1500,
                 confirm_timeout_s: float = 15.0, receipts_root: Path | None = None) -> None:
        self.filler = filler or HostedFormFiller()
        self.settle_ms = settle_ms
        self.confirm_timeout_s = confirm_timeout_s
        self.receipts_root = receipts_root
        self.security_code_provider: CodeProvider | None = None  # read-only mail lookup (Greenhouse codes)
        self.supported: frozenset[str] = SUPPORTED_ATS  # the Ashby adapter widens this for its own forms

    async def shot(self, page: Any, platform: str, job_id: str, label: str) -> str | None:
        return await capture(page, platform, job_id, label, root=self.receipts_root)

    async def open_form(self, page: Any, url: str, ats: str) -> None:
        await page.goto(ats_form_url(url, ats), wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(self.settle_ms)

    async def apply(self, page: Any, detail: JobDetail, facts: CandidateFacts, *, platform: str, dry_run: bool,
                    hitl_answers: dict[str, str] | None = None, navigate: bool = True) -> ApplyResult:
        ats = detail.ats or classify_ats(detail.apply_url)
        url = detail.apply_url or detail.listing.url
        job_id = detail.listing.external_job_id
        if ats not in self.supported:
            return ApplyResult(S.FILTERED_OUT, f"external_unsupported_ats:{urlsplit(url).hostname or 'unknown'}",
                               dry_run)
        try:
            prepared = await self._prepare(page, detail, facts, ats=ats, url=url, platform=platform,
                                           dry_run=dry_run, hitl_answers=hitl_answers, navigate=navigate)
        except Exception as exc:  # nothing was submitted: retryable FAILED, never a never-replay fence
            logger.warning("hosted form error before submit (%s)", type(exc).__name__, exc_info=True)
            return ApplyResult(S.FAILED, f"ats_form_error_before_submit:{type(exc).__name__}", dry_run,
                               clicked_apply=False)
        if isinstance(prepared, ApplyResult):
            return prepared
        outcome, submits, answers = prepared
        planned = (f"submit {ats} application for {job_id} ({detail.listing.title} @ {detail.listing.company})"
                   + (f"; upload {', '.join(outcome.planned_uploads)}" if outcome.planned_uploads else ""))
        if dry_run:
            shot = await self.shot(page, platform, job_id, "dry-run")
            return ApplyResult(S.SCORED, "dry_run_stopped_before_submit", True, planned_action=planned,
                               screenshot=shot, answers=answers)
        redirected = off_ats_host(page, ats)
        if redirected is not None:  # the page moved while filling: never click submit elsewhere
            return ApplyResult(S.FAILED, f"ats_redirected_before_submit:{redirected}", False, answers=answers)
        start_url = str(page.url)
        await self.filler.pacing.before_submit()  # Human Pulse: a short "review" pause before Submit
        mark_submit_attempted(f"{ats}_submit")
        submitted_at = datetime.now(UTC)
        await submits[0].click()
        return await self._after_submit(page, outcome, answers, ats=ats, url=url, platform=platform, job_id=job_id,
                                        start_url=start_url, company=detail.listing.company,
                                        submitted_at=submitted_at, hitl_answers=hitl_answers)

    async def quarantine_rejected(self, answers: tuple[dict[str, str], ...], errors: list[str]) -> int:
        """A portal rejected values we filled: quarantine the semantic-cache entries behind the fields
        the error messages name, so a bad cached answer never poisons another application."""
        cache = getattr(getattr(self.filler, "answerer", None), "cache", None)
        record = getattr(cache, "record_form_validation_error", None)
        if record is None:
            return 0
        text = " ".join(str(e) for e in errors).casefold()
        quarantined = 0
        for answer in answers:
            entry_id, label = answer.get("cache_entry_id"), str(answer.get("question") or "").casefold()
            words = [w for w in re.findall(r"[a-z]{4,}", label)][:6]
            if not entry_id or not words or not (label in text or sum(w in text for w in words) >= 2):
                continue
            try:
                await record(entry_id)
                quarantined += 1
            except Exception as exc:  # noqa: BLE001 - quarantine is best effort; the HITL still opens
                logger.info("cache quarantine of %s failed: %s", entry_id, type(exc).__name__)
        return quarantined

    async def _prepare(self, page: Any, detail: JobDetail, facts: CandidateFacts, *, ats: str, url: str,
                       platform: str, dry_run: bool, hitl_answers: dict[str, str] | None,
                       navigate: bool) -> ApplyResult | tuple[Any, list[Any], tuple[dict[str, str], ...]]:
        """Open + fill the hosted form up to (never including) the submit click."""
        job_id = detail.listing.external_job_id
        if navigate:
            await self.open_form(page, url, ats)
        redirected = off_ats_host(page, ats)
        if redirected is not None:  # never type PII / upload the resume on a host we did not vet
            return ApplyResult(S.FILTERED_OUT, f"ats_redirected:{redirected}", dry_run)
        state = await form_state(page, None)
        if state.get("challenge"):
            return ApplyResult(S.WAITING_FOR_USER, "ats_captcha_before_submit", dry_run,
                               question=HitlQuestion(kind="CAPTCHA", prompt=f"{ats.title()} form needs a CAPTCHA: "
                                                     f"{url}", context={"url": url, "platform": platform}))
        if re.search(r"no longer (?:open|accepting|available)|job (?:is )?closed|position has been filled|"
                     r"couldn'?t find (?:that|this) job|page (?:you'?re looking for )?(?:was )?not found",
                     state.get("body") or "", re.IGNORECASE):
            return ApplyResult(S.FILTERED_OUT, "ats_posting_closed", dry_run)
        outcome = await self.filler.fill(page, detail, facts, hitl_answers=hitl_answers, dry_run=dry_run,
                                         platform=platform)
        answers = tuple(outcome.filled)
        if outcome.question is not None:
            return ApplyResult(S.WAITING_FOR_USER, "question_requires_owner", dry_run, question=outcome.question,
                               answers=answers, screenshot=await self.shot(page, platform, job_id, "question"))
        readback = await self.filler.verify(page, outcome, detail=detail, platform=platform, dry_run=dry_run)
        if readback is not None:  # a required value reverted / the resume never attached: never submit
            return ApplyResult(S.WAITING_FOR_USER, str(readback.context.get("resolver_reason")), dry_run,
                               question=readback, answers=answers,
                               screenshot=await self.shot(page, platform, job_id, "readback"))
        submits = await form_submit_buttons(page, None, SUBMIT_TEXT)
        if len(submits) != 1:
            return ApplyResult(S.FAILED, f"ats_submit_control_{len(submits)}", dry_run, answers=answers)
        return outcome, submits, answers

    async def _after_submit(self, page: Any, outcome: Any, answers: tuple[dict[str, str], ...], *, ats: str,
                            url: str, platform: str, job_id: str, start_url: str, company: str | None = None,
                            submitted_at: datetime | None = None, hitl_answers: dict[str, str] | None = None,
                            code_source: str | None = None) -> ApplyResult:
        state = await poll_state(page, None, lambda st: bool(
            confirmation_source(st, start_url) or st.get("errors") or st.get("challenge")
            or (code_source is None and needs_security_code(st))), self.confirm_timeout_s)
        source = confirmation_source(state, start_url)
        if source is None and code_source is None and ats == "greenhouse" and needs_security_code(state):
            return await self._security_code_step(page, outcome, answers, ats=ats, url=url, platform=platform,
                                                  job_id=job_id, start_url=start_url, company=company,
                                                  submitted_at=submitted_at or datetime.now(UTC),
                                                  hitl_answers=hitl_answers)
        shot = await self.shot(page, platform, job_id, "receipt" if source else "after-submit")
        if source is not None:
            receipt = {"source": source, "url": state.get("url"), "ats": ats, "screenshot": shot,
                       "verified_at": datetime.now(UTC).isoformat(), "answers": list(answers),
                       "resume": outcome.resume, "resume_variant_used": outcome.resume}
            if code_source is not None:
                receipt["security_code"] = code_source  # how it was obtained; the code itself is never kept
                receipt["url"] = urlsplit(str(state.get("url") or url))._replace(query="", fragment="").geturl()
            return ApplyResult(S.APPLIED, "confirmed", False, clicked_apply=True, receipt=receipt, screenshot=shot,
                               answers=answers)
        if state.get("errors") and state.get("submits") == 1 and not state.get("challenge"):
            # The form rejected the submission (still on the form with validation errors).
            await self.quarantine_rejected(answers, state.get("errors") or [])
            return ApplyResult(S.WAITING_FOR_USER, "ats_validation_errors", False, clicked_apply=True,
                               answers=answers, screenshot=shot,
                               question=HitlQuestion(kind="ERROR", prompt="Form rejected: " + "; ".join(
                                   state.get("errors") or [])[:300], context={"url": url, "platform": platform}))
        return ApplyResult(S.SUBMISSION_UNKNOWN, "confirmation_ambiguous", False, clicked_apply=True,
                           answers=answers, screenshot=shot)

    async def _security_code_step(self, page: Any, outcome: Any, answers: tuple[dict[str, str], ...], *, ats: str,
                                  url: str, platform: str, job_id: str, start_url: str, company: str | None,
                                  submitted_at: datetime, hitl_answers: dict[str, str] | None) -> ApplyResult:
        """Greenhouse held the application for an emailed security code: email -> owner -> P0 HITL."""
        code, source = await obtain_code(self.security_code_provider, company, submitted_at, hitl_answers)
        if code is None or not await type_code(page, code):
            reason = source if code is None else "security_code_input_not_found"
            shot = await self.shot(page, platform, job_id, "security-code")
            return ApplyResult(S.WAITING_FOR_USER, reason, False, clicked_apply=True, answers=answers,
                               screenshot=shot, question=code_question(company, url, platform, reason))
        submits = await form_submit_buttons(page, None, SUBMIT_TEXT)
        if len(submits) != 1:
            return ApplyResult(S.SUBMISSION_UNKNOWN, f"security_code_submit_control_{len(submits)}", False,
                               clicked_apply=True, answers=answers)
        await submits[0].click()  # Submit #2 (already marked as a submit attempt)
        return await self._after_submit(page, outcome, answers, ats=ats, url=url, platform=platform, job_id=job_id,
                                        start_url=start_url, company=company, submitted_at=submitted_at,
                                        hitl_answers=hitl_answers, code_source=source)
