"""Naukri chatbot questionnaire: answer matching, typing/clicking answers, resolution."""

from __future__ import annotations

import re
from typing import Any

from backend.app.browser_v2.adapters.base import ApplyResult, JobDetail
from backend.app.browser_v2.adapters.naukri.base import NaukriAdapterBase
from backend.app.browser_v2.answers import CandidateFacts, hitl_override, resolve_answer
from backend.app.browser_v2.state import ApplicationState


class NaukriQuestionnaireMixin(NaukriAdapterBase):
    """multi_answers / _answer / _resolve / _result."""

    @staticmethod
    def multi_answers(answer: str, options: tuple[str, ...]) -> list[str]:
        """'Python, Go' -> the matching checkbox labels (exact, case-insensitive); [] if any part misses."""
        wanted = [p.strip() for p in re.split(r"\s*(?:,|;|\band\b|\|)\s*", answer or "") if p.strip()]
        lookup = {o.strip().lower(): o for o in options}
        picked = [lookup.get(w.lower()) for w in wanted]
        return [p for p in picked if p] if picked and all(picked) else []

    async def _answer(self, page: Any, state: dict[str, Any], answer: str) -> None:
        drawer = page.locator(".chatbot_DrawerContentWrapper")
        send = drawer.locator(".send, button").filter(
            has_text=re.compile(r"^\s*(save|send|next|continue|submit)\s*$", re.IGNORECASE))
        if state.get("checkboxes"):
            for label in self.multi_answers(answer, tuple(state["checkboxes"])):
                await drawer.locator("label").filter(has_text=re.compile(r"^\s*" + re.escape(label) + r"\s*$")).first.click()
                await page.wait_for_timeout(150)
            await send.first.click()
            return
        if state.get("selectOptions"):
            await drawer.locator("select").first.select_option(label=answer)
            await page.wait_for_timeout(300)
            await send.first.click()
            return
        if state.get("chips"):
            await drawer.locator(".chipsContainer .chatbot_Chip").filter(
                has_text=re.compile(r"^\s*" + re.escape(answer) + r"\s*$")).first.click()
            return
        if state.get("radios"):
            # Options are the radio VALUES; the visible label may differ ("dont" vs "don't").
            value = answer.replace("\\", "\\\\").replace('"', '\\"')
            radio = drawer.locator(f'input.ssrc__radio[type="radio"][value="{value}"]')
            radio_id = await radio.first.get_attribute("id") if await radio.count() else None
            label = drawer.locator(f'label[for="{radio_id}"]') if radio_id else drawer.locator(
                "label.ssrc__label").filter(has_text=re.compile(r"^\s*" + re.escape(answer) + r"\s*$"))
            if await label.count():
                await label.first.click()
            else:
                await radio.first.check(force=True)
            await page.wait_for_timeout(300)
            await send.first.click()
            return
        editor = drawer.locator('.textArea[contenteditable="true"],textarea,input[type=text]').first
        await editor.click()
        await editor.fill(answer)
        await page.wait_for_timeout(300)
        await send.first.click()

    async def _resolve(self, question: str, options: tuple[str, ...], facts: CandidateFacts,
                       detail: JobDetail, hitl_answers: dict[str, str] | None = None
                       ) -> tuple[str | None, str, str]:
        owner = hitl_override(question, options, hitl_answers)
        if owner is not None:  # Phase 4: resolved via Telegram/dashboard (incl. /once answers)
            return owner, "human_hitl", "hitl_owner_answer"
        if self.answerer is None:
            answer = resolve_answer(question, options, facts)
            return answer, "profile" if answer is not None else "human", "deterministic_only"
        resolved = await self.answerer.resolve(question, options, facts, {
            "title": detail.listing.title, "company": detail.listing.company})
        return resolved.answer, resolved.source, resolved.reason

    def _result(self, state: ApplicationState, reason: str, dry_run: bool, **extra: Any) -> ApplyResult:
        return ApplyResult(state=state, reason=reason, dry_run=dry_run, **extra)
