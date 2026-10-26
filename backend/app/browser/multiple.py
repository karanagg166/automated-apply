"""Reviewed set replacement with per-checkbox structure and network checks."""

from fastapi import HTTPException


async def fill_group(runtime, field, selected):
    signature = runtime.signature
    current = field
    for label in field["options"]:
        root = runtime.page.locator(f'[data-aa-field="{current["key"]}"]')
        choice = root.get_by_role("checkbox", name=label, exact=True)
        if await choice.count() != 1:
            raise HTTPException(409, "Checkbox choices changed; reanalyze")
        native = await choice.evaluate("e=>e.matches('input[type=checkbox]')")
        checked = (
            await choice.is_checked()
            if native
            else await choice.get_attribute("aria-checked") == "true"
        )
        desired = label in selected
        if checked != desired:
            if native:
                await choice.set_checked(desired, timeout=3000)
            else:
                await choice.click(timeout=3000)
            if runtime.blocked_step_requests:
                raise HTTPException(
                    409, "Checkbox handler needs networking; take over manually"
                )
            fresh, _ = await runtime.unchanged(signature)
            matches = [
                item
                for item in fresh
                if item["kind"] == field["kind"]
                and item["question"] == field["question"]
                and item.get("options_binding") == field.get("options_binding")
            ]
            if len(matches) != 1:
                raise HTTPException(409, "Checkbox group changed; reanalyze")
            current = matches[0]
    root = runtime.page.locator(f'[data-aa-field="{current["key"]}"]')
    actual = []
    for label in field["options"]:
        choice = root.get_by_role("checkbox", name=label, exact=True)
        checked = await choice.evaluate(
            "e=>e.matches('input[type=checkbox]') ? e.checked : e.getAttribute('aria-checked') === 'true'"
        )
        if checked:
            actual.append(label)
    valid = await root.evaluate(
        "e=>e.getAttribute('aria-invalid') !== 'true' && [...e.querySelectorAll('input[type=checkbox],[role=checkbox]')].every(c=>(!c.validity || c.validity.valid) && c.getAttribute('aria-invalid') !== 'true')"
    )
    return (
        valid
        and set(actual) == set(selected)
        and (not field["required"] or bool(actual))
    )
