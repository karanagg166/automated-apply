"""Phase 8b: Remotive / Arbeitnow / HN / Ashby / SmartRecruiters as v2 feed portals (no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from backend.app.browser_v2.adapters.feeds import FeedJob
from backend.app.browser_v2.adapters.public_sources import (
    REMOTIVE_MAX_FETCHES_PER_DAY,
    ArbeitnowAdapter,
    AshbyAdapter,
    FetchBudget,
    HackerNewsAdapter,
    RemotiveAdapter,
    SmartRecruitersAdapter,
    employer_link,
)
from backend.app.browser_v2.portals import PORTALS
from backend.app.browser_v2.service import default_adapters, job_id_from_url
from backend.app.browser_v2.store import MemoryStore, PostgresStore
from backend.app.schemas.candidate_profile import JobSearchPreferences
from backend.app.schemas.normalized_job import NormalizedJob

NEW = ("ashby", "smartrecruiters", "remotive", "arbeitnow", "hacker_news")


def client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


REMOTIVE = {"jobs": [{"id": 9988, "url": "https://remotive.com/remote-jobs/software-dev/python-developer-9988",
                      "title": "Python Developer", "company_name": "Acme Global",
                      "candidate_required_location": "Worldwide", "job_type": "full_time",
                      "description": "<p>Building APIs with FastAPI</p>",
                      "publication_date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}]}


def test_registry_has_15_portals_and_an_adapter_each():
    adapters = default_adapters()
    assert set(adapters) == set(PORTALS) and len(PORTALS) == 15
    assert all(not PORTALS[p].requires_login and not PORTALS[p].default_enabled for p in NEW)


async def test_memory_store_lists_the_new_portals_disabled():
    rules = {r.platform: r for r in await MemoryStore().list_rules()}
    assert all(p in rules and not rules[p].enabled for p in NEW)


async def test_remotive_discovers_and_respects_four_fetches_a_day(tmp_path):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.url.host == "remotive.com"
        return httpx.Response(200, json=REMOTIVE)

    budget = FetchBudget("remotive", REMOTIVE_MAX_FETCHES_PER_DAY, tmp_path / "budget.json")
    adapter = RemotiveAdapter(http_client=client(handler), budget=budget)
    listings = await adapter.discover_jobs(None, query="python developer", limit=5)
    assert [(item.external_job_id, item.company, item.posted_age_days) for item in listings] == [
        ("9988", "Acme Global", 0)]
    adapter.feed_ttl_sec = 0  # force re-reads: the persisted budget is what stops them
    for _ in range(6):
        await adapter.fetch("python", 10)
    assert len(calls) == REMOTIVE_MAX_FETCHES_PER_DAY
    restarted = RemotiveAdapter(http_client=client(handler), budget=FetchBudget(
        "remotive", REMOTIVE_MAX_FETCHES_PER_DAY, tmp_path / "budget.json"))
    assert await restarted.fetch("python", 10) == [] and len(calls) == REMOTIVE_MAX_FETCHES_PER_DAY


async def test_listing_page_sources_resolve_apply_links_or_keep_direct_ones():
    adapter = ArbeitnowAdapter()
    on_site = FeedJob("a1", "https://www.arbeitnow.com/jobs/x-1", "Dev", "Co", None)
    assert await adapter.resolve_apply_url(None, on_site) is None  # needs the listing page
    direct = FeedJob("a2", "https://www.arbeitnow.com/jobs/x-2", "Dev", "Co",
                     "https://boards.greenhouse.io/acme/jobs/4012345")
    assert await adapter.resolve_apply_url(None, direct) == "https://boards.greenhouse.io/acme/jobs/4012345"


def test_hn_employer_link_prefers_ats_and_skips_hn():
    comment = ('Acme | Backend Engineer | Remote<p>See <a href="https://news.ycombinator.com/user?id=x">me</a> '
               'or apply: <a href="https://jobs.lever.co/acme/0f1e2d3c-aaaa-bbbb-cccc-1234567890ab">'
               'link</a> https://acme.example/blog</p>')
    exclude = frozenset({"news.ycombinator.com"})
    assert employer_link(comment, exclude_hosts=exclude) == \
        "https://jobs.lever.co/acme/0f1e2d3c-aaaa-bbbb-cccc-1234567890ab"
    assert employer_link("no links here", exclude_hosts=exclude) is None


async def test_hn_feed_carries_the_employer_link():
    stories = {"hits": [{"objectID": "40001", "title": "Ask HN: Who is hiring? (November 2026)"}]}
    comments = {"hits": [{"objectID": "40002", "comment_text":
                          'TechCorp | Senior Python Engineer | Remote | Full-time<p>Apply at '
                          '<a href="https://boards.greenhouse.io/techcorp/jobs/123456">greenhouse</a></p>'}]}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=stories if "author_whoishiring" in str(request.url) else comments)

    jobs = await HackerNewsAdapter(http_client=client(handler)).fetch("python", 10)
    assert jobs and jobs[0].apply_url == "https://boards.greenhouse.io/techcorp/jobs/123456"
    assert job_id_from_url("hacker_news", jobs[0].url) == jobs[0].external_job_id


class FakeSource:
    def __init__(self, fail: str | None = None) -> None:
        self.fail = fail
        self.boards: dict[str, str] = {}
        self.next_cursor = None

    async def fetch_jobs(self, limit: int = 100, page: int = 1) -> list[NormalizedJob]:
        board = next(iter(self.boards))
        if board == self.fail:
            raise RuntimeError("board renamed")
        url = f"https://jobs.ashbyhq.com/{board}/0f1e2d3c-aaaa-bbbb-cccc-1234567890ab"
        return [NormalizedJob.model_validate({"source_name": "ashby", "source_job_id": f"{board}-1",
                                              "title": "Backend Engineer", "original_url": url,
                                              "application_url": url + "/application", "company_name": None})]


@pytest.mark.parametrize("cls,pref", [(AshbyAdapter, "ashby_boards"), (SmartRecruitersAdapter, "smartrecruiters_boards")])
async def test_board_sources_read_only_allowlisted_boards_and_isolate_failures(cls, pref, monkeypatch):
    adapter = cls()
    adapter.configure({"preferences": {pref: {"acme": "Acme", "broken": None, "bad token!": "x"}}})
    assert set(adapter.boards) >= {"acme", "broken"} and "bad token!" not in adapter.boards
    monkeypatch.setattr(adapter, "source", lambda _client: FakeSource(fail="broken"))
    adapter.http_client = client(lambda r: httpx.Response(500))
    jobs = await adapter.fetch("engineer", 10)
    assert [(j.external_job_id, j.company) for j in jobs if j.external_job_id.startswith("acme")] == [
        ("acme-1", "Acme")]
    assert job_id_from_url("ashby", jobs[0].url) == "0f1e2d3c-aaaa-bbbb-cccc-1234567890ab"


def test_preferences_accept_the_new_board_lists():
    prefs = JobSearchPreferences.model_validate({"ashby_boards": {"acme": "Acme"},
                                                 "smartrecruiters_boards": {"Bosch": None}})
    assert prefs.ashby_boards == {"acme": "Acme"} and prefs.smartrecruiters_boards == {"Bosch": None}


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, sql: str, *args: Any) -> str:
        self.executed.append((sql, args))
        return "INSERT 0 5"

    async def fetch(self, *args: Any) -> list[Any]:
        return []

    async def fetchval(self, *args: Any) -> Any:
        return None


async def test_postgres_store_self_seeds_missing_portal_rows_once():
    connection = FakeConnection()
    store = PostgresStore(connection, owns_connection=False)
    await store.list_rules()
    await store.list_rules()
    inserts = [args for sql, args in connection.executed if "INSERT INTO public.portal_rules" in sql]
    assert len(inserts) == 1 and set(inserts[0][0]) == set(PORTALS) and "ON CONFLICT" in connection.executed[0][0]
