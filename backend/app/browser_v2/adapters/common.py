"""Shared Phase 6A adapter engine.

- `classify_ats(url)`: greenhouse | lever | None for external employer links.
- `HostedFormFiller`: deterministic-first filler for hosted ATS forms and portal apply
  modals. Identity fields (name, email, phone, links, city) come from stored profile
  facts and are typed into the DOM only (never sent to an LLM). The best-matching
  resume PDF is uploaded. Every other REQUIRED question goes HITL answer -> 4-tier
  resolver (profile -> semantic cache -> free LLM) -> WAITING_FOR_USER. Optional
  unknown fields (EEO, demographics, "how did you hear") are left untouched.
- `HostedAtsApplier`: navigate to a Greenhouse/Lever form, fill, stop before Submit
  on dry-run, otherwise submit and verify a concrete confirmation signal.
- `InteractivePortalAdapter`: config-driven persistent-Brave portal adapter (session
  check with one reload, card discovery, detail parsing, Apply click + modal handling,
  confirmation / applied-badge verification, limit + challenge detection).

Selectors for the interactive portals are text/attribute based on purpose so small DOM
changes degrade to FAILED / SUBMISSION_UNKNOWN (never a blind replay).
"""

from __future__ import annotations

import asyncio
import html
import random
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

from backend.app.browser_v2.adapters.base import (
    ApplyResult,
    AuthStatus,
    HitlQuestion,
    JobDetail,
    JobListing,
    SessionCheck,
)
from backend.app.browser_v2.adapters.challenge import CHALLENGE_HELPERS_JS
from backend.app.browser_v2.answers import (
    CandidateFacts,
    ScreeningResolver,
    hitl_override,
    resolve_answer,
)
from backend.app.browser_v2.forms import extract_form
from backend.app.browser_v2.receipts import capture
from backend.app.browser_v2.resume import pick_resume
from backend.app.browser_v2.rules import (
    UNKNOWN_APPLICANTS,
    ApplicantCount,
    normalize_text,
    parse_applicants,
    parse_posted_age_days,
)
from backend.app.browser_v2.state import ApplicationState, guard_apply

S = ApplicationState
MAX_DESCRIPTION = 8_000
MAX_FORM_STEPS = 6

# --- external ATS classification ------------------------------------------------------------
GREENHOUSE_HOSTS = frozenset({"boards.greenhouse.io", "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io",
                              "boards.eu.greenhouse.io"})
LEVER_HOSTS = frozenset({"jobs.lever.co", "jobs.eu.lever.co"})
SUPPORTED_ATS = frozenset({"greenhouse", "lever"})
GREENHOUSE_PATH = re.compile(r"^/(?:embed/job_app|[A-Za-z0-9_-]{1,100}/jobs/\d{1,20})")
LEVER_PATH = re.compile(r"^/[A-Za-z0-9_.-]{1,100}/[0-9a-f-]{8,64}(?:/apply)?/?$")


def classify_ats(url: str | None) -> str | None:
    """greenhouse | lever for a hosted ATS application URL (https only), else None."""
    if not url:
        return None
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https":
        return None
    if host in GREENHOUSE_HOSTS and GREENHOUSE_PATH.match(parts.path):
        return "greenhouse"
    if host in LEVER_HOSTS and LEVER_PATH.match(parts.path):
        return "lever"
    return None


@dataclass(frozen=True)
class AtsHandoff:
    """A supported hosted-ATS posting found behind another portal's external apply link."""

    platform: str  # greenhouse | lever
    external_job_id: str
    url: str  # canonical posting URL the ATS adapter can look up (board in the path)
    board: str | None
    board_guessed: bool = False


_GH_ID = re.compile(r"^\d{1,20}$")
_LEVER_ID = re.compile(r"^[0-9a-f-]{8,64}$")
_GENERIC_LABELS = frozenset({"www", "careers", "career", "jobs", "job", "apply", "boards", "work", "join", "hire",
                             "hiring", "co", "com", "io", "ai", "in", "org", "net", "app", "dev", "tech"})


def _board_guess(host: str) -> str | None:
    """stripe.com -> stripe, careers.acme.io -> acme (only for ?gh_jid= custom career sites)."""
    labels = [p for p in host.lower().split(".") if p and p not in _GENERIC_LABELS]
    candidate = labels[-1] if labels else None
    return candidate if candidate and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,99}", candidate) else None


def ats_handoff_target(url: str | None) -> AtsHandoff | None:
    """Greenhouse/Lever posting behind an external apply link, deduped by its global job id.

    Supports boards.greenhouse.io / job-boards.greenhouse.io /<board>/jobs/<id>, the embed form
    (?for=<board>&token=<id>), custom career sites carrying ?gh_jid=<id> (board guessed from the
    domain, fail-closed if wrong) and jobs.lever.co/<board>/<uuid>[/apply]. https only.
    """
    if not url:
        return None
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        return None
    host = parts.hostname.lower()
    params = parse_qs(parts.query)

    def first(key: str) -> str | None:
        values = params.get(key)
        return values[0] if values else None

    segments = [s for s in parts.path.split("/") if s]
    if host in GREENHOUSE_HOSTS:
        if parts.path.startswith("/embed/job_app"):
            board, token = first("for"), first("token")
            if board and token and _GH_ID.match(token):
                return AtsHandoff("greenhouse", token, f"https://job-boards.greenhouse.io/{board}/jobs/{token}", board)
            return None
        if len(segments) >= 3 and segments[1] == "jobs" and _GH_ID.match(segments[2]):
            board = segments[0]
            return AtsHandoff("greenhouse", segments[2], f"https://job-boards.greenhouse.io/{board}/jobs/{segments[2]}",
                              board)
        return None
    if host in LEVER_HOSTS:
        if len(segments) >= 2 and _LEVER_ID.match(segments[1]):
            return AtsHandoff("lever", segments[1], f"https://{host}/{segments[0]}/{segments[1]}", segments[0])
        return None
    gh_jid = first("gh_jid")
    if gh_jid and _GH_ID.match(gh_jid):
        board = _board_guess(host)
        if board:
            return AtsHandoff("greenhouse", gh_jid, f"https://job-boards.greenhouse.io/{board}/jobs/{gh_jid}", board,
                              board_guessed=True)
    return None


def ats_form_url(url: str, ats: str) -> str:
    """Lever postings take their form at /apply; Greenhouse embeds it on the posting page."""
    if ats == "lever":
        parts = urlsplit(url)
        path = parts.path.rstrip("/")
        return f"https://{parts.hostname}{path if path.endswith('/apply') else path + '/apply'}"
    return url


def html_to_text(value: str | None, limit: int = MAX_DESCRIPTION) -> str | None:
    """Plain bounded text from (possibly entity-escaped) HTML. Never returns markup."""
    if not value:
        return None
    text = html.unescape(html.unescape(value))
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text).strip()
    return text[:limit] or None


def age_days_from(value: datetime | None, now: datetime | None = None) -> int | None:
    if value is None:
        return None
    moment = value if value.tzinfo else value.replace(tzinfo=UTC)
    return max(((now or datetime.now(UTC)) - moment).days, 0)


def role_query_match(title: str | None, query: str | None) -> bool:
    """Every meaningful query word (seniority-insensitive, engineer~developer) is in the title."""
    from backend.app.browser_v2.rules import _role_matches

    if not query or not query.strip():
        return True
    return bool(title) and _role_matches(title or "", query)


# --- shared answer resolution ---------------------------------------------------------------
async def resolve_question(question: str, options: tuple[str, ...], facts: CandidateFacts, detail: JobDetail,
                           answerer: ScreeningResolver | None, hitl_answers: dict[str, str] | None
                           ) -> tuple[str | None, str, str]:
    owner = hitl_override(question, options, hitl_answers)
    if owner is not None:
        return owner, "human_hitl", "hitl_owner_answer"
    if answerer is None:
        answer = resolve_answer(question, options, facts)
        return answer, "profile" if answer is not None else "human", "deterministic_only"
    resolved = await answerer.resolve(question, options, facts, {
        "title": detail.listing.title, "company": detail.listing.company})
    return resolved.answer, resolved.source, resolved.reason


NoteComposer = Callable[[JobDetail, CandidateFacts], Awaitable[str | None]]
COVER_NOTE = re.compile(
    r"cover letter|cover note|why should (?:we|you) (?:be )?hire|why (?:are you|do you want)|"
    r"\b(?:write|add|send|include)?\s*(?:a |an )?(?:short |brief )?(?:note|message) to\b|"
    r"introduce yourself|short (?:note|intro)|tell (?:us|the team) (?:about yourself|why)|add a note|"
    r"what interests you", re.IGNORECASE)


def deterministic_intro(detail: JobDetail, facts: CandidateFacts) -> str | None:
    """Template intro from verified facts only (no invented employers, dates or numbers)."""
    skills = [s for s in facts.skills][:5]
    if not skills and facts.experience_years is None:
        return None
    role = detail.listing.title or "this role"
    company = detail.listing.company or "your team"
    parts = [f"Hi {company} team, I'm interested in the {role} position."]
    if facts.experience_years is not None:
        years = int(facts.experience_years) if float(facts.experience_years).is_integer() \
            else facts.experience_years
        parts.append(f"I have {years} year{'s' if facts.experience_years != 1 else ''} of experience")
        parts[-1] += f" working with {', '.join(skills)}." if skills else "."
    elif skills:
        parts.append(f"I work with {', '.join(skills)}.")
    parts.append("I'd be glad to share more details about my work and how I can contribute.")
    return " ".join(parts)


# --- hosted form scanning + filling ---------------------------------------------------------
SCAN_JS = r"""
({root, maxFields}) => {
  const scope = root ? document.querySelector(root) : document;
  if (!scope) return {fields: [], missingRoot: true};
  document.querySelectorAll("[data-aa-field]").forEach(e => e.removeAttribute("data-aa-field"));
  const visible = (el) => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const clip = (s) => (s || "").replace(/\s+/g, " ").trim().slice(0, 300);
  const wrapLabel = (el) => {
    const wrap = el.closest(".field, .application-question, .application-field, .form-group, fieldset, li, [class*='question'], [class*='field']");
    if (!wrap) return "";
    const l = wrap.querySelector("label, legend, .application-label, [class*='label']");
    return l ? clip(l.innerText) : "";
  };
  const labelText = (el) => {
    if (el.labels && el.labels.length) return clip([...el.labels].map(l => l.innerText).join(" "));
    const by = el.getAttribute("aria-labelledby");
    if (by) {
      const t = by.split(/\s+/).map(id => document.getElementById(id)?.innerText || "").join(" ");
      if (t.trim()) return clip(t);
    }
    const aria = el.getAttribute("aria-label");
    if (aria) return clip(aria);
    return wrapLabel(el) || clip(el.getAttribute("placeholder") || el.name || el.id || "");
  };
  const fields = [];
  const seen = new Set();
  let i = 0;
  for (const el of scope.querySelectorAll("input, select, textarea")) {
    if (fields.length >= maxFields) break;
    const type = el.tagName === "SELECT" ? "select" : el.tagName === "TEXTAREA" ? "textarea"
      : (el.getAttribute("role") === "combobox" ? "combobox" : (el.type || "text").toLowerCase());
    if (["hidden", "submit", "button", "image", "reset", "search"].includes(type)) continue;
    if (type !== "file" && !visible(el) && !(["radio", "checkbox"].includes(type) && el.labels && [...el.labels].some(visible))) continue;
    if (el.disabled || el.readOnly) continue;
    if (type === "radio" || type === "checkbox") {
      const key = type + ":" + (el.name || ("#" + i));
      if (seen.has(key)) continue;
      seen.add(key);
      const group = el.name ? [...scope.querySelectorAll(`input[type=${type}][name="${CSS.escape(el.name)}"]`)] : [el];
      const fs = el.closest("fieldset");
      const legend = fs && fs.querySelector("legend");
      const label = clip(legend ? legend.innerText : (group.length > 1 ? (wrapLabel(el) || el.name) : labelText(el)));
      const options = group.map(r => {
        const idx = i++;
        r.setAttribute("data-aa-field", String(idx));
        return {idx, label: clip(r.labels && r.labels.length ? [...r.labels].map(l => l.innerText).join(" ") : r.value),
                checked: r.checked};
      });
      fields.push({kind: type, label, name: el.name || null, required: group.some(r => r.required || r.getAttribute("aria-required") === "true") || /\*\s*$/.test(label),
                   options, value_present: group.some(r => r.checked), single: group.length === 1});
      continue;
    }
    const idx = i++;
    el.setAttribute("data-aa-field", String(idx));
    const label = labelText(el);
    fields.push({idx, kind: type, label, name: el.name || el.id || null,
      required: !!(el.required || el.getAttribute("aria-required") === "true" || /\*\s*$/.test(label)),
      options: el.tagName === "SELECT" ? [...el.options].filter(o => o.value !== "" && !/^\s*(select|choose|--)/i.test(o.text)).map(o => clip(o.text)) : null,
      value_present: el.tagName === "SELECT" ? (el.selectedIndex > 0 && el.value !== "") : !!(el.value && String(el.value).trim()),
      autocomplete: el.getAttribute("autocomplete") || null, accept: el.getAttribute("accept") || null});
  }
  return {fields, missingRoot: false};
}
"""

FORM_STATE_JS = r"""
({root, submitRe, confirmRe}) => {
""" + CHALLENGE_HELPERS_JS + r"""
  const visible = (el) => !!el && el.isConnected && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const text = (el) => (el && el.innerText || "").replace(/\s+/g, " ").trim();
  const body = (document.body && document.body.innerText || "").slice(0, 20000);
  const scope = (root && document.querySelector(root)) || document;
  const errors = [...scope.querySelectorAll("[aria-invalid='true'], .field-error, .error-message, [class*='error']:not(form):not(body)")]
    .filter(visible).map(text).filter(t => t && t.length < 200).slice(0, 5);
  const sub = new RegExp(submitRe, "i");
  const submits = [...scope.querySelectorAll("button, input[type=submit], [role=button]")].filter(visible)
    .filter(b => sub.test((text(b) || b.value || "").trim())).length;
  return {url: location.href, body, errors, submits,
          confirmed: new RegExp(confirmRe, "i").test(body),
          challenge: challengeNodes() || challengeTitle() || /verify (?:that )?you are (?:a )?human|unusual traffic|press and hold/i.test(body)};
}
"""

IDENTITY_FIELDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("first_name", re.compile(r"^(?:legal\s+|preferred\s+)?first\s*name$|^given\s+name$", re.IGNORECASE)),
    ("last_name", re.compile(r"^(?:legal\s+)?last\s*name$|^surname$|^family\s+name$", re.IGNORECASE)),
    ("full_name", re.compile(r"^(?:your\s+)?(?:full\s+|legal\s+)?name$", re.IGNORECASE)),
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
        return tuple(dict.fromkeys(" ".join(t.split()) for t in texts if t.strip()))[:50]

    async def _apply_answer(self, page: Any, item: dict[str, Any], answer: str) -> bool:
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
                await locator.check(force=True)
            else:
                await locator.check(force=True)
            return True
        locator = page.locator(f'[data-aa-field="{item["idx"]}"]')
        if kind == "select":
            await locator.select_option(label=answer)
            return True
        if kind == "combobox":
            await locator.click()
            await locator.fill(answer)
            await page.wait_for_timeout(self.settle_ms)
            listbox = (await locator.get_attribute("aria-controls") or await locator.get_attribute("aria-owns")
                       or "").split(" ")[0]
            scope = page.locator(f'[id="{listbox}"]') if listbox else page
            option = scope.locator("[role=option]").filter(
                has_text=re.compile(r"^\s*" + re.escape(answer) + r"\s*$")).filter(visible=True)
            if await option.count():
                await option.first.click()
            else:
                await locator.press("Enter")
            return True
        await locator.fill(answer)
        return True


OPTIONS_JS = r"""
({field, scoped}) => {
  const visible = (el) => !!el && el.isConnected && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const text = (el) => (el && el.innerText || "").replace(/\s+/g, " ").trim();
  if (scoped) {
    const box = document.querySelector(field);
    const ids = ((box && (box.getAttribute("aria-controls") || box.getAttribute("aria-owns"))) || "").split(/\s+/).filter(Boolean);
    const lists = ids.map(id => document.getElementById(id)).filter(Boolean);
    if (!lists.length) return null;  // no ARIA link: caller diffs visible options before/after opening
    return lists.flatMap(l => [...l.querySelectorAll("[role=option]")].filter(visible).map(text));
  }
  return [...document.querySelectorAll("[role=option]")].filter(visible).map(text);
}
"""


# --- confirmation + submit helpers ----------------------------------------------------------
CONFIRM_TEXT = (r"thank(?:s| you) for (?:your )?appl(?:ying|ication)|application (?:has been |was )?(?:submitted|received|sent)"
                r"|we(?:'ve| have) received your application|successfully (?:submitted|applied)|you(?:'ve| have) applied"
                r"|applied successfully|your application is on its way")
SUBMIT_TEXT = (r"^(?:submit(?: (?:your )?application)?|send(?: application)?|apply(?: now)?|"
               r"submit & apply|finish|complete(?: application)?|confirm(?: application)?)$")
NEXT_TEXT = r"^(?:next|continue|save (?:and|&) continue|proceed)$"


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
        if ats not in SUPPORTED_ATS:
            return ApplyResult(S.FILTERED_OUT, f"external_unsupported_ats:{urlsplit(url).hostname or 'unknown'}",
                               dry_run)
        if navigate:
            await self.open_form(page, url, ats)
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
        submits = await visible_buttons(page, None, SUBMIT_TEXT)
        if len(submits) != 1:
            return ApplyResult(S.FAILED, f"ats_submit_control_{len(submits)}", dry_run, answers=answers)
        planned = (f"submit {ats} application for {job_id} ({detail.listing.title} @ {detail.listing.company})"
                   + (f"; upload {', '.join(outcome.planned_uploads)}" if outcome.planned_uploads else ""))
        if dry_run:
            shot = await self.shot(page, platform, job_id, "dry-run")
            return ApplyResult(S.SCORED, "dry_run_stopped_before_submit", True, planned_action=planned,
                               screenshot=shot, answers=answers)
        start_url = str(page.url)
        await submits[0].click()
        state = await poll_state(page, None, lambda st: bool(
            confirmation_source(st, start_url) or st.get("errors") or st.get("challenge")), self.confirm_timeout_s)
        source = confirmation_source(state, start_url)
        shot = await self.shot(page, platform, job_id, "receipt" if source else "after-submit")
        if source is not None:
            receipt = {"source": source, "url": state.get("url"), "ats": ats, "screenshot": shot,
                       "verified_at": datetime.now(UTC).isoformat(), "answers": list(answers),
                       "resume": outcome.resume}
            return ApplyResult(S.APPLIED, "confirmed", False, clicked_apply=True, receipt=receipt, screenshot=shot,
                               answers=answers)
        if state.get("errors") and state.get("submits") == 1 and not state.get("challenge"):
            # The form rejected the submission (still on the form with validation errors).
            return ApplyResult(S.WAITING_FOR_USER, "ats_validation_errors", False, clicked_apply=True,
                               answers=answers, screenshot=shot,
                               question=HitlQuestion(kind="ERROR", prompt="Form rejected: " + "; ".join(
                                   state.get("errors") or [])[:300], context={"url": url, "platform": platform}))
        return ApplyResult(S.SUBMISSION_UNKNOWN, "confirmation_ambiguous", False, clicked_apply=True,
                           answers=answers, screenshot=shot)


# --- config-driven interactive portal adapter -------------------------------------------------
PROBE_JS = r"""
({loggedIn, loginForm}) => {
""" + CHALLENGE_HELPERS_JS + r"""
  const visible = (el) => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const body = (document.body && document.body.innerText || "").slice(0, 20000);
  const any = (sel) => { try { return [...document.querySelectorAll(sel)].some(visible); } catch (e) { return false; } };
  return {
    url: location.href,
    challenge: challengeText(body) || challengeNodes(),
    otp: any('input[autocomplete="one-time-code"],input[name*="otp" i],input[id*="otp" i]'),
    loginForm: any(loginForm),
    loggedIn: any(loggedIn),
  };
}
"""

# Hiring badges rendered inside company-name elements (live internshala: "UV Farms Active").
COMPANY_BADGE = re.compile(r"\s+(?:actively hiring|active|hiring|verified)$", re.IGNORECASE)
CARDS_JS = r"""
({pattern, limit, hosts}) => {
  const text = (el) => (el && el.innerText || "").replace(/\s+/g, " ").trim();
  const re = new RegExp(pattern);
  const out = [], seen = new Set();
  const postingIds = (el) => {
    const ids = new Set();
    for (const x of el.querySelectorAll("a[href]")) {
      try { const v = new URL(x.href, location.href); const mm = hosts.includes(v.hostname) && v.pathname.match(re);
            if (mm) ids.add(mm[1]); } catch (e) { /* ignore */ }
      if (ids.size > 1) break;
    }
    return ids.size;
  };
  for (const a of document.querySelectorAll("a[href]")) {
    let u; try { u = new URL(a.href, location.href); } catch (e) { continue; }
    if (!hosts.includes(u.hostname)) continue;
    const m = u.pathname.match(re);
    if (!m || seen.has(m[1])) continue;
    seen.add(m[1]);
    // Live 2026-11-26: class-name heuristics picked the anchor itself (internshala a.job-title-href) or a
    // bare row (wellfound), losing company/age. The card is the LARGEST ancestor holding only this posting.
    let card = a;
    for (let i = 0; i < 10 && card.parentElement && card.parentElement !== document.body
         && postingIds(card.parentElement) <= 1; i++) card = card.parentElement;
    const ACTION = /^(?:view job|apply(?: now)?|save|share|follow|change status.*|report|see all .*jobs.*)$/i;
    const pick = (sel) => { if (!card) return null; for (const el of card.querySelectorAll(sel)) {
        const t = text(el); if (t && t.length <= 120 && !ACTION.test(t)) return t; } return null; };
    const ctext = text(card).slice(0, 1500);
    // Company blocks listing several roles (wellfound): use the group's single company link.
    const groupCompany = () => {
      let group = card.parentElement;
      for (let i = 0; i < 6 && group && group !== document.body; i++, group = group.parentElement) {
        const names = new Set([...group.querySelectorAll("a[href*='/company/'], a[href*='/companies/']")]
          .map(text).filter(t => t && t.length < 120));
        if (names.size === 1) return [...names][0];
        if (names.size > 1) return null;  // reached a list of several companies: never guess
      }
      return null;
    };
    const posted = (ctext.match(/(?:posted\s*:?\s*)?(?:just now|today|yesterday|few hours ago|\d+\+?\s*(?:minute|hour|day|week|month)s?\s+ago)/i) || [null])[0];
    const applicants = (ctext.match(/(?:less than\s+)?\d[\d,]*\+?\s+applicants?/i) || [null])[0];
    const heading = pick("h2, h3, h4, [class*='title' i]");
    out.push({id: m[1], url: u.origin + u.pathname, title: (a.getAttribute("title") || text(a) || heading || "").slice(0, 200) || null,
              company: pick(".company-name, .company_name, [class*='company-name' i], [class*='company_name' i], "
                            + "a[href*='/company/'], [class*='employer' i], p[class*='company' i], [class*='company' i]:not(div:has(a[href]))")
                       || groupCompany(), posted, applicants});
    const last = out[out.length - 1];
    if (last.company) last.company = last.company.slice(0, 120);  // never a whole card's text
    if (out.length >= limit) break;
  }
  return out;
}
"""

DETAIL_JS = r"""
({applyRe, appliedRe, externalRe, applySel, companySel, hintRe}) => {
  const visible = (el) => !!el && el.isConnected && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const text = (el) => (el && el.innerText || "").replace(/\s+/g, " ").trim();
  const body = (document.body && document.body.innerText || "").slice(0, 30000);
  // Phase 8: the portal's primary selector only counts elements that also read as Apply.
  const primary = applySel ? [...document.querySelectorAll(applySel)].filter(el => visible(el) && !el.disabled &&
    new RegExp(applyRe, "i").test(((el.innerText || "").replace(/\s+/g, " ").trim() || el.value || "").trim())) : [];
  const pick = (sel) => { const el = [...document.querySelectorAll(sel)].find(visible); return el ? text(el) : null; };
  const desc = [...document.querySelectorAll("[class*='description' i], [class*='job-desc' i], [class*='jobDescription' i], [class*='about' i], [class*='details' i], article, main")]
    .filter(visible).map(text).sort((a, b) => b.length - a.length)[0] || "";
  // Live 2026-11-26 (wellfound): the logged-in NAV has an "Applied" link - navigation/header/menu
  // controls are never apply/applied evidence for the job on the page.
  const chrome = "nav, header, [role=navigation], [role=menu], [role=menubar], [role=banner], aside";
  const controls = [...document.querySelectorAll("button, a, [role=button], input[type=submit]")]
    .filter(b => visible(b) && !b.closest(chrome));
  const label = (b) => (text(b) || b.value || "").trim();
  const ACTION = /^(?:view job|apply(?: now)?|save|share|follow|change status.*|report|interested|not interested|see all .*jobs.*)$/i;
  const shortText = (sel) => { if (!sel) return null; for (const el of document.querySelectorAll(sel)) {
      if (!visible(el) || el.closest(chrome)) continue; const t = text(el);
      if (t && t.length >= 2 && t.length <= 80 && !ACTION.test(t)) return t; } return null; };
  const apply = new RegExp(applyRe, "i"), applied = new RegExp(appliedRe, "i"), external = new RegExp(externalRe, "i");
  // Phase 8: duplicate CTAs that trigger the SAME action (same ng-click/onclick/href/form) are one
  // control (live instahyre: header + sticky footer "Apply"); different actions stay ambiguous.
  const actionKey = (b) => [label(b).toLowerCase(), b.getAttribute("ng-click") || b.getAttribute("onclick") ||
    b.getAttribute("data-action") || (b.href ? new URL(b.href, location.href).href : "") ||
    (b.form ? (b.form.getAttribute("action") || b.form.id || "form") : "")].join("|");
  // Live 2026-11-26 (instahyre): <a>Apply now</a> wraps <button ng-click=submitChoice(..)>Apply now</button>:
  // one click target, so nested matches collapse to the innermost control.
  const innermost = (list) => list.filter(b => !list.some(o => o !== b && b.contains(o)));
  const applyControls = innermost(primary.length ? primary : controls.filter(b => apply.test(label(b)) && !b.disabled));
  const applyActions = new Set(applyControls.map(actionKey)).size;
  const sameAction = applyControls.length > 1 && applyActions === 1 && !actionKey(applyControls[0]).endsWith("|");
  // Phase 8: posting date from the job page when the card had none (JSON-LD JobPosting.datePosted,
  // <time datetime>, article:published_time).
  let datePosted = null;
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const d = JSON.parse(s.textContent);
      for (const it of (Array.isArray(d) ? d : (d["@graph"] || [d]))) {
        if ([].concat(it["@type"] || []).some(t => String(t).includes("JobPosting")) && it.datePosted) datePosted = String(it.datePosted);
      }
    } catch (e) { /* ignore */ }
  }
  if (!datePosted) {
    const meta = document.querySelector('meta[property="article:published_time"],meta[itemprop="datePosted"]');
    const t = [...document.querySelectorAll("main time[datetime], article time[datetime], [class*='posted' i] time[datetime]")]
      .find(el => !el.closest(chrome));
    datePosted = (meta && meta.getAttribute("content")) || (t && t.getAttribute("datetime")) || null;
  }
  return {
    url: location.href,
    title: pick("h1") || pick("h2"),
    company: shortText(companySel) || shortText("[class*='company' i] a, [class*='company-name' i], [class*='companyName' i], [class*='company' i], [class*='employer' i], [class*='startup' i] a"),
    description: desc.slice(0, 8000) || null,
    posted: (body.match(/(?:posted\s*(?:on)?\s*:?\s*)?(?:just now|today|yesterday|few hours ago|\d+\+?\s*(?:minute|hour|day|week|month)s?\s+ago|\d{4}-\d{2}-\d{2})/i) || [null])[0],
    applicants: (body.match(/(?:less than\s+)?\d[\d,]*\+?\s+applicants?/i) || [null])[0],
    salary: (body.match(/(?:₹|rs\.?|inr|\$|usd)\s?[\d,.]+\s*(?:k|l|lpa|lakhs?|lacs?)?(?:\s*(?:-|–|to)\s*(?:₹|rs\.?|inr|\$|usd)?\s?[\d,.]+\s*(?:k|l|lpa|lakhs?|lacs?)?)?(?:\s*(?:\/|per)\s*(?:year|annum|month|yr|mo))?/i) || [null])[0],
    location: pick("[class*='location' i]"),
    workMode: (body.match(/\b(remote|hybrid|work from home|on-?site|in office)\b/i) || [null])[0],
    // Live 2026-11-26 (internshala): "150+ candidates have already applied" is NOT our application.
    // Body text counts only in the first person, and never while an enabled Apply control is shown.
    applied: controls.some(b => applied.test(label(b))) || (!applyControls.length &&
      /\byou(?:'ve| have)(?: already)? applied\b|\byou already applied\b|\balready applied to this\b/i.test(body)),
    // A portal-declared primary Apply control wins over duplicate CTAs of the same flow (live internshala: 4).
    applyButtons: sameAction ? 1 : applyControls.length,
    externalLinks: controls.filter(b => external.test(label(b))).map(b => b.href || null).filter(Boolean).slice(0, 3),
    datePosted,
    closed: /no longer (?:accepting applications|available|active|open)|this (?:job|role|position|opening) (?:has been|is|was) (?:closed|filled|removed)|(?:job|position|role) (?:is )?(?:closed|expired|filled)|applications? (?:are |is )?(?:now )?closed|not accepting applications/i.test(body),
    loginToApply: /(?:log ?in|sign ?in|sign up|create an account|register) (?:to|before you) apply/i.test(body),
    unsupportedApply: !!hintRe && controls.some(b => new RegExp(hintRe, "i").test(label(b))),
  };
}
"""

# Phase 8: the click path marks the control DETAIL_JS counted (same chrome exclusion, same
# primary selector, same "same action" dedup), so a nav/sticky copy can never make it "changed".
MARK_APPLY_JS = r"""
({applyRe, appliedRe, applySel}) => {
  const visible = (el) => !!el && el.isConnected && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  const text = (el) => (el && el.innerText || "").replace(/\s+/g, " ").trim();
  for (const old of document.querySelectorAll("[data-aa-apply]")) old.removeAttribute("data-aa-apply");
  const chrome = "nav, header, [role=navigation], [role=menu], [role=menubar], [role=banner], aside";
  const label = (b) => (text(b) || b.value || "").trim();
  const apply = new RegExp(applyRe, "i"), applied = new RegExp(appliedRe, "i");
  const primary = applySel ? [...document.querySelectorAll(applySel)]
    .filter(el => visible(el) && !el.disabled && apply.test(label(el))) : [];
  const controls = [...document.querySelectorAll("button, a, [role=button], input[type=submit]")]
    .filter(b => visible(b) && !b.closest(chrome));
  const actionKey = (b) => [label(b).toLowerCase(), b.getAttribute("ng-click") || b.getAttribute("onclick") ||
    b.getAttribute("data-action") || (b.href ? new URL(b.href, location.href).href : "") ||
    (b.form ? (b.form.getAttribute("action") || b.form.id || "form") : "")].join("|");
  const matches = primary.length ? primary : controls.filter(b => apply.test(label(b)) && !b.disabled);
  const found = matches.filter(b => !matches.some(o => o !== b && b.contains(o)));
  const actions = new Set(found.map(actionKey)).size;
  const same = found.length > 1 && actions === 1 && !actionKey(found[0]).endsWith("|");
  if (found.length === 1 || same) found[0].setAttribute("data-aa-apply", "1");
  return {count: same ? 1 : found.length, applied: controls.some(b => applied.test(label(b)))};
}
"""

DIALOG_JS = r"""
(selectors) => {
  const visible = (el) => !!el && el.isConnected && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== "hidden";
  for (const sel of selectors) {
    const el = [...document.querySelectorAll(sel)].filter(visible).pop();
    if (el && el.querySelector("input, textarea, select, button")) {
      if (!el.id) el.id = "aa-dialog-" + Math.random().toString(36).slice(2, 8);
      return "#" + CSS.escape(el.id);
    }
  }
  return null;
}
"""


@dataclass(frozen=True)
class PortalConfig:
    platform: str
    label: str
    hosts: tuple[str, ...]
    home_url: str
    job_path: str  # JS regex source; group 1 = stable job id
    logged_in: str  # CSS selector list proving an authenticated session
    login_form: str = 'input[type=password], form[action*="login" i], [class*="login-form" i]'
    login_paths: tuple[str, ...] = ("/login", "/signin", "/sign_in", "/users/sign_in", "/nlogin", "/auth")
    login_hosts: tuple[str, ...] = ()
    apply_text: str = r"^(?:apply|apply now|easy apply|quick apply|1-click apply|i'?m interested|interested)$"
    applied_text: str = r"^(?:applied|already applied|application sent)$"
    external_text: str = r"apply on company (?:site|website)|apply externally|company website"
    confirm_text: str = CONFIRM_TEXT
    limit_text: str = (r"(?:daily|today'?s?)\s+(?:apply|application)s?\s+(?:limit|quota)|reached\s+(?:the|your)\s+"
                       r"(?:daily\s+|maximum\s+)?(?:apply\s+|application\s+)?limit|apply\s+limit\s+(?:reached|exceeded)|"
                       r"you can(?:not|'t) apply to (?:more|any more)")
    dialog_selectors: tuple[str, ...] = ("[role=dialog]", "[aria-modal=true]", ".modal.show", ".modal.in",
                                         "[class*='modal' i]", "[class*='Modal']", "[class*='drawer' i]")
    # Keep True: a dry-run then never clicks Apply, so it can never cause an unrecorded
    # submission. (False would let dry-runs open the form; only for portals where Apply
    # provably cannot submit.)
    apply_click_may_submit: bool = True
    # True when Apply navigates to a full-page application form (no modal), e.g. Internshala.
    form_page_after_apply: bool = False
    # Live 2026-11-26: the single primary Apply control when a page repeats equivalent CTAs, and the
    # precise company element when a generic [class*=company] container also holds the title.
    apply_selector: str | None = None
    company_selector: str | None = None
    # CSS that proves search results have rendered (logged-in SPAs hydrate after DOMContentLoaded).
    results_selector: str | None = None
    # Phase 8: a control that is the portal's apply UI but not yet calibrated for automation
    # (live YC 2026-11-26: "Change status to apply" status menu) -> apply_control_unsupported_ui.
    unsupported_apply_text: str | None = None


class InteractivePortalAdapter:
    """Persistent-Brave portal adapter driven by a `PortalConfig` (one worker tab)."""

    config: PortalConfig

    def __init__(self, *, answerer: ScreeningResolver | None = None, composer: NoteComposer | None = None,
                 settle_ms: int = 1500, refresh_wait_ms: int = 3000, jitter: tuple[float, float] = (0.8, 2.2),
                 receipts_root: Path | None = None, confirm_timeout_s: float = 12.0) -> None:
        self.settle_ms = settle_ms
        self.refresh_wait_ms = refresh_wait_ms
        self.jitter = jitter
        self.receipts_root = receipts_root
        self.confirm_timeout_s = confirm_timeout_s
        self.composer = composer
        self.last_discovery_blocked: str | None = None
        self._answerer = answerer
        self.filler = HostedFormFiller(answerer=answerer, composer=composer, jitter=(0, 0) if jitter[1] == 0
                                       else (0.2, 0.6))

    @property
    def platform(self) -> str:
        return self.config.platform

    # The service rebinds `answerer` when the AI runtime is available.
    @property
    def answerer(self) -> ScreeningResolver | None:
        return self._answerer

    @answerer.setter
    def answerer(self, value: ScreeningResolver | None) -> None:
        self._answerer = value
        self.filler.answerer = value

    # --- navigation helpers ------------------------------------------------------------
    async def _goto(self, page: Any, url: str) -> None:
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(self.settle_ms)

    async def _pause(self) -> None:
        if self.jitter[1] > 0:
            await asyncio.sleep(random.uniform(*self.jitter))

    async def _wait_for_results(self, page: Any, timeout_ms: int = 12_000) -> None:
        """Live 2026-11-26: logged-in SPAs (YC, Naukri) render job links well after DOMContentLoaded."""
        try:
            await page.wait_for_function(
                "([pattern, hosts, sel]) => (sel && document.querySelector(sel)) || [...document.querySelectorAll('a[href]')]"
                ".some(a => { try { const u = new URL(a.href, location.href); return hosts.includes(u.hostname) && "
                "new RegExp(pattern).test(u.pathname); } catch (e) { return false; } }) || "
                "/no (?:jobs|results|matching)/i.test(document.body ? document.body.innerText : '')",
                arg=[self.config.job_path, list(self.config.hosts), self.config.results_selector],
                timeout=timeout_ms)
        except Exception:  # noqa: BLE001 - timeout: parse whatever rendered (possibly none)
            return

    async def _probe(self, page: Any) -> dict[str, Any]:
        return await page.evaluate(PROBE_JS, {"loggedIn": self.config.logged_in, "loginForm": self.config.login_form})

    def classify_auth(self, probe: dict[str, Any]) -> str:
        parts = urlsplit(str(probe.get("url", "")))
        path, host = parts.path.lower(), (parts.hostname or "").lower()
        if probe.get("challenge"):
            return "challenge"
        if probe.get("otp"):
            return "otp"
        if probe.get("loggedIn") and host in self.config.hosts:
            return "ok"
        if host in self.config.login_hosts or any(path.startswith(p) for p in self.config.login_paths) \
                or probe.get("loginForm"):
            return "login"
        return "unknown"

    async def _wait_for_auth_markers(self, page: Any, timeout_ms: int = 12_000) -> None:
        """Cold SPA loads render the logged-in nav late (live: YC/Naukri flipped OK <-> UNKNOWN)."""
        try:
            await page.wait_for_function(
                "([a, b]) => { try { return !!(document.querySelector(a) || document.querySelector(b)); }"
                " catch (e) { return true; } }", arg=[self.config.logged_in, self.config.login_form],
                timeout=timeout_ms)
        except Exception:  # noqa: BLE001, S110 - classify whatever rendered
            pass

    async def check_session(self, page: Any) -> SessionCheck:
        await self._goto(page, self.config.home_url)
        await self._wait_for_auth_markers(page)
        first = self.classify_auth(await self._probe(page))
        if first == "ok":
            return SessionCheck(AuthStatus.OK)
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_timeout(self.refresh_wait_ms)
        await self._goto(page, self.config.home_url)
        await self._wait_for_auth_markers(page)
        second = self.classify_auth(await self._probe(page))
        details = {"first": first, "second": second}
        if second == "ok":
            return SessionCheck(AuthStatus.OK, refreshed=True, details=details)
        if second in {"login", "otp", "challenge"}:
            return SessionCheck(AuthStatus.AUTH_REQUIRED, refreshed=True, reason=second, details=details)
        return SessionCheck(AuthStatus.UNKNOWN, refreshed=True, reason="logged_in_indicator_missing", details=details)

    # --- discovery ----------------------------------------------------------------------
    def search_url(self, query: str, job_age_days: int | None = None) -> str:
        raise NotImplementedError

    async def discover_jobs(self, page: Any, *, query: str, limit: int = 20,
                            job_age_days: int | None = None) -> list[JobListing]:
        await self._goto(page, self.search_url(query, job_age_days))
        await self._wait_for_results(page)
        if (await self._probe(page)).get("challenge"):
            # Live 2026-11-26 (hiringcafe.com behind Cloudflare): never parse cards off an interstitial;
            # the next session check isolates the portal (AUTH_REQUIRED/challenge).
            self.last_discovery_blocked = "challenge"
            return []
        self.last_discovery_blocked = None
        items = await page.evaluate(CARDS_JS, {"pattern": self.config.job_path, "limit": max(1, min(limit, 50)),
                                               "hosts": list(self.config.hosts)})
        listings = []
        for item in items:
            posted = item.get("posted")
            company = COMPANY_BADGE.sub("", item.get("company") or "").strip() or None
            listings.append(JobListing(
                platform=self.platform, external_job_id=str(item["id"]), url=item["url"],
                title=item.get("title"), company=company, posted_text=posted,
                posted_age_days=parse_posted_age_days(posted), age_is_lower_bound=bool(posted and "+" in posted),
                applicants=parse_applicants(item.get("applicants")) if item.get("applicants") else None))
        return listings

    # --- inspection ---------------------------------------------------------------------
    def _detail_args(self) -> dict[str, Any]:
        return {"applyRe": self.config.apply_text, "appliedRe": self.config.applied_text,
                "externalRe": self.config.external_text, "applySel": self.config.apply_selector,
                "companySel": self.config.company_selector, "hintRe": self.config.unsupported_apply_text}

    async def resolve_apply_control(self, page: Any, polls: int = 12) -> dict[str, Any]:
        """Same counting as inspection; waits (<= ~3 s) for two identical reads (SPA hydration)."""
        args = {"applyRe": self.config.apply_text, "appliedRe": self.config.applied_text,
                "applySel": self.config.apply_selector}
        previous: int | None = None
        state: dict[str, Any] = {}
        for attempt in range(max(1, polls)):
            state = await page.evaluate(MARK_APPLY_JS, args)
            if state.get("applied") or (state.get("count") == 1 and previous == 1):
                return state
            previous = state.get("count")
            if attempt + 1 < polls:
                await page.wait_for_timeout(250)
        return state

    async def _primary_apply(self, page: Any) -> list[Any]:
        if not self.config.apply_selector:
            return []
        locator = page.locator(self.config.apply_selector)
        found = []
        for index in range(min(await locator.count(), 5)):
            item = locator.nth(index)
            try:
                if await item.is_visible() and await item.is_enabled():
                    found.append(item)
            except Exception:  # noqa: BLE001, S112
                continue
        return found

    async def _wait_for_job_page(self, page: Any, timeout_ms: int = 12_000) -> None:
        """Logged-in SPAs render the job title after DOMContentLoaded (live canary 2026-11-27):
        wait for a non-empty h1, an apply/applied control, or a login/challenge page."""
        try:
            await page.wait_for_function(
                "([applyRe]) => { const h = document.querySelector('h1'); if (h && h.innerText.trim()) return true;"
                " const re = new RegExp(applyRe, 'i'); return [...document.querySelectorAll('button, a')]"
                ".some(b => re.test((b.innerText || '').trim())) || /login|signin|sign_in/i.test(location.pathname); }",
                arg=[self.config.apply_text], timeout=timeout_ms)
        except Exception:  # noqa: BLE001 - timeout: parse whatever rendered; filters fail closed
            return

    async def inspect_job(self, page: Any, listing: JobListing) -> JobDetail:
        await self._goto(page, listing.url)
        await self._wait_for_job_page(page)
        auth = self.classify_auth(await self._probe(page))
        data = await page.evaluate(DETAIL_JS, self._detail_args())
        applicants = parse_applicants(data.get("applicants")) if data.get("applicants") else (
            listing.applicants or UNKNOWN_APPLICANTS)
        # Card age first (calibrated per portal), then the job page: visible "posted ..." text,
        # then structured data (JSON-LD datePosted / <time datetime>) - Phase 8 unknown-age layer 1.
        age = listing.posted_age_days
        if data.get("posted"):
            age = parse_posted_age_days(data.get("posted"))
        if age is None and data.get("datePosted"):
            age = parse_posted_age_days(str(data["datePosted"])[:10])
        external = data.get("externalLinks") or []
        if data.get("applied"):
            mode = "applied"
        elif data.get("applyButtons") == 1:
            mode = "direct"
        elif external:
            mode = "external"
        elif data.get("applyButtons"):
            mode = "ambiguous"
        elif data.get("unsupportedApply"):
            mode = "unsupported_ui"
        else:
            mode = "closed" if data.get("closed") else "none"
        if mode == "none" and data.get("loginToApply") and auth == "unknown":
            auth = "login"  # logged-out job page that hides Apply behind "log in to apply"
        apply_url = urljoin(listing.url, external[0]) if mode == "external" and external else None
        merged = replace(listing, title=data.get("title") or listing.title,
                         # the calibrated card value wins; detail-page text is only a fallback
                         company=listing.company or data.get("company"),
                         posted_text=data.get("posted") or listing.posted_text, posted_age_days=age,
                         applicants=applicants)
        return JobDetail(
            listing=merged, applicants=applicants, posted_age_days=age, already_applied=bool(data.get("applied")),
            apply_mode=mode, challenge=auth if auth in {"challenge", "otp", "login"} else None,
            portal_limit=await self.detect_portal_limit(page), description=data.get("description"),
            salary_text=data.get("salary"), location=data.get("location"), work_mode=data.get("workMode"),
            apply_url=apply_url, ats=classify_ats(apply_url))

    async def extract_form(self, page: Any) -> dict[str, Any]:
        return await extract_form(page)

    async def detect_portal_limit(self, page: Any) -> str | None:
        body = await page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 20000)")
        match = re.search(self.config.limit_text, body or "", re.IGNORECASE)
        return match.group(0) if match else None

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

    async def apply_job(self, page: Any, detail: JobDetail, profile: CandidateFacts | Any, *,
                        dry_run: bool = True, existing_state: str | None = None,
                        hitl_answers: dict[str, str] | None = None) -> ApplyResult:
        guard_apply(existing_state)
        facts = profile if isinstance(profile, CandidateFacts) else CandidateFacts.from_profile(profile)
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
            source = confirmation_source(state, start_url)
            if source is not None and clicked:
                return await self._receipt(page, detail, source, tuple(answers))
            if state.get("challenge"):
                return self._result(S.SUBMISSION_UNKNOWN if clicked else S.WAITING_FOR_USER,
                                    "challenge_after_apply_click", dry_run, clicked_apply=clicked,
                                    question=None if clicked else HitlQuestion(kind="CAPTCHA", prompt=f"{name} CAPTCHA"),
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
        return self._result(S.SUBMISSION_UNKNOWN, "confirmation_ambiguous", False, clicked_apply=True,
                            answers=tuple(answers), screenshot=await self.shot(page, job_id, "ambiguous"))

    async def _receipt(self, page: Any, detail: JobDetail, source: str, answers: tuple[dict[str, str], ...]
                       ) -> ApplyResult:
        shot = await self.shot(page, detail.listing.external_job_id, "receipt")
        receipt = {"source": source, "url": detail.listing.url, "screenshot": shot,
                   "verified_at": datetime.now(UTC).isoformat(), "answers": list(answers)}
        return self._result(S.APPLIED, "confirmed", False, clicked_apply=True, receipt=receipt, screenshot=shot,
                            answers=answers)


def applicants_from_text(value: str | None) -> ApplicantCount:
    return parse_applicants(value) if value else UNKNOWN_APPLICANTS


def normalized(value: str | None) -> str:
    return normalize_text(value)
