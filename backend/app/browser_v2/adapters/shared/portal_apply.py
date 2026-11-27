"""Apply-click + modal handling + confirmation mixin of `InteractivePortalAdapter`."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from backend.app.browser_v2.adapters.base import ApplyResult, HitlQuestion, JobDetail
from backend.app.browser_v2.adapters.shared.apply_flow import (
    NEXT_TEXT,
    SUBMIT_TEXT,
    confirmation_source,
    form_state,
    poll_state,
    visible_buttons,
)
from backend.app.browser_v2.adapters.shared.discovery import PortalDiscoveryMixin
from backend.app.browser_v2.adapters.shared.dom_scripts import DETAIL_JS, DIALOG_JS
from backend.app.browser_v2.adapters.shared.text import MAX_FORM_STEPS, S
from backend.app.browser_v2.answers import CandidateFacts
from backend.app.browser_v2.receipts import capture
from backend.app.browser_v2.state import ApplicationState, guard_apply

logger = logging.getLogger(__name__)
EXTERNAL_LINK_JS = r"""
(pattern) => {
  const re = new RegExp(pattern, "i");
  const link = [...document.querySelectorAll("a[href]")].find(a => re.test((a.innerText || "").trim()));
  return link ? link.href : null;
}
"""
EXTERNAL_LINK_TEXT = r"^apply on (?:the )?(?:company(?:'s)? )?(?:website|site)$"


@dataclass
class Attempt:
    """What a live apply has done so far: a submit control clicked means it may have been sent."""

    submit_clicked: bool = False


class PortalApplyMixin(PortalDiscoveryMixin):
    """apply_job: Apply click, modal/form steps, submit and receipt verification."""

    # --- apply ----------------------------------------------------------------------------
    async def shot(self, page: Any, job_id: str, label: str) -> str | None:
        return await capture(page, self.platform, job_id, label, root=self.receipts_root)

    def _result(self, state: ApplicationState, reason: str, dry_run: bool, **extra: Any) -> ApplyResult:
        return ApplyResult(state=state, reason=reason, dry_run=dry_run, **extra)

    async def _dialog(self, page: Any) -> str | None:
        return await page.evaluate(DIALOG_JS, list(self.config.dialog_selectors))

    async def _confirmed(self, page: Any, root: str | None, start_url: str) -> tuple[str | None, dict[str, Any]]:
        state = await poll_state(page, root, lambda st: bool(
            confirmation_source(st, start_url) or st.get("errors") or st.get("challenge")
            or re.search(self.config.limit_text, st.get("body") or "", re.IGNORECASE)),
            self.confirm_timeout_s, confirm_re=self.config.confirm_text)
        return confirmation_source(state, start_url), state

    async def _wait_after_click(self, page: Any, start_url: str) -> None:
        """Apply clicked: wait for a confirmation, a modal/form, a limit or a challenge."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.confirm_timeout_s
        while loop.time() < deadline:
            state = await form_state(page, None, confirm_re=self.config.confirm_text)
            if confirmation_source(state, start_url) or state.get("challenge") or state.get("submits") \
                    or re.search(self.config.limit_text, state.get("body") or "", re.IGNORECASE) \
                    or await self._dialog(page):
                return
            await page.wait_for_timeout(250)

    async def _applied_badge(self, page: Any, detail: JobDetail) -> bool:
        await self._goto(page, detail.listing.url)
        data = await page.evaluate(DETAIL_JS, self._detail_args())
        return bool(data.get("applied"))

    def _may_have_sent(self, attempt: Attempt) -> bool:
        return attempt.submit_clicked or not self.config.apply_opens_form

    async def _external_link(self, page: Any) -> str | None:
        try:
            link = await page.evaluate(EXTERNAL_LINK_JS, EXTERNAL_LINK_TEXT)
        except Exception:  # noqa: BLE001 - the link is a bonus (ATS handoff); its absence is fine
            return None
        return link if isinstance(link, str) and link.startswith("http") else None

    async def apply_job(self, page: Any, detail: JobDetail, profile: CandidateFacts | Any, *,
                        dry_run: bool = True, existing_state: str | None = None,
                        hitl_answers: dict[str, str] | None = None) -> ApplyResult:
        guard_apply(existing_state)
        facts = profile if isinstance(profile, CandidateFacts) else CandidateFacts.from_profile(profile)
        attempt = Attempt()
        try:
            return await self._apply(page, detail, facts, dry_run=dry_run, hitl_answers=hitl_answers,
                                     attempt=attempt)
        except Exception as exc:
            if self._may_have_sent(attempt):
                raise  # the service records SUBMISSION_UNKNOWN (never replayed)
            # Apply only opened the form and nothing was submitted: retryable, never a fence.
            logger.warning("%s apply error before submit (%s)", self.platform, type(exc).__name__, exc_info=True)
            try:
                shot = await self.shot(page, detail.listing.external_job_id, "error-before-submit")
            except Exception:  # noqa: BLE001
                shot = None
            return self._result(S.FAILED, f"apply_error_before_submit:{type(exc).__name__}", dry_run,
                                screenshot=shot)

    async def _apply(self, page: Any, detail: JobDetail, facts: CandidateFacts, *, dry_run: bool,
                     hitl_answers: dict[str, str] | None, attempt: Attempt) -> ApplyResult:
        job_id, name = detail.listing.external_job_id, self.config.label
        if detail.challenge:
            kind = {"challenge": "CAPTCHA", "otp": "OTP", "login": "AUTH"}[detail.challenge]
            return self._result(S.WAITING_FOR_USER, "portal_" + detail.challenge, dry_run,
                                question=HitlQuestion(kind=kind, prompt=f"{name} needs {kind} on {detail.listing.url}",
                                                      context={"platform": self.platform}))
        if detail.portal_limit:
            return self._result(S.QUOTA_HIT_PENDING, "portal_daily_limit", dry_run,
                                receipt={"limit_text": detail.portal_limit})
        if detail.already_applied:
            return self._result(S.APPLIED, "already_applied_on_portal", dry_run,
                                receipt={"source": "applied_badge_before_action", "url": detail.listing.url,
                                         "verified_at": datetime.now(UTC).isoformat()})
        if detail.apply_mode == "external":
            return self._result(S.FILTERED_OUT, "external_company_site", dry_run)
        if detail.apply_mode == "closed":
            return self._result(S.FILTERED_OUT, "job_closed", dry_run)
        if detail.apply_mode != "direct":
            return self._result(S.FAILED, f"apply_control_{detail.apply_mode}", dry_run,
                                screenshot=await self.shot(page, job_id, f"apply-{detail.apply_mode}"))
        control = await self.resolve_apply_control(page)
        if control.get("applied"):
            return self._result(S.APPLIED, "already_applied_on_portal", dry_run,
                                receipt={"source": "applied_badge_before_action", "url": detail.listing.url,
                                         "verified_at": datetime.now(UTC).isoformat()})
        marked = page.locator('[data-aa-apply="1"]')
        buttons = [marked.first] if control.get("count") == 1 and await marked.count() == 1 else []
        if len(buttons) != 1:
            return self._result(S.FAILED, "apply_control_changed", dry_run,
                                screenshot=await self.shot(page, job_id, "apply-control"))
        planned = f"click {name} Apply for {job_id} ({detail.listing.title} @ {detail.listing.company})"
        if dry_run and self.config.apply_click_may_submit:
            return self._result(S.SCORED, "dry_run_stopped_before_apply_click", True, planned_action=planned,
                                screenshot=await self.shot(page, job_id, "dry-run"))
        await self._pause()
        pages_before = len(page.context.pages)
        start_url = str(page.url)
        await buttons[0].click()
        await page.wait_for_timeout(self.settle_ms)
        clicked = not dry_run or self.config.apply_click_may_submit
        if len(page.context.pages) > pages_before or \
                (urlsplit(str(page.url)).hostname or "") not in self.config.hosts:
            return self._result(S.FILTERED_OUT, "external_company_site_after_click", dry_run, clicked_apply=clicked)
        await self._wait_after_click(page, start_url)
        answers: list[dict[str, str]] = []
        for _ in range(MAX_FORM_STEPS):
            root = await self._dialog(page)
            state = await form_state(page, root, confirm_re=self.config.confirm_text)
            if re.search(self.config.limit_text, state.get("body") or "", re.IGNORECASE):
                return self._result(S.QUOTA_HIT_PENDING, "portal_daily_limit_after_click", dry_run,
                                    clicked_apply=clicked, answers=tuple(answers))
            if self.config.external_modal_text and not attempt.submit_clicked and re.search(
                    self.config.external_modal_text, state.get("body") or "", re.IGNORECASE):
                link = await self._external_link(page)
                return self._result(S.FILTERED_OUT, "external_company_site_after_click", dry_run,
                                    clicked_apply=clicked, receipt={"external_url": link} if link else None)
            if self.config.ineligible_modal_text and not attempt.submit_clicked and re.search(
                    self.config.ineligible_modal_text, state.get("body") or "", re.IGNORECASE):
                return self._result(S.FILTERED_OUT, "portal_says_location_not_supported", dry_run,
                                    clicked_apply=clicked, screenshot=await self.shot(page, job_id, "ineligible"))
            source = confirmation_source(state, start_url)
            if source is not None and clicked:
                return await self._receipt(page, detail, source, tuple(answers))
            if state.get("challenge"):
                sent = clicked and self._may_have_sent(attempt)
                return self._result(S.SUBMISSION_UNKNOWN if sent else S.WAITING_FOR_USER,
                                    "challenge_after_apply_click", dry_run, clicked_apply=clicked,
                                    question=None if sent else HitlQuestion(kind="CAPTCHA", prompt=f"{name} CAPTCHA"),
                                    screenshot=await self.shot(page, job_id, "challenge"))
            if root is None and not self.config.form_page_after_apply:
                break  # no modal: never scan/fill arbitrary page inputs (search bars, filters)
            fill = await self.filler.fill(page, detail, facts, root=root, hitl_answers=hitl_answers,
                                          dry_run=dry_run, platform=self.platform)
            answers.extend(fill.filled)
            if fill.question is not None:
                return self._result(S.WAITING_FOR_USER, "question_requires_owner", dry_run, clicked_apply=clicked,
                                    answers=tuple(answers), question=fill.question,
                                    screenshot=await self.shot(page, job_id, "question"))
            submit = await visible_buttons(page, root, SUBMIT_TEXT)
            if len(submit) == 1:
                if dry_run:
                    return self._result(S.SCORED, "dry_run_stopped_before_submit", True, planned_action=planned,
                                        answers=tuple(answers), screenshot=await self.shot(page, job_id, "dry-run"))
                await self._pause()
                attempt.submit_clicked = True
                await submit[0].click()
                source, state = await self._confirmed(page, root, start_url)
                if source is not None:
                    return await self._receipt(page, detail, source, tuple(answers))
                if re.search(self.config.limit_text, state.get("body") or "", re.IGNORECASE):
                    return self._result(S.QUOTA_HIT_PENDING, "portal_daily_limit_after_click", False,
                                        clicked_apply=True, answers=tuple(answers))
                break
            following = await visible_buttons(page, root, NEXT_TEXT)
            if len(following) == 1:
                await self._pause()
                attempt.submit_clicked = True  # conservative: a last "Continue" may be the submit
                await following[0].click()
                await page.wait_for_timeout(self.settle_ms)
                continue
            if not fill.filled:
                break
        else:
            return self._result(S.SUBMISSION_UNKNOWN, "form_step_limit", dry_run, clicked_apply=clicked,
                                answers=tuple(answers))
        if dry_run and not self.config.apply_click_may_submit:
            return self._result(S.FAILED, "dry_run_form_not_found", True, answers=tuple(answers))
        if await self._applied_badge(page, detail):
            return await self._receipt(page, detail, "applied_badge_after_reload", tuple(answers))
        if not self._may_have_sent(attempt):
            # Live 2026-11-27 Wellfound: Apply opened no usable form and nothing was submitted.
            return self._result(S.FAILED, "apply_form_not_submitted", False, clicked_apply=True,
                                answers=tuple(answers), screenshot=await self.shot(page, job_id, "no-form"))
        return self._result(S.SUBMISSION_UNKNOWN, "confirmation_ambiguous", False, clicked_apply=True,
                            answers=tuple(answers), screenshot=await self.shot(page, job_id, "ambiguous"))

    async def _receipt(self, page: Any, detail: JobDetail, source: str, answers: tuple[dict[str, str], ...]
                       ) -> ApplyResult:
        shot = await self.shot(page, detail.listing.external_job_id, "receipt")
        receipt = {"source": source, "url": detail.listing.url, "screenshot": shot,
                   "verified_at": datetime.now(UTC).isoformat(), "answers": list(answers)}
        return self._result(S.APPLIED, "confirmed", False, clicked_apply=True, receipt=receipt, screenshot=shot,
                            answers=answers)
