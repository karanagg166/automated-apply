"""Naukri chatbot questionnaire: answer matching, typing/clicking answers, resolution."""

from __future__ import annotations

import logging
import re
from typing import Any

from backend.app.browser_v2.adapters.base import ApplyResult, JobDetail
from backend.app.browser_v2.adapters.naukri.base import NaukriAdapterBase
from backend.app.browser_v2.adapters.shared.text import (
    ResolvedField,
    resolve_question_detail,
)
from backend.app.browser_v2.answers import CandidateFacts
from backend.app.browser_v2.state import ApplicationState

logger = logging.getLogger(__name__)


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
                       detail: JobDetail, hitl_answers: dict[str, str] | None = None, *,
                       field_kind: str | None = None) -> tuple[str | None, str, str]:
        resolved = await self._resolve_field(question, options, facts, detail, hitl_answers, field_kind=field_kind)
        return resolved.answer, resolved.source, resolved.reason

    async def _resolve_field(self, question: str, options: tuple[str, ...], facts: CandidateFacts,
                             detail: JobDetail, hitl_answers: dict[str, str] | None = None, *,
                             field_kind: str | None = None) -> ResolvedField:
        """Milestone 2: the same 4-tier cascade + metadata as the hosted-ATS filler (owner HITL answer,
        deterministic facts, semantic cache v2 keyed by company/portal/field_type/options, LLM)."""
        return await resolve_question_detail(question, options, facts, detail, self.answerer, hitl_answers,
                                             field_kind=field_kind, platform="naukri")

    async def _quarantine_rejected(self, entry_id: str | None) -> bool:
        """Naukri refused the value a cached answer filled (the drawer re-asked the same question):
        quarantine that semantic-cache entry so it never poisons another application."""
        cache = getattr(self.answerer, "cache", None)
        record = getattr(cache, "record_form_validation_error", None)
        if not entry_id or record is None:
            return False
        try:
            await record(entry_id)
        except Exception as exc:  # noqa: BLE001 - quarantine is best effort; the outcome still stands
            logger.info("naukri cache quarantine of %s failed: %s", entry_id, type(exc).__name__)
            return False
        return True

    def _result(self, state: ApplicationState, reason: str, dry_run: bool, **extra: Any) -> ApplyResult:
        return ApplyResult(state=state, reason=reason, dry_run=dry_run, **extra)
