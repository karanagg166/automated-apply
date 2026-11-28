"""react-select / ARIA combobox helpers shared by the hosted-form filler.

Live 2026-11-28 Greenhouse (Twilio, Stripe):
- "Location (City)" loads geo suggestions asynchronously (~0.5-1.5 s); Enter after a short
  settle selected nothing -> "Please enter your location".
- `fill()` without a click first never opened the menu (aria-expanded stayed false).
- "School" searches a fixed list that has no entry for many Indian colleges (IIITDM Jabalpur);
  the list's own "Other" entry is the honest pick.
"""

from __future__ import annotations

import re
from typing import Any

ACTION_TIMEOUT_MS = 8_000  # one form widget never blocks the apply for 30 s
ASYNC_OPTION_WAIT_MS = 6_000
STATIC_OPTION_WAIT_MS = 1_500
OPTION_POLL_MS = 250
EDUCATION_LABEL = re.compile(r"\b(?:school|university|college|institut(?:e|ion))\b", re.IGNORECASE)


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


async def type_into_combobox(page: Any, locator: Any, value: str) -> None:
    """Focus, type and make sure the menu opened (real keystrokes when `fill` did not open it)."""
    await locator.click(timeout=ACTION_TIMEOUT_MS)
    await locator.fill(value, timeout=ACTION_TIMEOUT_MS)
    await page.wait_for_timeout(OPTION_POLL_MS)
    if (await locator.get_attribute("aria-expanded")) != "true":
        await locator.fill("", timeout=ACTION_TIMEOUT_MS)
        await locator.press_sequentially(value, delay=40, timeout=ACTION_TIMEOUT_MS)


async def pick_combobox_option(page: Any, locator: Any, value: str, *, exact: bool, wait_ms: int) -> bool:
    """Click THIS combobox's option for `value` once it renders; False when none appears in time.

    exact=False (typed identity values such as a city) also accepts the first option that starts
    with the value ("Faridabad" -> "Faridabad, Haryana, India"), but only inside the field's own
    listbox, never a page-wide list (the phone country-code picker is always in the DOM).
    """
    wanted, waited = _norm(value), 0
    while True:
        listbox = ((await locator.get_attribute("aria-controls")) or (await locator.get_attribute("aria-owns"))
                   or "").split(" ")[0]
        scope = page.locator(f'[id="{listbox}"]') if listbox else page
        options = scope.locator("[role=option]").filter(visible=True)
        best = None
        for index in range(min(await options.count(), 50)):
            text = _norm(await options.nth(index).inner_text())
            if text == wanted:
                best = index
                break
            if best is None and not exact and listbox and text.startswith(wanted):
                best = index
        if best is not None:
            await options.nth(best).click(timeout=ACTION_TIMEOUT_MS)
            return True
        if waited >= wait_ms:
            return False
        await page.wait_for_timeout(OPTION_POLL_MS)
        waited += OPTION_POLL_MS


async def pick_other_education(page: Any, locator: Any, label: str) -> bool:
    """School/university pickers without the candidate's college: choose the list's own "Other"."""
    if not EDUCATION_LABEL.search(label or ""):
        return False
    await type_into_combobox(page, locator, "Other")
    return await pick_combobox_option(page, locator, "Other", exact=True, wait_ms=ASYNC_OPTION_WAIT_MS)
