"""Naukri `apply_job`: Apply click, chatbot questionnaire loop and receipt verification."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from backend.app.browser_v2.adapters.base import ApplyResult, HitlQuestion, JobDetail
from backend.app.browser_v2.adapters.naukri.constants import (
    MAX_QUESTION_STEPS,
    OPTIONAL_QUESTION,
    OTP_VALUE,
    PORTAL_LIMIT,
)
from backend.app.browser_v2.adapters.naukri.discovery import NaukriDiscoveryMixin
from backend.app.browser_v2.adapters.naukri.page_state import NaukriPageStateMixin
from backend.app.browser_v2.adapters.naukri.questionnaire import (
    NaukriQuestionnaireMixin,
)
from backend.app.browser_v2.answers import CandidateFacts
from backend.app.browser_v2.state import ApplicationState, guard_apply
from backend.app.browser_v2.submit_marker import mark_submit_attempted


class NaukriApplyMixin(NaukriQuestionnaireMixin, NaukriPageStateMixin, NaukriDiscoveryMixin):
    """apply_job (dry-run stops before the Apply click)."""

    tracks_submit = True  # mark_submit_attempted() runs right before the Apply click

    async def apply_job(self, page: Any, detail: JobDetail, profile: CandidateFacts | Any, *,
                        dry_run: bool = True, existing_state: str | None = None,
                        hitl_answers: dict[str, str] | None = None) -> ApplyResult:
        guard_apply(existing_state)
        facts = profile if isinstance(profile, CandidateFacts) else CandidateFacts.from_profile(profile)
        job_id = detail.listing.external_job_id
        if detail.challenge == "otp" and not dry_run:
            # Phase 6A: owner OTP (Telegram/dashboard) or auto email-OTP, then re-inspect once.
            entered, _otp_source = await self.recover_otp(page, hitl_answers)
            if entered:
                await self._goto(page, detail.listing.url)
                fresh = await self.inspect_job(page, detail.listing)
                if fresh.challenge != "otp":
                    return await self.apply_job(page, fresh, facts, dry_run=dry_run, existing_state=existing_state,
                                                hitl_answers={k: v for k, v in (hitl_answers or {}).items()
                                                              if not OTP_VALUE.match(v or "")})
        if detail.challenge:
            kind = {"challenge": "CAPTCHA", "otp": "OTP", "login": "AUTH"}[detail.challenge]
            return self._result(ApplicationState.WAITING_FOR_USER, "portal_" + detail.challenge, dry_run,
                                question=HitlQuestion(kind=kind, prompt=f"Naukri needs {kind} on {detail.listing.url}"))
        if detail.portal_limit:
            return self._result(ApplicationState.QUOTA_HIT_PENDING, "portal_daily_limit", dry_run,
                                receipt={"limit_text": detail.portal_limit})
        if detail.already_applied:
            return self._result(ApplicationState.APPLIED, "already_applied_on_portal", dry_run,
                                receipt={"source": "header_applied_before_action", "url": detail.listing.url,
                                         "verified_at": datetime.now(UTC).isoformat()})
        if detail.apply_mode == "external":
            return self._result(ApplicationState.FILTERED_OUT, "external_company_site", dry_run)
        if detail.apply_mode == "closed":
            return self._result(ApplicationState.FILTERED_OUT, "job_closed", dry_run)
        if detail.apply_mode != "direct":
            return self._result(ApplicationState.FAILED, f"apply_control_{detail.apply_mode}", dry_run)

        await self._opt_out_company_follow(page)
        control = await self.resolve_apply_control(page)
        if control["mode"] == "applied":  # hydration revealed the header "Applied" badge
            return self._result(ApplicationState.APPLIED, "already_applied_on_portal", dry_run,
                                receipt={"source": "header_applied_before_action", "url": detail.listing.url,
                                         "verified_at": datetime.now(UTC).isoformat()})
        if control["mode"] == "external":  # hydration swapped Apply -> "Apply on company site"
            return self._result(ApplicationState.FILTERED_OUT, "external_company_site", dry_run)
        button = await self._apply_button(page)
        if control["mode"] != "direct" or await button.count() != 1:
            return self._result(ApplicationState.FAILED, "apply_control_changed", dry_run,
                                screenshot=await self._screenshot(page, job_id, "apply-control"))
        planned = f"click Naukri 'Apply' for {job_id} ({detail.listing.title} @ {detail.listing.company})"
        if dry_run:
            shot = await self._screenshot(page, job_id, "dry-run")
            return self._result(ApplicationState.SCORED, "dry_run_stopped_before_apply_click", True,
                                planned_action=planned, screenshot=shot)

        await self._pause()
        pages_before = len(page.context.pages)
        mark_submit_attempted("naukri_apply")  # Naukri's Apply may submit at once (no questionnaire)
        await button.click()
        state = await self._wait_after_click(page, pages_before)
        if len(page.context.pages) > pages_before or urlsplit(state.get("url", "")).hostname not in {
                "www.naukri.com", "naukri.com"}:
            return self._result(ApplicationState.FILTERED_OUT, "external_company_site_after_click", False,
                                clicked_apply=True)
        answers: list[dict[str, str]] = []
        for _ in range(MAX_QUESTION_STEPS):
            if PORTAL_LIMIT.search(state.get("body") or ""):
                return self._result(ApplicationState.QUOTA_HIT_PENDING, "portal_daily_limit_after_click",
                                    False, clicked_apply=True)
            if not state.get("drawer") or self._confirmation(state):
                break
            state = await self._settle_question(page, state)
            if not state.get("drawer") or self._confirmation(state):
                break
            if PORTAL_LIMIT.search(state.get("body") or ""):
                return self._result(ApplicationState.QUOTA_HIT_PENDING, "portal_daily_limit_after_click",
                                    False, clicked_apply=True)
            question = state.get("question") or ""
            multi = tuple(state.get("checkboxes") or ())
            options = tuple(state.get("chips") or state.get("radios") or state.get("selectOptions") or multi)
            # Live canary 2026-11-27: the drawer always holds a hidden resume-uploader <input type=file>;
            # checking it first turned every radio question into "file_upload" -> needless HITL.
            input_kind = ("multi" if multi else "choice" if options else "text" if state.get("textInput")
                          else "file" if state.get("fileInput") else "text")
            if input_kind == "text" and not state.get("textInput"):
                # Unknown control (date picker, slider ...): Naukri has not submitted yet (the drawer
                # is still asking) - stop and ask the owner instead of guessing or raising.
                return self._result(
                    ApplicationState.WAITING_FOR_USER, "questionnaire_unsupported_control", False,
                    clicked_apply=True, answers=tuple(answers),
                    screenshot=await self._screenshot(page, job_id, "unsupported"),
                    question=HitlQuestion(kind="ERROR", prompt=f"Naukri asked a question with an unsupported "
                                                               f"control: {question[:300]}",
                                          context={"job_id": job_id, "url": detail.listing.url}))
            answer, answer_source, resolver_reason, entry_id = None, "human", "file_upload", None
            if input_kind != "file":
                resolved = await self._resolve_field(question, options, facts, detail, hitl_answers,
                                                     field_kind=input_kind)
                answer, answer_source, resolver_reason = resolved.answer, resolved.source, resolved.reason
                entry_id = resolved.cache_entry_id
            if answer is not None and input_kind == "multi" and not self.multi_answers(answer, multi):
                answer, resolver_reason = None, "multi_select_answer_not_in_options"
            if answer is None and state.get("skippable") and OPTIONAL_QUESTION.search(question):
                await self._pause()
                await page.locator(".chatbot_DrawerContentWrapper").get_by_text(
                    re.compile(r"^\s*skip this question\s*$", re.IGNORECASE)).last.click()
                answers.append({"question": question, "answer": "[skipped: optional]", "source": "skip_optional"})
                state = await self._wait_after_answer(page, question)
                if state.get("drawer") and state.get("question") == question and not self._confirmation(state):
                    return self._result(ApplicationState.SUBMISSION_UNKNOWN, "questionnaire_stalled", False,
                                        clicked_apply=True, answers=tuple(answers),
                                        screenshot=await self._screenshot(page, job_id, "stalled"))
                continue
            if answer is None:
                return self._result(
                    ApplicationState.WAITING_FOR_USER, "question_requires_owner", False, clicked_apply=True,
                    answers=tuple(answers), screenshot=await self._screenshot(page, job_id, "question"),
                    question=HitlQuestion(kind="QUESTION", prompt=question, options=options,
                                          input_kind=input_kind,
                                          context={"job_id": job_id, "url": detail.listing.url,
                                                   "title": detail.listing.title,
                                                   "company": detail.listing.company,
                                                   "resolver_reason": resolver_reason}))
            await self._pause()
            await self._answer(page, state, answer)
            entry = {"question": question, "answer": answer, "source": answer_source}
            if entry_id:  # lets a rejection quarantine the cached answer (semantic cache v2)
                entry["cache_entry_id"] = entry_id
            answers.append(entry)
            state = await self._wait_after_answer(page, question)
            if state.get("drawer") and state.get("question") == question and not self._confirmation(state):
                # Naukri re-asked the same question: it refused the value we filled.
                await self._quarantine_rejected(entry_id)
                return self._result(ApplicationState.SUBMISSION_UNKNOWN, "questionnaire_stalled", False,
                                    clicked_apply=True, answers=tuple(answers),
                                    screenshot=await self._screenshot(page, job_id, "stalled"))
        else:
            return self._result(ApplicationState.SUBMISSION_UNKNOWN, "questionnaire_step_limit", False,
                                clicked_apply=True, answers=tuple(answers))

        source = self._confirmation(await self._poll(page, self._confirmation, 6.0))
        shot = await self._screenshot(page, job_id, "receipt")
        if source is None:
            source = await self._confirm_from_history(page, detail)
        if source is None:
            return self._result(ApplicationState.SUBMISSION_UNKNOWN, "confirmation_ambiguous", False,
                                clicked_apply=True, answers=tuple(answers), screenshot=shot)
        receipt = {"source": source, "url": detail.listing.url, "screenshot": shot,
                   "verified_at": datetime.now(UTC).isoformat(), "answers": answers,
                   "resume_variant_used": "portal_profile"}  # Naukri sends the profile's own resume
        return self._result(ApplicationState.APPLIED, "confirmed", False, clicked_apply=True,
                            receipt=receipt, screenshot=shot, answers=tuple(answers))
