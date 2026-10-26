"""Named interruption, stale requests, queued work and authentication boundaries."""

import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.browser.operations import BrowserOperations


@pytest.mark.asyncio
async def test_cancel_interrupts_only_named_task_and_discards_already_queued_work():
    lock = asyncio.Lock()
    operations = BrowserOperations(lambda _: lock)
    entered = asyncio.Event()
    release = asyncio.Event()
    executed = []

    async def run(first=False):
        async with operations.run("packet", "fill", 3):
            if first:
                entered.set()
                await release.wait()
            operations.checkpoint("packet")
            executed.append("queued")

    active = asyncio.create_task(run(True))
    await entered.wait()
    queued = asyncio.create_task(run())
    await asyncio.sleep(0)
    identity = operations.public("packet")["id"]
    for wrong, revision in [(uuid4(), 3), (identity, 2), (None, 3)]:
        with pytest.raises(HTTPException):
            operations.request_stop("packet", wrong, revision, 3)
        assert not active.done()
    ticket, interrupted = operations.request_stop("packet", identity, 3, 3)
    assert interrupted["cancel_requested"]
    release.set()
    for task in (active, queued):
        with pytest.raises(HTTPException) as error:
            await task
        assert error.value.status_code == 409
    assert executed == [] and not operations.active
    with pytest.raises(HTTPException):
        async with operations.run("packet", "open", 3):
            pytest.fail("Cancellation reconciliation must fence new commands")
    operations.reconciled("packet", ticket)
    async with operations.run("packet", "open", 3):
        assert operations.public("packet")["id"] != identity
        with pytest.raises(HTTPException):
            operations.request_stop("packet", identity, 3, 3)


@pytest.mark.asyncio
async def test_unrelated_task_cancellation_keeps_native_cancellation_semantics():
    lock = asyncio.Lock()
    operations = BrowserOperations(lambda _: lock)
    entered = asyncio.Event()

    async def run():
        async with operations.run("packet", "analyze", 2):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(run())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not operations.active and not lock.locked()


@pytest.mark.asyncio
async def test_operation_control_and_cancel_require_existing_owner_authentication(
    async_client, phase2_auth, monkeypatch
):
    from backend.app.browser.runner import browser
    from backend.app.core.config import get_settings

    monkeypatch.setenv("BROWSER_ASSISTANT_ENABLED", "true")
    get_settings.cache_clear()
    packet_id = str(uuid4())
    entered, release = asyncio.Event(), asyncio.Event()

    async def operation():
        async with browser.operations.run(packet_id, "fill", 1):
            entered.set()
            await release.wait()

    task = asyncio.create_task(operation())
    await entered.wait()
    try:
        route = "/api/v1/browser-applications/" + packet_id
        assert (await async_client.get(route + "/operation")).status_code == 401
        assert (
            await async_client.post(
                route + "/actions", json={"action": "cancel", "expected_revision": 1}
            )
        ).status_code == 401
        assert (
            await async_client.get(
                route + "/operation",
                headers={**phase2_auth, "Origin": "https://untrusted.invalid"},
            )
        ).status_code == 403
        assert not browser.operations.public(packet_id)["cancel_requested"]
    finally:
        release.set()
        await task


@pytest.mark.asyncio
async def test_cancel_before_driver_start_still_disposes_late_resources_once():
    from backend.app.browser.runner import BrowserResources

    resources = BrowserResources()
    await resources.close()
    with pytest.raises(HTTPException):
        resources.checkpoint()

    class Driver:
        stops = 0

        async def stop(self):
            self.stops += 1

    resources.playwright = Driver()
    await resources.close()
    await resources.close()
    assert resources.playwright.stops == 1
