"""Deterministic-first filler for hosted ATS forms and portal apply modals."""

from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from backend.app.browser_v2.adapters.base import HitlQuestion, JobDetail
from backend.app.browser_v2.adapters.shared.dom_scripts import OPTIONS_JS, SCAN_JS
from backend.app.browser_v2.adapters.shared.text import (
    COVER_NOTE,
    NoteComposer,
    resolve_question,
)
from backend.app.browser_v2.answers import CandidateFacts, ScreeningResolver
from backend.app.browser_v2.resume import pick_resume

logger = logging.getLogger(__name__)
ACTION_TIMEOUT_MS = 8_000  # one form widget never blocks the apply for 30 s
MAX_COMBOBOX_OPTIONS = 400

# --- hosted form scanning + filling ---------------------------------------------------------
IDENTITY_FIELDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("first_name", re.compile(r"^(?:legal\s+|preferred\s+)?first\s*name$|^given\s+name$", re.IGNORECASE)),
    ("last_name", re.compile(r"^(?:legal\s+)?last\s*name$|^surname$|^family\s+name$", re.IGNORECASE)),
    ("full_name", re.compile(r"^(?:what\s+is\s+)?(?:your\s+)?(?:full\s+|legal\s+|full\s+legal\s+)?name\??$",
                             re.IGNORECASE)),
    ("email", re.compile(r"^(?:your\s+)?e-?mail(?:\s+address|\s+id)?$", re.IGNORECASE)),
    ("phone", re.compile(r"^(?:your\s+)?(?:phone|mobile|cell|contact)(?:\s+(?:number|no\.?))?$", re.IGNORECASE)),
    ("linkedin_url", re.compile(r"linkedin", re.IGNORECASE)),
    ("github_url", re.compile(r"github", re.IGNORECASE)),
    ("portfolio_url", re.compile(r"^(?:personal\s+|other\s+)?(?:website|portfolio|site)(?:\s+(?:url|link))?$", re.IGNORECASE)),
    ("current_location", re.compile(r"^(?:current\s+)?(?:location|city)(?:\s*\(city\))?$", re.IGNORECASE)),
)
AUTOCOMPLETE_MAP = {"given-name": "first_name", "family-name": "last_name", "name": "full_name", "email": "email",
                    "tel": "phone", "url": "portfolio_url", "address-level2": "current_location"}
NAME_ATTR_MAP = {"first_name": "first_name", "firstname": "first_name", "last_name": "last_name",
                 "lastname": "last_name", "name": "full_name", "full_name": "full_name", "email": "email",
                 "phone": "phone", "mobile": "phone", "location": "current_location",
                 "urls[linkedin]": "linkedin_url", "urls[github]": "github_url", "urls[portfolio]": "portfolio_url"}
RESUME_FIELD = re.compile(r"resume|\bcv\b|curriculum", re.IGNORECASE)
COVER_FILE = re.compile(r"cover\s*letter", re.IGNORECASE)


def clean_label(label: str | None) -> str:
    """Drop trailing required markers: "*" (Greenhouse), "✱" (Lever, live 2026-11-26), "(required)"."""
    return re.sub(r"(?:\s*(?:[*✱✳＊]|\(required\)))+\s*$", "", " ".join((label or "").split()),
                  flags=re.IGNORECASE).strip()


def identity_key(field: dict[str, Any]) -> str | None:
    label = clean_label(field.get("label"))
    for key, pattern in IDENTITY_FIELDS:
        if pattern.search(label):
            return key
    auto = (field.get("autocomplete") or "").lower()
    if auto in AUTOCOMPLETE_MAP:
        return AUTOCOMPLETE_MAP[auto]
    name = (field.get("name") or "").lower()
    return NAME_ATTR_MAP.get(name)


@dataclass
class FillOutcome:
    filled: list[dict[str, str]] = field(default_factory=list)
    question: HitlQuestion | None = None
    resume: str | None = None
    planned_uploads: list[str] = field(default_factory=list)


class HostedFormFiller:
    """Fill one visible form (document or a modal root) deterministically first."""

    def __init__(self, *, answerer: ScreeningResolver | None = None, composer: NoteComposer | None = None,
                 settle_ms: int = 250, jitter: tuple[float, float] = (0.2, 0.6)) -> None:
        self.answerer = answerer
        self.composer = composer
        self.settle_ms = settle_ms
        self.jitter = jitter

    async def scan(self, page: Any, root: str | None = None) -> list[dict[str, Any]]:
        data = await page.evaluate(SCAN_JS, {"root": root, "maxFields": 80})
        return list(data.get("fields") or [])

    async def _pause(self) -> None:
        if self.jitter[1] > 0:
            await asyncio.sleep(random.uniform(*self.jitter))

    async def fill(self, page: Any, detail: JobDetail, facts: CandidateFacts, *, root: str | None = None,
                   hitl_answers: dict[str, str] | None = None, dry_run: bool = False,
                   platform: str = "") -> FillOutcome:
        outcome = FillOutcome()
        choice = pick_resume(facts.resume_files, title=detail.listing.title, description=detail.description,
                             fallback_path=facts.identity.get("resume_path"))
        for item in await self.scan(page, root):
            kind = item.get("kind")
            label = clean_label(item.get("label"))
            required = bool(item.get("required"))
            if kind == "file":
                if RESUME_FIELD.search(label) or RESUME_FIELD.search(item.get("name") or ""):
                    if choice.path is None:
                        if required:
                            outcome.question = self._question(detail, "Resume upload is required but no resume "
                                                              "PDF is configured (preferences.resume_files)",
                                                              (), "file", platform, "resume_missing")
                            return outcome
                        continue
                    outcome.resume = choice.label or Path(choice.path).name
                    if dry_run:
                        outcome.planned_uploads.append(Path(choice.path).name)
                        continue
                    await page.locator(f'[data-aa-field="{item["idx"]}"]').set_input_files(choice.path)
                    outcome.filled.append({"question": label or "resume", "answer": Path(choice.path).name,
                                           "source": "resume_picker"})
                    await page.wait_for_timeout(self.settle_ms)
                    continue
                if required:
                    outcome.question = self._question(detail, label or "File upload", (), "file", platform,
                                                      "file_upload_required")
                    return outcome
                continue
            if item.get("value_present"):
                continue
            key = identity_key(item) if kind not in ("radio", "checkbox", "select") else None
            if key is not None:
                value = facts.identity.get(key)
                if value is None and key == "full_name" and facts.identity.get("first_name"):
                    value = " ".join(v for v in (facts.identity.get("first_name"), facts.identity.get("last_name"))
                                     if v)
                if value:
                    await self._type(page, item, value)
                    outcome.filled.append({"question": label, "answer": key, "source": "profile_identity"})
                    continue
                if required:
                    outcome.question = self._question(detail, label, (), "text", platform, "identity_fact_missing")
                    return outcome
                continue
            if not required:
                continue  # optional unknowns (EEO, referral source, ...) are never guessed
            options = tuple(o["label"] if isinstance(o, dict) else str(o) for o in item.get("options") or ())
            if kind == "checkbox" and item.get("single"):
                options = ("Yes", "No")
            if kind == "combobox":
                options = await self._combobox_options(page, item)
            answer, source, reason = await resolve_question(label, options, facts, detail, self.answerer,
                                                            hitl_answers)
            if answer is None and kind in ("textarea", "text") and COVER_NOTE.search(label) \
                    and self.composer is not None:
                answer = await self.composer(detail, facts)
                source, reason = ("composer", "intro_note") if answer else (source, reason)
            if answer is None:
                outcome.question = self._question(
                    detail, label, options, "choice" if options else "text", platform, reason)
                return outcome
            if kind == "checkbox" and item.get("single") and answer.strip().lower() not in ("yes", "y", "true"):
                outcome.question = self._question(detail, label, ("Yes", "No"), "choice", platform,
                                                  "required_checkbox_declined")
                return outcome
            await self._pause()
            if not await self._apply_answer(page, item, answer):
                outcome.question = self._question(detail, label, options, "choice" if options else "text",
                                                  platform, "answer_not_applicable")
                return outcome
            outcome.filled.append({"question": label, "answer": answer, "source": source})
        return outcome

    def _question(self, detail: JobDetail, prompt: str, options: tuple[str, ...], input_kind: str,
                  platform: str, reason: str) -> HitlQuestion:
        return HitlQuestion(kind="QUESTION", prompt=prompt or "Unlabelled required field", options=options,
                            input_kind=input_kind,
                            context={"job_id": detail.listing.external_job_id, "url": detail.apply_url
                                     or detail.listing.url, "title": detail.listing.title,
                                     "company": detail.listing.company, "platform": platform,
                                     "resolver_reason": reason})

    async def _type(self, page: Any, item: dict[str, Any], value: str) -> None:
        locator = page.locator(f'[data-aa-field="{item["idx"]}"]')
        await locator.fill(value)
        if item.get("kind") == "combobox":
            await page.wait_for_timeout(self.settle_ms)
            await locator.press("Enter")

    async def _combobox_options(self, page: Any, item: dict[str, Any]) -> tuple[str, ...]:
        """Options of THIS combobox only (live 2026-11-26 greenhouse: a page-wide [role=option] read
        returned the phone country-code picker's list for "Are you currently based in Bangalore?")."""
        field = f'[data-aa-field="{item["idx"]}"]'
        locator = page.locator(field)
        try:
            before = await page.evaluate(OPTIONS_JS, {"field": field, "scoped": False})
            await locator.click()
            await page.wait_for_timeout(self.settle_ms)
            scoped = await page.evaluate(OPTIONS_JS, {"field": field, "scoped": True})
            texts = scoped if scoped is not None else [
                t for t in await page.evaluate(OPTIONS_JS, {"field": field, "scoped": False}) if t not in set(before)]
            await locator.press("Escape")
        except Exception:  # noqa: BLE001 - unknown widget: treat as free text
            return ()
        # Phase 9: country / phone-code lists have ~250 options ("India +91" is far past the first 50).
        return tuple(dict.fromkeys(" ".join(t.split()) for t in texts if t.strip()))[:MAX_COMBOBOX_OPTIONS]

    async def _apply_answer(self, page: Any, item: dict[str, Any], answer: str) -> bool:
        """False (-> owner question) when the widget cannot take the answer; never raises.

        Phase 9 go-live: a non-fillable Greenhouse widget made `locator.fill` wait the default 30 s and
        the exception fenced the job as SUBMISSION_UNKNOWN although nothing had been submitted."""
        try:
            return await self._apply_answer_unsafe(page, item, answer)
        except Exception as exc:  # noqa: BLE001 - Playwright timeout / detached / not editable
            logger.info("form field %s not answerable: %s", item.get("idx"), type(exc).__name__)
            return False

    async def _apply_answer_unsafe(self, page: Any, item: dict[str, Any], answer: str) -> bool:
        kind = item.get("kind")
        if kind in ("radio", "checkbox"):
            options = item.get("options") or []
            if item.get("single"):
                target = options[0] if options else None
            else:
                wanted = answer.strip().lower()
                target = next((o for o in options if o["label"].strip().lower() == wanted), None)
            if target is None:
                return False
            locator = page.locator(f'[data-aa-field="{target["idx"]}"]')
            if kind == "checkbox":
                await locator.check(force=True, timeout=ACTION_TIMEOUT_MS)
            else:
                await locator.check(force=True, timeout=ACTION_TIMEOUT_MS)
            return True
        locator = page.locator(f'[data-aa-field="{item["idx"]}"]')
        if kind == "select":
            await locator.select_option(label=answer, timeout=ACTION_TIMEOUT_MS)
            return True
        if kind == "combobox":
            await locator.click(timeout=ACTION_TIMEOUT_MS)
            await locator.fill(answer, timeout=ACTION_TIMEOUT_MS)
            await page.wait_for_timeout(self.settle_ms)
            listbox = (await locator.get_attribute("aria-controls") or await locator.get_attribute("aria-owns")
                       or "").split(" ")[0]
            scope = page.locator(f'[id="{listbox}"]') if listbox else page
            option = scope.locator("[role=option]").filter(
                has_text=re.compile(r"^\s*" + re.escape(answer) + r"\s*$")).filter(visible=True)
            if await option.count():
                await option.first.click(timeout=ACTION_TIMEOUT_MS)
            else:
                await locator.press("Enter", timeout=ACTION_TIMEOUT_MS)
            return True
        await locator.fill(answer, timeout=ACTION_TIMEOUT_MS)
        return True
