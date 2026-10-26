"""Bounded non-value dropdown inspection; website code never gains network access."""

import asyncio
from pathlib import Path

from fastapi import HTTPException

from backend.app.browser.contracts import DetectedField

OPTIONS = Path(__file__).with_name("dropdown_options.js").read_text()
STATE = Path(__file__).with_name("dropdown_state.js").read_text()
MAX_PROBES = 3


async def choices(page, key):
    for _ in range(8):
        result = await page.evaluate(OPTIONS, {"key": key})
        if result is not None:
            await asyncio.sleep(0.05)
            second = await page.evaluate(OPTIONS, {"key": key})
            if second != result:
                return {"options": [], "error": "Dropdown choices are still changing"}
            return result
        await asyncio.sleep(0.05)
    return {"options": [], "error": "Load dropdown choices manually with Take Over"}


async def discover(runtime, fields):
    if runtime.manual:
        return []
    catalog = []
    candidates = [
        DetectedField.model_validate(field).model_dump()
        for field in fields
        if field["kind"] == "combobox"
        and not field["options"]
        and field["manual_reason"]
        == "Unsupported or ambiguous custom dropdown: complete manually"
    ]
    for field in candidates[:MAX_PROBES]:
        key = field["key"]
        if not await runtime.page.evaluate(OPTIONS, {"key": key, "eligibility": True}):
            continue
        if runtime.blocked_step_requests:
            raise HTTPException(
                409, "Choice inspection requires network activity; take over manually"
            )
        runtime.in_page_mode = True
        blocked, epoch = runtime.blocked_step_requests, runtime.document_epoch
        before = await runtime.page.evaluate(STATE)
        element = runtime.page.locator(f'[data-aa-field="{key}"]')
        try:
            await element.click(timeout=1500)
            result = await choices(runtime.page, key)
        finally:
            if not runtime.page.is_closed():
                await element.press("Escape", timeout=1500)
        after = await runtime.page.evaluate(STATE)
        if (
            runtime.cancelled
            or before != after
            or epoch != runtime.document_epoch
            or runtime.blocked_step_requests != blocked
            or await element.get_attribute("aria-expanded") != "false"
        ):
            raise HTTPException(
                409,
                "Dropdown inspection changed values, needed network access or could not close safely; take over manually",
            )
        catalog.append({"key": key, **result})
    return catalog


async def open_reviewed(runtime, field):
    """Re-read the actual newly mounted list immediately before selecting a value."""
    element = runtime.page.locator(f'[data-aa-field="{field["key"]}"]')
    if await element.get_attribute("aria-expanded") == "false":
        await element.click(timeout=1500)
    actual = await choices(runtime.page, field["key"])
    if (
        actual["error"]
        or actual["options"] != field["options"]
        or runtime.blocked_step_requests
    ):
        raise HTTPException(
            409,
            "Dropdown choices changed or need network access; reanalyze or take over",
        )
    return element
