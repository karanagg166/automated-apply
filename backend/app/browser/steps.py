"""Owner-reviewed, idempotent in-page step changes with submission guards intact."""

import asyncio
from pathlib import Path

from fastapi import HTTPException
from pydantic import Field, StrictBool

from backend.app.browser.runner import browser
from backend.app.browser.service import analyze, metadata, status
from backend.app.schemas.applications import IdempotencyKey, RevisionInput
from backend.app.services.applications.resume_selector import digest
from backend.app.services.applications.service import ApplicationPacketService

STATE = Path(__file__).with_name("step_state.js").read_text()


class AdvanceStep(RevisionInput):
    preview_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: IdempotencyKey
    confirm_values_and_consents: StrictBool


async def inspect(session, packet_id, revision):
    service = ApplicationPacketService(session)
    packet, _, _ = await service.locked(packet_id, revision)
    saved = await metadata(session, packet_id)
    runtime = browser.sessions.get(str(packet_id))
    if not saved or not runtime or runtime.manual or runtime.page.is_closed():
        raise HTTPException(
            409, "Analyze the connected application before reviewing the next step"
        )
    from backend.app.services.applications.multi_select import available

    runtime.multi_enabled = await available(session)
    fields, _ = await runtime.unchanged(saved.value["signature"])
    if runtime.has_frames:
        raise HTTPException(409, "Embedded forms require manual step navigation")
    runtime.in_page_mode = True
    if runtime.blocked_step_requests:
        raise HTTPException(
            409, "This page needs network activity; take over and reanalyze manually"
        )
    steps = runtime.steps
    if len(steps) != 1 or not steps[0]["supported"]:
        raise HTTPException(
            409, "No unambiguous in-page Next/Continue button; take over manually"
        )
    actual = await runtime.page.evaluate(STATE, fields)
    bound = {
        "packet_id": str(packet.id),
        "revision": packet.revision,
        "form": runtime.signature,
        "button": steps[0]["label"],
        "state": actual,
    }
    return (
        service,
        packet,
        saved,
        runtime,
        {
            "label": steps[0]["label"],
            "values": actual["values"],
            "complete": actual["complete"],
            "preview_digest": digest(bound),
            "expected_revision": packet.revision,
            "warning": "Reviewing this in-page step pauses all page network activity until Take Over. Form submission, navigation and server-save requests remain blocked.",
        },
    )


async def preview(session, packet_id, revision):
    *_, result = await inspect(session, packet_id, revision)
    return result


async def advance(session, packet_id, data):
    # Resolve replay before checking an old revision; it must never click again.
    saved = await metadata(session, packet_id)
    history = list(saved.value.get("step_history", [])) if saved else []
    previous = next(
        (item for item in history if item["key"] == data.idempotency_key), None
    )
    if previous:
        if previous["digest"] != data.preview_digest:
            raise HTTPException(
                409, "Step idempotency key belongs to different reviewed values"
            )
        return await status(session, packet_id)
    if not data.confirm_values_and_consents:
        raise HTTPException(
            422, "Review the actual values and every selected consent before advancing"
        )
    service, packet, saved, runtime, current = await inspect(
        session, packet_id, data.expected_revision
    )
    if current["preview_digest"] != data.preview_digest:
        raise HTTPException(409, "Step values or form changed; review a fresh preview")
    if not current["complete"]:
        raise HTTPException(
            409, "Complete required answers and resolve validation before advancing"
        )
    if (
        saved.value.get("diagnostic") in {"step_started", "step_handoff_required"}
        or len(history) >= 20
    ):
        raise HTTPException(
            409,
            "Inspect the interrupted or long application manually before continuing",
        )
    previous_signature, blocked = runtime.signature, runtime.blocked_mutations
    blocked_step = runtime.blocked_step_requests
    submission_blocks = await runtime.page.evaluate("window.__aaSubmissionBlocks || 0")
    record = {
        "key": data.idempotency_key,
        "digest": data.preview_digest,
        "outcome": "started",
    }
    # Do not advance packet revision until a real next-step analysis succeeds.
    # This durable intent prevents retries after process loss or a lost response.
    saved.value = {
        **saved.value,
        "diagnostic": "step_started",
        "step_history": [*history, record],
    }
    await session.commit()
    await service.locked(packet.id, data.expected_revision)
    runtime.in_page_mode = True
    outcome = "step_handoff_required"
    try:
        async with asyncio.timeout(12):
            *_, verified = await inspect(session, packet_id, data.expected_revision)
            if verified["preview_digest"] != data.preview_digest:
                raise HTTPException(409, "Step changed after recording intent")
            key = runtime.steps[0]["key"]
            button = runtime.page.locator(f'[data-aa-step="{key}"]')
            if await button.count() != 1:
                raise HTTPException(409, "Step changed before click")
            await button.click(timeout=5000)
            for _ in range(24):
                await asyncio.sleep(0.2)
                await runtime.scan()
                if (
                    runtime.blocked_mutations != blocked
                    or runtime.blocked_step_requests != blocked_step
                    or await runtime.page.evaluate("window.__aaSubmissionBlocks || 0")
                    != submission_blocks
                ):
                    break
                if runtime.signature != previous_signature:
                    changed = runtime.signature
                    await asyncio.sleep(0.4)
                    await runtime.scan()
                    if (
                        runtime.blocked_mutations != blocked
                        or runtime.blocked_step_requests != blocked_step
                        or runtime.signature != changed
                        or await runtime.page.evaluate(
                            "window.__aaSubmissionBlocks || 0"
                        )
                        != submission_blocks
                    ):
                        break
                    await analyze(session, packet, service, runtime)
                    outcome = "next_step_analyzed"
                    break
    except Exception:
        outcome = "step_handoff_required"
    latest = await metadata(session, packet_id)
    latest.value = {
        **latest.value,
        "diagnostic": outcome,
        "step_history": [*history, {**record, "outcome": outcome}],
    }
    await session.commit()
    return await status(session, packet_id)
