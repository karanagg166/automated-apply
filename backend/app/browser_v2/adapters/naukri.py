"""Deterministic Naukri adapter for the persistent Brave context.

DOM knowledge ported from extension/naukri-{execution,chatbot,observation}.js
and backend/app/execution/naukri_questionnaires.py. Actions use real Playwright
input (trusted events) in the single worker tab.

Naukri has no separate final Submit: clicking "Apply" either submits at once or
opens the chatbot, whose last answer submits. Dry-run therefore stops before
the Apply click.
"""

from __future__ import annotations

import asyncio
import random
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlsplit

from backend.app.browser_v2 import profile as brave_profile
from backend.app.browser_v2.adapters.base import (
    ApplyResult,
    AuthStatus,
    HitlQuestion,
    JobDetail,
    JobListing,
    SessionCheck,
)
from backend.app.browser_v2.answers import (
    CandidateFacts,
    ScreeningResolver,
    hitl_override,
    resolve_answer,
)
from backend.app.browser_v2.forms import extract_form
from backend.app.browser_v2.receipts import prune_failures
from backend.app.browser_v2.rules import parse_applicants, parse_posted_age_days
from backend.app.browser_v2.state import ApplicationState, guard_apply

ORIGIN = "https://www.naukri.com"
HOME_URL = ORIGIN + "/mnjuser/homepage"
PROFILE_URL = ORIGIN + "/mnjuser/profile"
HISTORY_URL = ORIGIN + "/myapply/historypage"
JOB_PATH = re.compile(r"^/job-listings-[a-zA-Z0-9%_-]+-(\d{10,20})/?$")
APPLY_SUCCESS = re.compile(
    r"you have successfully applied|applied successfully|successfully applied|"
    r"application (?:has been )?(?:sent|submitted) successfully", re.IGNORECASE)
PORTAL_LIMIT = re.compile(
    r"(?:daily|today'?s?)\s+(?:apply|application)s?\s+(?:limit|quota)|"
    r"reached\s+(?:the|your)\s+(?:daily\s+|maximum\s+)?(?:apply\s+|application\s+)?limit|"
    r"exceeded\s+(?:the|your)\s+(?:daily\s+)?(?:apply\s+|application\s+)?limit|"
    r"maximum\s+(?:number\s+of\s+)?applications\s+(?:for|per)\s+(?:the\s+)?day|"
    r"apply\s+limit\s+(?:reached|exceeded)", re.IGNORECASE)
HISTORY_SENT = re.compile(r"^application sent\b", re.IGNORECASE)
MAX_QUESTION_STEPS = 20
OTP_VALUE = re.compile(r"^\s*(\d{4,8})\s*$")
OtpProvider = Callable[[str, datetime], Awaitable[str | None]]


VISIBLE_JS = """const visible = (el) => !!el && el.isConnected && el.getClientRects().length > 0 &&
  getComputedStyle(el).visibility !== "hidden";
const text = (el) => (el && el.innerText || "").replace(/\\s+/g, " ").trim();"""

AUTH_PROBE_JS = "() => {" + VISIBLE_JS + r"""
  const body = (document.body && document.body.innerText || "").slice(0, 20000);
  const any = (sel) => [...document.querySelectorAll(sel)].some(visible);
  return {
    url: location.href,
    challenge: /captcha|verify (?:that )?you are human|unusual traffic|access denied|too many requests/i.test(body)
      || any('iframe[src*="captcha"],[data-sitekey]'),
    otp: any('input[autocomplete="one-time-code"],input[name*="otp" i],input[id*="otp" i]'),
    loginForm: any('input[type=password],#usernameField,form[name="login-form"],#loginForm,[class*="loginForm"]'),
    loggedIn: any('.nI-gNb-drawer__icon,.nI-gNb-icon-img,.nI-gNb-info,.nI-gNb-drawer,a[href*="/mnjuser/profile"],.view-profile-wrapper'),
  };
}"""

LISTING_JS = "({limit}) => {" + VISIBLE_JS + r"""
  const out = [], seen = new Set();
  for (const a of document.querySelectorAll('a[href*="/job-listings-"]')) {
    let u; try { u = new URL(a.href, location.origin); } catch { continue; }
    if (u.origin !== "https://www.naukri.com") continue;
    const path = u.pathname.replace(/\/$/, "");
    const m = path.match(/^\/job-listings-[a-zA-Z0-9%_-]+-(\d{10,20})$/);
    if (!m || seen.has(m[1])) continue;
    seen.add(m[1]);
    const card = a.closest('[data-job-id],.srp-jobtuple-wrapper,.cust-job-tuple,article.jobTuple,.jobTuple,article') || a.parentElement;
    const pick = (sel) => text(card && card.querySelector(sel)) || null;
    out.push({id: m[1], url: u.origin + path, title: (a.getAttribute("title") || text(a)) || null,
      company: pick('.comp-name,[class*="comp-name"],[class*="compName"]'),
      posted: pick('.job-post-day,[class*="job-post-day"],[class*="postDay"],[class*="post-day"]')});
    if (out.length >= limit) break;
  }
  return {jobs: out, empty: /no jobs found|no results found/i.test(document.body && document.body.innerText || "")};
}"""

DETAIL_JS = "() => {" + VISIBLE_JS + r"""
  const header = document.querySelector("#job_header") ||
    [...document.querySelectorAll('[class*="jd-header"],[class*="jdHeader"]')].find(h => h.querySelector("h1"));
  const spans = header ? [...header.querySelectorAll("span,p,div")].map(text).filter(t => t && t.length < 80) : [];
  const applicantRe = [/^(?:applicants?\s*:?\s*)?[\d,]+\+?(?:\s*(?:-|–|to)\s*[\d,]+)?(?:\s*applicants?)?$/i,
                       /^(?:applicants?\s*:?\s*)?(?:less than|fewer than)\s+[\d,]+(?:\s*applicants?)?$/i];
  const applicants = [...new Set(spans.filter(t => /applicants?/i.test(t) && applicantRe.some(r => r.test(t))))];
  const posted = spans.find(t => /^posted\s*:?/i.test(t)) || null;
  let datePosted = null;
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const d = JSON.parse(s.textContent);
      const items = Array.isArray(d) ? d : (d["@graph"] || [d]);
      for (const it of items) {
        if ([].concat(it["@type"] || []).some(t => String(t).includes("JobPosting")) && it.datePosted) datePosted = String(it.datePosted);
      }
    } catch (e) {}
  }
  let ldDescription = null;
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const d = JSON.parse(s.textContent);
      for (const it of (Array.isArray(d) ? d : (d["@graph"] || [d]))) {
        if ([].concat(it["@type"] || []).some(t => String(t).includes("JobPosting")) && it.description) {
          const box = document.createElement("div"); box.innerHTML = String(it.description);
          ldDescription = box.textContent;
        }
      }
    } catch (e) {}
  }
  const jd = document.querySelector('[class*="job-desc"],[class*="JDC"],[class*="dang-inner-html"]');
  const description = (text(jd) || ldDescription || "").replace(/\s+/g, " ").trim().slice(0, 8000) || null;
  const salary = spans.find(t => /(lacs?|lakhs?|lpa|₹|not disclosed|crore)/i.test(t) && t.length < 60) || null;
  const location = text(header && header.querySelector('[class*="location"],[class*="loc"]')) || null;
  const workMode = spans.find(t => /^(remote|hybrid|work from (home|office)|on-?site)/i.test(t)) || null;
  const buttons = header ? [...header.querySelectorAll("button,[role=button],a")].filter(visible) : [];
  return {
    description, salary, location, workMode,
    url: location.href,
    title: text(header && header.querySelector("h1")) || null,
    company: text(header && header.querySelector('[class*="comp-name"] > a,[class*="compName"] > a'))
      || text(header && header.querySelector('[class*="comp-name"],[class*="compName"]')) || null,
    applicants, posted, datePosted,
    applied: buttons.some(b => /^(already applied|applied)$/i.test(text(b))),
    external: buttons.some(b => /company site/i.test(text(b))) || !!document.querySelector("#company-site-button"),
    applyButtons: buttons.filter(b => b.tagName === "BUTTON" && /^apply$/i.test(text(b)) && !b.disabled).length,
  };
}"""

PAGE_STATE_JS = "() => {" + VISIBLE_JS + r"""
  const drawer = [...document.querySelectorAll(".chatbot_DrawerContentWrapper")].find(visible);
  const header = document.querySelector('#job_header,[class*="jd-header"],[class*="jdHeader"]');
  const msgs = drawer ? [...drawer.querySelectorAll(".chatbot_MessageContainer .botItem .botMsg")].filter(visible) : [];
  return {
    url: location.href,
    body: (document.body && document.body.innerText || "").slice(0, 20000),
    drawer: !!drawer,
    question: msgs.length ? text(msgs[msgs.length - 1]).slice(0, 2000) : null,
    chips: drawer ? [...drawer.querySelectorAll(".chipsContainer .chatbot_Chip")].filter(visible).map(text)
      .filter(t => !/^skip this question$/i.test(t)) : [],
    radios: drawer ? [...drawer.querySelectorAll('input.ssrc__radio[type="radio"]')].map(r => String(r.value || "").trim()) : [],
    textInput: !!(drawer && [...drawer.querySelectorAll('.textArea[contenteditable="true"]')].find(visible)),
    fileInput: !!(drawer && drawer.querySelector('input.chatbot_Uploader[type="file"]')),
    headerApplied: !!header && [...header.querySelectorAll("button,[role=button]")].some(b => /^(applied|already applied)$/i.test(text(b))),
  };
}"""

HISTORY_JS = "({title, company}) => {" + VISIBLE_JS + r"""
  const norm = (s) => (s || "").toLowerCase().replace(/\s+/g, " ").trim();
  const rows = [...document.querySelectorAll(".jdTuplesContainer .jdTupleContainer")].map(card => ({
    title: text(card.querySelector(".jdTitle")), company: text(card.querySelector(".subheading .company")),
    status: text(card.querySelector("section.apply-status .title")),
  }));
  return rows.filter(r => norm(r.title) === norm(title) && norm(r.company) === norm(company));
}"""


OTP_STATE_JS = "() => {" + VISIBLE_JS + r"""
  const boxes = [...document.querySelectorAll('input[autocomplete="one-time-code"],input[name*="otp" i],input[id*="otp" i],input[class*="otp" i]')].filter(visible);
  const verify = [...document.querySelectorAll("button,[role=button],input[type=submit]")].filter(visible)
    .filter(b => /^(verify|submit|continue|login|proceed|confirm)$/i.test((text(b) || b.value || "").trim()));
  const body = (document.body && document.body.innerText || "").slice(0, 8000);
  return {boxes: boxes.length, maxLength: boxes.length === 1 ? (boxes[0].maxLength || 0) : 1,
          verify: verify.length, invalid: /invalid otp|incorrect otp|otp (?:has )?expired|wrong otp/i.test(body),
          url: location.href};
}"""

def classify_auth(probe: dict[str, Any]) -> str:
    path = urlsplit(str(probe.get("url", ""))).path.lower()
    if probe.get("challenge"):
        return "challenge"
    if probe.get("otp"):
        return "otp"
    if "/nlogin" in path or path.startswith("/login") or probe.get("loginForm"):
        return "login"
    if probe.get("loggedIn") and path.startswith("/mnjuser"):
        return "ok"
    return "unknown"


def search_url(query: str, *, job_age_days: int | None = None) -> str:
    if query.startswith(ORIGIN + "/"):
        return query
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-") or "jobs"
    url = f"{ORIGIN}/{slug}-jobs?k={quote_plus(query)}"
    if job_age_days:
        allowed = [d for d in (1, 3, 7, 15, 30) if d >= job_age_days]
        url += f"&jobAge={allowed[0] if allowed else 30}"
    return url


def external_job_id(url: str) -> str | None:
    match = JOB_PATH.match(urlsplit(url).path)
    return match.group(1) if match else None


class NaukriAdapter:
    platform = "naukri"

    def __init__(self, *, refresh_wait_ms: int = 3000, settle_ms: int = 1500,
                 receipts_dir: Path | None = None, jitter: tuple[float, float] = (0.8, 2.2),
                 answerer: ScreeningResolver | None = None,
                 otp_provider: OtpProvider | None = None) -> None:
        self.refresh_wait_ms = refresh_wait_ms
        # Phase 6A: auto email-OTP (MailReadService.fetch_recent_otp) when no owner answer exists.
        self.otp_provider = otp_provider
        # Phase 3: Tier 0 profile -> Tier 1 semantic cache -> Tier 2 free LLM; None = HITL.
        self.answerer = answerer
        self.settle_ms = settle_ms
        self.receipts_dir = receipts_dir or brave_profile.runtime_dir() / "receipts" / "naukri"
        self.jitter = jitter

    async def _goto(self, page: Any, url: str) -> None:
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        await page.wait_for_timeout(self.settle_ms)

    async def _probe(self, page: Any) -> dict[str, Any]:
        return await page.evaluate(AUTH_PROBE_JS)

    async def _cookie_names(self, page: Any) -> set[str]:
        try:
            cookies = await page.context.cookies(ORIGIN)
        except Exception:  # noqa: BLE001 - best-effort probe; DOM checks still decide auth
            return set()
        return {c.get("name") for c in cookies}

    async def check_session(self, page: Any) -> SessionCheck:
        """Logged-in check that lets nauk_rt renew an expired nauk_at before failing."""
        await self._goto(page, HOME_URL)
        first = classify_auth(await self._probe(page))
        if first == "ok":
            return SessionCheck(AuthStatus.OK)
        # One clean reload + wait gives Naukri's refresh-token flow a chance,
        # then the authenticated page is requested again.
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_timeout(self.refresh_wait_ms)
        await self._goto(page, HOME_URL)
        second = classify_auth(await self._probe(page))
        cookies = await self._cookie_names(page)
        details = {"first": first, "second": second,
                   "has_refresh_cookie": "nauk_rt" in cookies, "has_access_cookie": "nauk_at" in cookies}
        if second == "ok":
            return SessionCheck(AuthStatus.OK, refreshed=True, details=details)
        if second in {"login", "otp", "challenge"}:
            return SessionCheck(AuthStatus.AUTH_REQUIRED, refreshed=True, reason=second, details=details)
        return SessionCheck(AuthStatus.UNKNOWN, refreshed=True, reason="logged_in_indicator_missing",
                            details=details)

    async def discover_jobs(self, page: Any, *, query: str, limit: int = 20,
                            job_age_days: int | None = None) -> list[JobListing]:
        await self._goto(page, search_url(query, job_age_days=job_age_days))
        data = await page.evaluate(LISTING_JS, {"limit": max(1, min(limit, 50))})
        listings = []
        for item in data["jobs"]:
            posted = item.get("posted")
            listings.append(JobListing(
                platform=self.platform, external_job_id=item["id"], url=item["url"],
                title=item.get("title"), company=item.get("company"), posted_text=posted,
                posted_age_days=parse_posted_age_days(posted),
                age_is_lower_bound=bool(posted and "+" in posted)))
        return listings

    async def inspect_job(self, page: Any, listing: JobListing) -> JobDetail:
        await self._goto(page, listing.url)
        probe = await self._probe(page)
        auth = classify_auth(probe)
        data = await page.evaluate(DETAIL_JS)
        applicant_labels = data.get("applicants") or []
        applicants = parse_applicants(applicant_labels[0] if len(applicant_labels) == 1 else None)
        age = (parse_posted_age_days(data["datePosted"]) if data.get("datePosted")
               else parse_posted_age_days(data.get("posted")) if data.get("posted")
               else listing.posted_age_days)
        if data.get("applied"):
            mode = "applied"
        elif data.get("external"):
            mode = "external"
        elif data.get("applyButtons") == 1:
            mode = "direct"
        else:
            mode = "ambiguous" if data.get("applyButtons") else "none"
        merged = JobListing(
            platform=self.platform, external_job_id=listing.external_job_id, url=listing.url,
            title=data.get("title") or listing.title, company=data.get("company") or listing.company,
            posted_text=data.get("posted") or listing.posted_text, posted_age_days=age,
            age_is_lower_bound=listing.age_is_lower_bound and not data.get("datePosted"),
            applicants=applicants)
        return JobDetail(
            listing=merged, applicants=applicants, posted_age_days=age,
            already_applied=bool(data.get("applied")), apply_mode=mode,
            challenge=auth if auth in {"challenge", "otp", "login"} else None,
            portal_limit=await self.detect_portal_limit(page),
            description=data.get("description"), salary_text=data.get("salary"),
            location=data.get("location"), work_mode=data.get("workMode"))

    async def extract_form(self, page: Any) -> dict[str, Any]:
        return await extract_form(page)

    async def detect_portal_limit(self, page: Any) -> str | None:
        body = await page.evaluate("() => (document.body && document.body.innerText || '').slice(0, 20000)")
        match = PORTAL_LIMIT.search(body or "")
        return match.group(0) if match else None

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
        return await page.evaluate(PAGE_STATE_JS)

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
        return page.locator('#job_header button, [class*="jd-header"] button, [class*="jdHeader"] button').filter(
            has_text=re.compile(r"^\s*Apply\s*$"))

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

    async def _answer(self, page: Any, state: dict[str, Any], answer: str) -> None:
        drawer = page.locator(".chatbot_DrawerContentWrapper")
        send = drawer.locator(".send").filter(has_text=re.compile(r"^\s*(save|send|next|continue)\s*$", re.IGNORECASE))
        if state.get("chips"):
            await drawer.locator(".chipsContainer .chatbot_Chip").filter(
                has_text=re.compile(r"^\s*" + re.escape(answer) + r"\s*$")).first.click()
            return
        if state.get("radios"):
            await drawer.locator("label.ssrc__label").filter(
                has_text=re.compile(r"^\s*" + re.escape(answer) + r"\s*$")).first.click()
            await page.wait_for_timeout(300)
            await send.first.click()
            return
        editor = drawer.locator('.textArea[contenteditable="true"]').first
        await editor.click()
        await editor.fill(answer)
        await page.wait_for_timeout(300)
        await send.first.click()

    async def _confirm_from_history(self, page: Any, detail: JobDetail) -> str | None:
        await self._goto(page, HISTORY_URL)
        rows = await page.evaluate(HISTORY_JS, {"title": detail.listing.title or "",
                                                "company": detail.listing.company or ""})
        sent = [r for r in rows if HISTORY_SENT.match(r.get("status") or "")]
        return "application_history" if len(sent) == 1 else None

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

    # --- Phase 6A: live OTP entry -----------------------------------------------------------
    @staticmethod
    def otp_from_answers(hitl_answers: dict[str, str] | None) -> str | None:
        """Newest owner answer that is a 4-8 digit code (resolved OTP HITL rows)."""
        for answer in reversed(list((hitl_answers or {}).values())):
            match = OTP_VALUE.match(answer or "")
            if match:
                return match.group(1)
        return None

    async def obtain_otp(self, hitl_answers: dict[str, str] | None, since: datetime) -> tuple[str | None, str]:
        code = self.otp_from_answers(hitl_answers)
        if code:
            return code, "hitl_owner_answer"
        if self.otp_provider is not None:
            try:
                fetched = await self.otp_provider(self.platform, since)
            except Exception:  # noqa: BLE001 - mail outage: fall back to the OTP HITL
                fetched = None
            if fetched and OTP_VALUE.match(fetched):
                return fetched.strip(), "email_otp"
        return None, "none"

    async def enter_otp(self, page: Any, code: str) -> bool:
        """Type the code into Naukri's OTP box(es) and press Verify. True when the OTP screen clears."""
        if not OTP_VALUE.match(code or ""):
            return False
        state = await page.evaluate(OTP_STATE_JS)
        if not state.get("boxes"):
            return False
        boxes = page.locator('input[autocomplete="one-time-code"],input[name*="otp" i],input[id*="otp" i],'
                             'input[class*="otp" i]')
        digits = code.strip()
        if state["boxes"] == 1:
            await boxes.first.fill(digits)
        else:  # one box per digit
            for index, digit in enumerate(digits[: state["boxes"]]):
                await boxes.nth(index).fill(digit)
        await page.wait_for_timeout(300)
        verify = page.locator("button,[role=button],input[type=submit]").filter(
            has_text=re.compile(r"^\s*(verify|submit|continue|login|proceed|confirm)\s*$", re.IGNORECASE))
        if await verify.count() >= 1:
            await verify.first.click()
        else:
            await boxes.last.press("Enter")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 10
        while loop.time() < deadline:
            await page.wait_for_timeout(400)
            after = await page.evaluate(OTP_STATE_JS)
            if after.get("invalid"):
                return False
            if not after.get("boxes"):
                return True
        return False

    async def recover_otp(self, page: Any, hitl_answers: dict[str, str] | None) -> tuple[bool, str]:
        since = datetime.now(UTC) - timedelta(minutes=3)
        code, source = await self.obtain_otp(hitl_answers, since)
        if code is None:
            return False, "otp_unavailable"
        return await self.enter_otp(page, code), source

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
        if detail.apply_mode != "direct":
            return self._result(ApplicationState.FAILED, f"apply_control_{detail.apply_mode}", dry_run)

        await self._opt_out_company_follow(page)
        button = await self._apply_button(page)
        if await button.count() != 1:
            return self._result(ApplicationState.FAILED, "apply_control_changed", dry_run)
        planned = f"click Naukri 'Apply' for {job_id} ({detail.listing.title} @ {detail.listing.company})"
        if dry_run:
            shot = await self._screenshot(page, job_id, "dry-run")
            return self._result(ApplicationState.SCORED, "dry_run_stopped_before_apply_click", True,
                                planned_action=planned, screenshot=shot)

        await self._pause()
        pages_before = len(page.context.pages)
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
            question = state.get("question") or ""
            options = tuple(state.get("chips") or state.get("radios") or ())
            input_kind = "file" if state.get("fileInput") else "choice" if options else "text"
            answer, answer_source, resolver_reason = None, "human", "file_upload"
            if input_kind != "file":
                answer, answer_source, resolver_reason = await self._resolve(question, options, facts, detail,
                                                                             hitl_answers)
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
            answers.append({"question": question, "answer": answer, "source": answer_source})
            state = await self._wait_after_answer(page, question)
            if state.get("drawer") and state.get("question") == question and not self._confirmation(state):
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
                   "verified_at": datetime.now(UTC).isoformat(), "answers": answers}
        return self._result(ApplicationState.APPLIED, "confirmed", False, clicked_apply=True,
                            receipt=receipt, screenshot=shot, answers=tuple(answers))
