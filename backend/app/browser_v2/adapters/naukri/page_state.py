"""Naukri page-state reads: screenshots, Apply control, polling, confirmation and history."""

from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from backend.app.browser_v2.adapters.base import JobDetail
from backend.app.browser_v2.adapters.naukri.auth import NaukriAuthMixin
from backend.app.browser_v2.adapters.naukri.constants import (
    APPLY_SETTLE_POLLS,
    APPLY_SUCCESS,
    HISTORY_SENT,
    HISTORY_URL,
    PORTAL_LIMIT,
)
from backend.app.browser_v2.adapters.naukri.dom_scripts import (
    HISTORY_ALL_JS,
    HISTORY_JS,
    MARK_APPLY_JS,
    PAGE_STATE_JS,
)
from backend.app.browser_v2.receipts import prune_failures


class NaukriPageStateMixin(NaukriAuthMixin):
    """Chatbot/page state polling, Apply-control resolution and history verification."""

    async def _pause(self) -> None:
        await asyncio.sleep(random.uniform(*self.jitter))

    async def _screenshot(self, page: Any, job_id: str, label: str) -> str | None:
        # Phase 6A: verified receipts stay in receipts/naukri; every other capture goes to the
        # receipts/failures ring buffer (newest 20 kept).
        folder = self.receipts_dir if label == "receipt" else self.receipts_dir.parent / "failures"
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        path = folder / f"naukri-{job_id}-{stamp}-{label}.png"
        try:
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            await page.screenshot(path=str(path), full_page=False)
        except Exception:  # noqa: BLE001 - a missing screenshot must never change the outcome
            return None
        if label != "receipt":
            prune_failures(folder)
        return str(path)

    async def _state(self, page: Any) -> dict[str, Any]:
        """Live canary 2026-11-27: the last answer can navigate (success / saveApply page) while we
        poll; "Execution context was destroyed" is a navigation, not a failure - wait and re-read."""
        for attempt in range(4):
            try:
                return await page.evaluate(PAGE_STATE_JS)
            except Exception as exc:  # only navigation races are retried
                message = str(exc)
                if attempt == 3 or not ("Execution context was destroyed" in message or "navigat" in message):
                    raise
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=15_000)
                except Exception:  # noqa: BLE001, S110 - re-read whatever loaded
                    pass
                await page.wait_for_timeout(500)
        raise RuntimeError("unreachable")

    @staticmethod
    def _confirmation(state: dict[str, Any]) -> str | None:
        if state.get("headerApplied"):
            return "header_applied_button"
        if "saveapply" in str(state.get("url", "")).lower():
            return "save_apply_page"
        match = APPLY_SUCCESS.search(state.get("body") or "")
        return "success_text:" + match.group(0) if match else None

    async def _opt_out_company_follow(self, page: Any) -> None:
        checked = page.locator('[class*="fb_ckb_container"] [role=checkbox][aria-checked="true"]')
        if await checked.count() == 1:
            await checked.click()
            await page.wait_for_timeout(300)

    async def _apply_button(self, page: Any) -> Any:
        """Locator for the single visible Apply in the JD header (marked by MARK_APPLY_JS)."""
        return page.locator('[data-aa-apply="1"]')

    async def resolve_apply_control(self, page: Any, polls: int = APPLY_SETTLE_POLLS) -> dict[str, Any]:
        """Wait for the React JD header to settle, then classify the apply control.

        Returns {"mode": direct|external|applied|changed|none, "count": n}. `direct` means exactly
        one visible enabled Apply, unchanged across two consecutive reads, now marked for click.
        """
        previous: tuple[Any, ...] | None = None
        state: dict[str, Any] = {}
        for attempt in range(max(1, polls)):
            state = await page.evaluate(MARK_APPLY_JS)
            if state.get("applied"):
                return {"mode": "applied", **state}
            if state.get("external") and not state.get("count"):
                return {"mode": "external", **state}
            key = (state.get("count"), state.get("external"), state.get("drawer"))
            if state.get("count") == 1 and key == previous:
                return {"mode": "direct", **state}
            previous = key
            if attempt + 1 < polls:
                await page.wait_for_timeout(250)
        mode = "changed" if state.get("count") else "none"
        return {"mode": mode, **state}

    async def _poll(self, page: Any, done: Any, timeout_s: float) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        state = await self._state(page)
        while not done(state) and loop.time() < deadline:
            await page.wait_for_timeout(250)
            state = await self._state(page)
        return state

    async def _wait_after_click(self, page: Any, pages_before: int) -> dict[str, Any]:
        """After Apply: the chatbot opens, a confirmation shows, a limit appears or we leave."""
        return await self._poll(page, lambda st: bool(
            st.get("drawer") or self._confirmation(st) or PORTAL_LIMIT.search(st.get("body") or "")
            or len(page.context.pages) > pages_before
            or urlsplit(st.get("url", "")).hostname not in {"www.naukri.com", "naukri.com"}), 10.0)

    async def _wait_after_answer(self, page: Any, question: str) -> dict[str, Any]:
        return await self._poll(page, lambda st: bool(
            not st.get("drawer") or st.get("question") != question or self._confirmation(st)
            or PORTAL_LIMIT.search(st.get("body") or "")), 8.0)

    async def _settle_question(self, page: Any, state: dict[str, Any]) -> dict[str, Any]:
        """Phase 8: the drawer opens (and changes question) before the bot's message and its
        controls render (typing animation). Wait until the question has an input to answer."""
        def ready(st: dict[str, Any]) -> bool:
            return bool(not st.get("drawer") or self._confirmation(st) or PORTAL_LIMIT.search(st.get("body") or "")
                        or (st.get("question") and (st.get("chips") or st.get("radios") or st.get("checkboxes")
                                                    or st.get("selectOptions") or st.get("textInput"))))
        if ready(state):
            return state
        return await self._poll(page, ready, 8.0)

    async def history_rows(self, page: Any) -> list[dict[str, Any]]:
        """Every visible row of the Naukri application history (title, company, status)."""
        await self._goto(page, HISTORY_URL)
        try:
            await page.wait_for_selector(".jdTuplesContainer .jdTupleContainer", timeout=12_000)
        except Exception:  # noqa: BLE001, S110 - empty history or layout drift: nothing verifies
            pass
        return await page.evaluate(HISTORY_ALL_JS)

    @staticmethod
    def history_match(rows: list[dict[str, Any]], title: str | None, company: str | None) -> dict[str, Any] | None:
        norm = lambda v: " ".join((v or "").lower().split())
        sent = [r for r in rows if norm(r.get("title")) == norm(title) and norm(r.get("company")) == norm(company)
                and HISTORY_SENT.match(r.get("status") or "")]
        return sent[0] if title and company and len(sent) == 1 else None

    async def _confirm_from_history(self, page: Any, detail: JobDetail) -> str | None:
        await self._goto(page, HISTORY_URL)
        rows = await page.evaluate(HISTORY_JS, {"title": detail.listing.title or "",
                                                "company": detail.listing.company or ""})
        sent = [r for r in rows if HISTORY_SENT.match(r.get("status") or "")]
        return "application_history" if len(sent) == 1 else None
