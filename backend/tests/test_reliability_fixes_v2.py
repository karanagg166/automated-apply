"""2026-11-28 live-failure regressions.

1. Greenhouse job-boards render a page-level "Apply" button beside the form's own
   "Submit application"; the ATS flow refused every hosted form (ats_submit_control_2).
2. The worker's single asyncpg connection died during laptop clamshell sleep and was
   never replaced, so the worker looped on InterfaceError for 8 hours.
"""

from __future__ import annotations

import asyncio

import pytest

from backend.app.browser_v2.adapters.greenhouse import GreenhouseAdapter
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store.base import SerializedConnection
from backend.tests.phase6a_fixtures import (  # noqa: F401
    chromium_fixture,
    facts,
    html,
    web_fixture,
)
from backend.tests.test_adapters_phase6 import AUTH_ANSWER, GH_JOB, gh_detail, gh_form

pytestmark = [pytest.mark.asyncio(loop_scope="module"),
              pytest.mark.filterwarnings("ignore:The test <Function:pytest.PytestWarning")]


def gh_with_page_apply_button() -> str:
    form = gh_form()
    assert "<form" in form
    return form.replace("<form", '<button type="button" class="btn btn--pill">Apply</button><form', 1)


async def test_greenhouse_page_level_apply_button_does_not_block_submit(web, tmp_path):
    page, site = web
    site.add(GH_JOB, gh_with_page_apply_button())
    site.add(GH_JOB + "/confirmation", html("<h2>Thank you for applying to Acme!</h2>"))
    adapter = GreenhouseAdapter(receipts_root=tmp_path, settle_ms=10, confirm_timeout_s=5)
    result = await adapter.apply_job(page, gh_detail(), facts(tmp_path), dry_run=False, hitl_answers=AUTH_ANSWER)
    assert result.reason != "ats_submit_control_2"
    assert result.state is S.APPLIED and result.reason == "confirmed"


# --- SerializedConnection reconnect -------------------------------------------------------------------------
class FakeConn:
    def __init__(self, name: str) -> None:
        self.name = name
        self.closed = False
        self.terminated = False
        self.calls: list[str] = []

    def is_closed(self) -> bool:
        return self.closed

    def terminate(self) -> None:
        self.terminated = True
        self.closed = True

    async def fetchval(self, query: str) -> str:
        if self.closed:
            raise RuntimeError("connection is closed")  # must never be reached after a reconnect
        self.calls.append(query)
        return self.name

    async def execute(self, query: str) -> str:
        raise TimeoutError


async def test_closed_connection_is_replaced_before_the_next_query():
    first, second = FakeConn("a"), FakeConn("b")
    opened = [second]

    async def reconnect():
        return opened.pop()

    conn = SerializedConnection(first, reconnect=reconnect)
    assert await conn.fetchval("select 1") == "a"
    first.closed = True  # clamshell sleep killed the socket
    assert await conn.fetchval("select 1") == "b"
    assert conn.reconnects == 1 and second.calls == ["select 1"]


async def test_timeout_terminates_the_socket_so_the_next_call_reconnects():
    first, second = FakeConn("a"), FakeConn("b")

    async def reconnect():
        return second

    conn = SerializedConnection(first, reconnect=reconnect)
    with pytest.raises(TimeoutError):
        await conn.execute("update x")
    assert first.terminated
    assert await conn.fetchval("select 1") == "b"


async def test_failed_reconnect_raises_and_retries_on_the_next_call():
    first, second = FakeConn("a"), FakeConn("b")
    first.closed = True
    attempts = []

    async def reconnect():
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("network down")
        return second

    conn = SerializedConnection(first, reconnect=reconnect)
    with pytest.raises(OSError):
        await conn.fetchval("select 1")
    assert await conn.fetchval("select 1") == "b"


async def test_without_reconnect_factory_behaviour_is_unchanged():
    first = FakeConn("a")
    conn = SerializedConnection(first)
    first.closed = True
    with pytest.raises(RuntimeError):
        await conn.fetchval("select 1")
    assert not first.terminated


async def test_concurrent_callers_reconnect_once():
    first, second = FakeConn("a"), FakeConn("b")
    first.closed = True
    count = []

    async def reconnect():
        count.append(1)
        await asyncio.sleep(0)
        return second

    conn = SerializedConnection(first, reconnect=reconnect)
    results = await asyncio.gather(*(conn.fetchval("select 1") for _ in range(5)))
    assert results == ["b"] * 5 and len(count) == 1


# --- a job that fails before submit on every rediscovery is parked -----------------------------------------
class DomFailAdapter:
    platform = "greenhouse"
    tracks_submit = True

    async def check_session(self, page):
        from backend.app.browser_v2.adapters.base import AuthStatus, SessionCheck
        return SessionCheck(AuthStatus.OK)

    async def discover_jobs(self, page, *, query, limit=20, job_age_days=None):
        return []

    async def inspect_job(self, page, listing):
        from backend.app.browser_v2.adapters.base import JobDetail
        from backend.app.browser_v2.rules import parse_applicants
        return JobDetail(listing=listing, applicants=parse_applicants("10 applicants"), posted_age_days=1,
                         already_applied=False, apply_mode="direct", description="python fastapi backend",
                         apply_url=listing.url, ats="greenhouse")

    async def extract_form(self, page):
        return {}

    async def detect_portal_limit(self, page):
        return None

    async def apply_job(self, page, detail, profile, *, dry_run=True, existing_state=None, hitl_answers=None):
        from backend.app.browser_v2.adapters.base import ApplyResult
        return ApplyResult(S.FAILED, "ats_submit_control_2", dry_run)


async def test_repeated_dom_failures_on_one_job_stop_after_the_attempt_cap():
    from backend.app.browser_v2.service.apply import MAX_PRE_SUBMIT_ATTEMPTS
    from backend.tests.test_m2_submit_quota_and_codes import LISTING, make_service

    service, store, _ = make_service(DomFailAdapter())
    for _ in range(MAX_PRE_SUBMIT_ATTEMPTS - 1):
        await service.process_job(LISTING, dry_run=False, record_filters=True)
        record = await store.get("greenhouse", "4012345")
        assert record is not None and record.state is S.FAILED
    await service.process_job(LISTING, dry_run=False, record_filters=True)
    record = await store.get("greenhouse", "4012345")
    assert record is not None and record.state is S.FILTERED_OUT
    assert record.reason == "failures_exhausted:ats_submit_control_2"
