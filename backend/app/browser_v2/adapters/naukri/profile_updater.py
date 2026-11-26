"""Naukri profile updater (Phase 9D portal profile sync).

Selectors are PORTED, not invented, from the legacy reference implementation (read-only):
``extension/naukri-execution.js`` (profile summary section/value/editor/Save),
``extension/naukri-profile-skills.js`` (Key skills card, chips, keySkillsForm, #keySkillSugg,
#saveKeySkills) and ``extension/naukri-resume-download.js`` (Resume card). The current Naukri UI
has NOT been re-verified against them, so ``calibrated = False``: read/write/touch return
``skipped_not_calibrated`` / False without touching the page until the owner runs
``cli probe-profile-page --portal naukri`` and a fixture test covers the selectors.

Fields with no legacy selectors (resume headline, notice period, CTC, preferred locations,
resume upload input, the "Profile last updated" text) stay ``None`` and are never guessed.
Skills are add-only (legacy: "no chip removal"); one Save click per field, never repeated.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from types import MappingProxyType
from typing import Any

from backend.app.browser_v2.adapters.challenge import CHALLENGE_HELPERS_JS
from backend.app.browser_v2.profile_sync.adapters.base import not_calibrated
from backend.app.browser_v2.profile_sync.models import FieldStatus, FieldValue

PROFILE_URL = "https://www.naukri.com/mnjuser/profile"
FIELDS = frozenset({"resume_headline", "profile_summary", "key_skills", "notice_period", "current_ctc",
                    "expected_ctc", "preferred_locations", "resume_pdf"})
# Fields whose selectors exist in the legacy reference implementation.
LEGACY_FIELDS = frozenset({"profile_summary", "key_skills"})
SELECTORS: MappingProxyType[str, str | None] = MappingProxyType({
    # naukri-execution.js summarySection()/summaryValue()
    "profile_summary.heading": 'h1.section-heading,h2,h3,h4,[class*="widgetTitle"]',
    "profile_summary.section": '.profileSummary.section,section,[class*="widget"],[class*="card"]',
    "profile_summary.value": ".widgetCont > .prefill,.card-container .card-details > p.card-sub-heading",
    "profile_summary.more": 'a.morelink[aria-label="Read more of profile summary"]',
    "profile_summary.edit": "[role=button][aria-label='Edit profile summary'],"
                            ".profileSummary.section h1.section-heading .new-pencil",
    "profile_summary.editor": 'textarea[aria-label="Profile summary"],[role=dialog] textarea#summary[name="summary"]',
    "profile_summary.save": "button:visible:text-is('Save')",
    # naukri-profile-skills.js
    "key_skills.section": "#lazyKeySkills .card",
    "key_skills.chip": ".widgetCont > .prefill > span.chip",
    "key_skills.edit": '#lazyKeySkills .card [role=button][aria-label="Edit key skills"]',
    "key_skills.form": '.keySkillsEdit.model_open form[name="keySkillsForm"]',
    "key_skills.input": "#keySkillSugg",
    "key_skills.save": "button#saveKeySkills",
    # naukri-resume-download.js (download control only: the upload input was never captured)
    "resume_pdf.section": '#lazyAttachCV.card,.section.resume',
    "resume_pdf.upload_input": None,
    "profile.last_updated": None,
    "resume_headline": None,
    "notice_period": None,
    "current_ctc": None,
    "expected_ctc": None,
    "preferred_locations": None,
})
_FRESH = re.compile(r"\b(?:today|just now|few (?:seconds|minutes)|\d+\s*(?:sec|min)\w* ago)\b", re.IGNORECASE)

READ_JS = "(sel) => {\n" + CHALLENGE_HELPERS_JS + r"""
  const visible = (e) => !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== "hidden";
  const clean = (e) => (e && e.textContent || "").replace(/\s+/g, " ").trim();
  if (challengeNodes() || challengeText(document.body && document.body.innerText)) return {challenge: true};
  const out = {};
  const headings = [...document.querySelectorAll(sel["profile_summary.heading"])]
    .filter((e) => visible(e) && clean(e).toLowerCase() === "profile summary");
  if (headings.length === 1) {
    const section = headings[0].matches(".widgetTitle") ? headings[0].closest(".card")
      : headings[0].closest(sel["profile_summary.section"]);
    const values = section ? [...section.querySelectorAll(sel["profile_summary.value"])].filter(visible) : [];
    if (values.length === 1 && !values[0].querySelector(sel["profile_summary.more"])) {
      const clone = values[0].cloneNode(true);
      for (const link of clone.querySelectorAll("a.morelink")) link.remove();
      out.profile_summary = clean(clone);
    } else if (section && !values.length) out.profile_summary = "";
  }
  const cards = [...document.querySelectorAll(sel["key_skills.section"])].filter(visible);
  if (cards.length === 1) {
    const chips = [...cards[0].querySelectorAll(sel["key_skills.chip"])].filter(visible).map(clean);
    if (chips.length <= 100 && chips.every((v) => v && v.length <= 200)) out.key_skills = [...new Set(chips)];
  }
  return out;
}"""


class NaukriProfileUpdater:
    platform = "naukri"
    supported_fields = FIELDS
    calibrated = False  # legacy selectors, current UI not re-verified (see module docstring)
    calibrated_fields = LEGACY_FIELDS
    freshness_touch = True
    selectors = SELECTORS
    profile_url: str | None = PROFILE_URL

    def __init__(self, *, settle_ms: int = 1500) -> None:
        self.settle_ms = settle_ms

    async def _open_profile(self, page: Any) -> None:
        if not str(getattr(page, "url", "") or "").startswith(PROFILE_URL):
            await page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=45_000)
            await page.wait_for_timeout(self.settle_ms)

    async def _expand_summary(self, page: Any) -> None:
        more = page.locator(str(SELECTORS["profile_summary.more"]))
        if await more.count() == 1:
            await more.first.click()
            await page.wait_for_timeout(500)

    async def read(self, page: Any) -> dict[str, FieldValue]:
        if not self.calibrated:
            return not_calibrated(self.supported_fields)
        await self._open_profile(page)
        await self._expand_summary(page)
        raw = await page.evaluate(READ_JS, dict(SELECTORS)) or {}
        if raw.get("challenge"):
            return {name: FieldValue(status=FieldStatus.ERROR, reason="challenge_requires_owner")
                    for name in sorted(self.supported_fields)}
        out = not_calibrated(self.supported_fields - self.calibrated_fields)
        for name in sorted(self.calibrated_fields):
            out[name] = FieldValue(raw[name]) if name in raw else FieldValue(
                status=FieldStatus.ERROR, reason=f"{name}_section_not_found")
        return out

    async def write(self, page: Any, field: str, value: Any) -> bool:
        if not self.calibrated or field not in self.calibrated_fields:
            return False
        await self._open_profile(page)
        if field == "profile_summary":
            return await self._write_summary(page, str(value or ""))
        if field == "key_skills":
            return await self._add_skills(page, value if isinstance(value, Sequence) else ())
        return False

    async def _write_summary(self, page: Any, text: str) -> bool:
        if not text.strip():
            return False  # never-empty rule, also enforced by the diff
        edit = page.locator(str(SELECTORS["profile_summary.edit"]))
        if await edit.count() != 1:
            return False
        await edit.first.click()
        editor = page.locator(str(SELECTORS["profile_summary.editor"]))
        await editor.first.wait_for(state="visible", timeout=8000)
        if await editor.count() != 1:
            return False
        max_length = await editor.first.evaluate("(e) => e.maxLength")
        if isinstance(max_length, int) and 0 < max_length < len(text):
            return False  # legacy: profile_summary_exceeds_platform_limit
        await editor.first.fill(text)
        save = page.locator(str(SELECTORS["profile_summary.save"]))
        if await save.count() != 1:
            return False
        await save.first.click()  # exactly once; an uncertain save is never repeated
        await page.wait_for_timeout(self.settle_ms)
        return True

    async def _add_skills(self, page: Any, additions: Sequence[Any]) -> bool:
        values = [str(v).strip() for v in additions if isinstance(v, str) and v.strip()
                  and not re.search(r"[,\r\n]", v)]  # legacy: profile_skills_approved_value_invalid
        if not values:
            return False
        edit = page.locator(str(SELECTORS["key_skills.edit"]))
        if await edit.count() != 1:
            return False
        await edit.first.click()
        form = page.locator(str(SELECTORS["key_skills.form"]))
        await form.first.wait_for(state="visible", timeout=8000)
        field_input = form.first.locator(str(SELECTORS["key_skills.input"]))
        if await field_input.count() != 1:
            return False
        max_length = await field_input.first.evaluate("(e) => e.maxLength")
        added = 0
        for value in values:
            if isinstance(max_length, int) and 0 < max_length < len(value):
                continue
            await field_input.first.fill(value)
            await field_input.first.dispatch_event("blur")  # legacy: the chip is created on blur
            await page.wait_for_timeout(400)
            added += 1
        save = form.first.locator(str(SELECTORS["key_skills.save"]))
        if not added or await save.count() != 1:
            return False
        await save.first.click()
        await page.wait_for_timeout(self.settle_ms)
        return True

    async def _last_updated(self, page: Any) -> str | None:
        selector = SELECTORS["profile.last_updated"]
        if not selector:
            return None
        node = page.locator(selector)
        return (await node.first.inner_text()).strip() if await node.count() else None

    async def touch(self, page: Any, resume_path: str | None = None) -> bool:
        """Re-upload the identical active PDF; True only when "Profile last updated" proves it."""
        upload = SELECTORS["resume_pdf.upload_input"]
        if not self.calibrated or not upload or not SELECTORS["profile.last_updated"] or not resume_path:
            return False
        await self._open_profile(page)
        before = await self._last_updated(page)
        await page.locator(upload).set_input_files(resume_path)
        await page.wait_for_timeout(self.settle_ms * 2)
        after = await self._last_updated(page)
        return bool(after) and (after != before or bool(_FRESH.search(after or "")))
