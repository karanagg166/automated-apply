"""Greenhouse post-submit email security code step (Milestone 2).

After Submit #1 Greenhouse may hold the application behind "A verification code was sent to
your email" + an 8-character input. The applier then asks an injected, read-only mail provider
for the newest matching code (see `mail_v2.security_codes`), types it, clicks Submit #2 and
verifies the confirmation. No code -> ONE P0 OTP HITL card; the raw code is never logged.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from backend.app.browser_v2.adapters.base import HitlQuestion

logger = logging.getLogger(__name__)

SECURITY_PROMPT = re.compile(r"verification code (?:was|has been) sent|security code|enter (?:the )?"
                             r"(?:8|eight)[- ]character code|check your email for a code", re.IGNORECASE)
OWNER_CODE = re.compile(r"^\s*([A-Za-z0-9]{8})\s*$")
CODE_INPUTS_JS = """() => {
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const all = [...document.querySelectorAll('input')].filter(el => visible(el) && !el.disabled &&
      !['hidden','file','checkbox','radio','submit','button'].includes((el.type || '').toLowerCase()));
  const hint = el => [el.name, el.id, el.autocomplete, el.getAttribute('aria-label'), el.placeholder]
      .join(' ').toLowerCase();
  const single = all.filter(el => /security|verification|code|otp|one-time/.test(hint(el)) &&
      (el.maxLength === -1 || el.maxLength >= 8));
  const boxes = all.filter(el => el.maxLength === 1);
  const mark = (els) => els.map((el, i) => { el.setAttribute('data-aa-code', String(i)); return i; }).length;
  if (single.length === 1) return {mode: 'single', count: mark(single)};
  if (boxes.length === 8) return {mode: 'boxes', count: mark(boxes)};
  return {mode: 'none', count: 0};
}"""

CodeProvider = Callable[[str | None, datetime], Awaitable[str | None]]
OWNER_PROMPT = "{company}: Greenhouse emailed an 8-character security code - reply with the code"


def needs_security_code(state: dict[str, Any]) -> bool:
    return not state.get("confirmed") and bool(SECURITY_PROMPT.search(state.get("body") or ""))


def owner_prompt(company: str | None) -> str:
    return OWNER_PROMPT.format(company=company or "Greenhouse application")


def owner_code(hitl_answers: dict[str, str] | None, company: str | None) -> str | None:
    """A code the owner replied to the OTP card with (only for this company's prompt)."""
    value = (hitl_answers or {}).get(owner_prompt(company))
    match = OWNER_CODE.match(value or "")
    return match.group(1) if match else None


def code_question(company: str | None, url: str, platform: str, reason: str) -> HitlQuestion:
    return HitlQuestion(kind="OTP", prompt=owner_prompt(company), input_kind="text",
                        context={"url": url, "platform": platform, "priority": "P0",
                                 "resolver_reason": reason, "company": company})


async def type_code(page: Any, code: str) -> bool:
    """Fill a single code input or 8 one-character boxes; False when no code control is found."""
    found = await page.evaluate(CODE_INPUTS_JS)
    mode = (found or {}).get("mode")
    if mode == "single":
        await page.locator('[data-aa-code="0"]').fill(code, timeout=8_000)
        return True
    if mode == "boxes":
        for index, char in enumerate(code):
            await page.locator(f'[data-aa-code="{index}"]').fill(char, timeout=8_000)
        return True
    return False


async def obtain_code(provider: CodeProvider | None, company: str | None, submitted_at: datetime,
                      hitl_answers: dict[str, str] | None) -> tuple[str | None, str]:
    """(code, source): a fresh email code first, else the owner's HITL reply, else (None, reason)."""
    if provider is not None:
        try:
            code = await provider(company, submitted_at)
        except Exception as exc:  # noqa: BLE001 - mail trouble degrades to the owner card
            logger.info("security code provider failed: %s", type(exc).__name__)
            code = None
        if code:
            return code, "email_auto"
    owner = owner_code(hitl_answers, company)
    if owner:
        return owner, "owner_hitl"
    return None, "security_code_timeout" if provider is not None else "security_code_mail_unavailable"
