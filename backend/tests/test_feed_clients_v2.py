"""v2-owned feed HTTP clients (browser_v2/adapters/feed_clients): no network, httpx.MockTransport only."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from backend.app.browser_v2.adapters.feed_clients import (
    ArbeitnowClient,
    AshbyClient,
    ConditionalHttp,
    GreenhouseClient,
    HackerNewsClient,
    HttpStatusError,
    LeverClient,
    RateLimited,
    RawPosting,
    RemotiveClient,
    ResponseTooLarge,
    SmartRecruitersClient,
    Validators,
)
from backend.app.browser_v2.adapters.feed_clients.http import parse_retry_after
from backend.app.browser_v2.adapters.feeds import USER_AGENT

URL = "https://feeds.example.org/jobs.json"
POSTED = "2026-11-20T10:00:00Z"
POSTED_DT = datetime(2026, 11, 20, 10, tzinfo=UTC)
LEVER_ID = "0f1e2d3c-aaaa-bbbb-cccc-1234567890ab"


def mock(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def conditional(handler: Any, **kwargs: Any) -> ConditionalHttp:
    return ConditionalHttp(mock(handler), min_interval=0.0, **kwargs)


# --- ConditionalHttp --------------------------------------------------------------------------------------
async def test_validators_are_sent_as_conditional_headers_and_304_is_not_modified():
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(304, headers={"etag": '"v2"'})

    previous = Validators(etag='"v1"', last_modified="Wed, 25 Nov 2026 10:00:00 GMT", body_hash="abc")
    result = await conditional(handler).get(URL, validators=previous)
    assert seen[0]["if-none-match"] == '"v1"' and seen[0]["if-modified-since"] == previous.last_modified
    assert seen[0]["user-agent"] == USER_AGENT and seen[0]["accept"] == "application/json"
    assert result.not_modified and result.body is None and result.status == 304
    assert result.validators == Validators(etag='"v2"', last_modified=previous.last_modified, body_hash="abc")


async def test_first_fetch_sends_no_conditional_headers_and_returns_server_validators():
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(200, content=b'{"a":1}', headers={"etag": '"e1"', "last-modified": "x"})

    result = await conditional(handler).get(URL)
    assert "if-none-match" not in seen[0] and "if-modified-since" not in seen[0]
    assert result.body == b'{"a":1}' and not result.not_modified
    assert result.validators.etag == '"e1"' and result.validators.last_modified == "x"
    assert result.validators.body_hash and len(result.validators.body_hash) == 64


async def test_body_hash_short_circuits_when_the_server_sends_no_validators():
    body = {"value": b'{"jobs":[]}'}
    http = conditional(lambda request: httpx.Response(200, content=body["value"]))
    first = await http.get(URL)
    again = await http.get(URL, validators=first.validators)
    assert again.not_modified and again.body is None
    assert again.validators.body_hash == first.validators.body_hash
    body["value"] = b'{"jobs":[1]}'
    changed = await http.get(URL, validators=first.validators)
    assert not changed.not_modified and changed.body == b'{"jobs":[1]}'


async def test_retry_after_raises_rate_limited_with_a_capped_delay():
    http = conditional(lambda request: httpx.Response(429, headers={"retry-after": "120"}))
    with pytest.raises(RateLimited) as limited:
        await http.get(URL)
    assert limited.value.retry_after == 120.0 and limited.value.status == 429
    http = conditional(lambda request: httpx.Response(503, headers={"retry-after": "99999"}))
    with pytest.raises(RateLimited) as unavailable:
        await http.get(URL)
    assert unavailable.value.retry_after == 3600.0 and unavailable.value.status == 503
    with pytest.raises(HttpStatusError) as failed:
        await conditional(lambda request: httpx.Response(503)).get(URL)
    assert failed.value.status == 503 and not isinstance(failed.value, RateLimited)
    now = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
    assert parse_retry_after("Fri, 27 Nov 2026 10:01:00 GMT", now) == 60.0
    assert parse_retry_after("soon", now) is None and parse_retry_after("-5", now) == 0.0


async def test_responses_over_the_size_cap_are_rejected():
    http = conditional(lambda request: httpx.Response(200, content=b"x" * 2048))
    with pytest.raises(ResponseTooLarge):
        await http.get(URL, max_bytes=1024)
    assert (await http.get(URL, max_bytes=4096)).body == b"x" * 2048


async def test_requests_to_one_host_are_spaced_by_the_injected_clock():
    clock = FakeClock()
    http = ConditionalHttp(mock(lambda request: httpx.Response(200, content=b"{}")), clock=clock, sleep=clock.sleep)
    await http.get(URL)
    clock.now += 0.25
    await http.get(URL)
    await http.get("https://other.example.org/feed")  # another host is not delayed
    assert clock.sleeps == [pytest.approx(0.75)]
    await http.get(URL)
    assert clock.sleeps == [pytest.approx(0.75), pytest.approx(1.0)]


# --- source request semantics (ported v1 behaviour) ---------------------------------------------------------
async def test_sources_retry_one_5xx_but_never_429_and_remotive_never_retries():
    calls: list[str] = []

    def flaky(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if len(calls) == 1:
            return httpx.Response(502)
        return httpx.Response(200, json={"jobs": []})

    assert await GreenhouseClient(mock(flaky), board_token="acme").fetch_jobs(limit=10) == []
    assert len(calls) == 2
    calls.clear()
    with pytest.raises(HttpStatusError):
        await RemotiveClient(mock(flaky)).fetch_jobs(limit=10)
    assert len(calls) == 1
    calls.clear()

    def limited(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(429, headers={"retry-after": "30"})

    with pytest.raises(RateLimited):
        await GreenhouseClient(mock(limited), board_token="acme").fetch_jobs(limit=10)
    assert len(calls) == 1


# --- parsing goldens (one per source; synthetic data) ------------------------------------------------------
async def test_greenhouse_golden():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true"
        return httpx.Response(200, json={"jobs": [
            {"id": 4012345, "title": " Backend Engineer ", "absolute_url": "https://boards.greenhouse.io/acme/jobs/4012345",
             "location": {"name": "Remote - India"}, "content": "&lt;p&gt;Python&lt;/p&gt;", "first_published": POSTED},
            {"id": True, "title": "Bad id", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1"},
            {"id": 6, "title": "Plain http", "absolute_url": "http://boards.greenhouse.io/acme/jobs/6"},
        ]})

    client = GreenhouseClient(mock(handler), board_token="acme", company_name="Acme")
    jobs = await client.fetch_jobs(board_token="acme", limit=100, page=1)
    assert jobs == [RawPosting(
        source_job_id="4012345", title="Backend Engineer", company_name="Acme",
        original_url="https://boards.greenhouse.io/acme/jobs/4012345",
        application_url="https://boards.greenhouse.io/acme/jobs/4012345", description="&lt;p&gt;Python&lt;/p&gt;",
        date_posted=POSTED_DT, location="Remote - India", remote_type="remote",
        source_fields={"id": 4012345, "title": " Backend Engineer ",
                       "absolute_url": "https://boards.greenhouse.io/acme/jobs/4012345",
                       "location": {"name": "Remote - India"}, "first_published": POSTED})]
    assert len(client.record_errors) == 2 and client.next_cursor is None


async def test_lever_golden():
    url = f"https://jobs.lever.co/acme/{LEVER_ID}"

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.lever.co/v0/postings/acme?mode=json"
        return httpx.Response(200, json=[
            {"id": LEVER_ID, "text": "Platform Engineer", "hostedUrl": url, "applyUrl": url + "/apply",
             "createdAt": 1795000000000, "categories": {"location": "Bengaluru", "commitment": "Full-time"},
             "descriptionPlain": "Go and Python", "workplaceType": "hybrid", "salaryDescriptionPlain": "INR 20L"},
            {"id": "abc", "text": "Wrong board", "hostedUrl": "https://jobs.lever.co/other/abc"},
        ])

    client = LeverClient(mock(handler), region="global", boards={"acme": "Acme"})
    jobs = await client.fetch_jobs(limit=100, page=1)
    assert len(jobs) == 1 and len(client.record_errors) == 1
    job = jobs[0]
    assert (job.source_job_id, job.title, job.company_name, job.original_url, job.application_url) == (
        LEVER_ID, "Platform Engineer", "Acme", url, url + "/apply")
    assert (job.description, job.location, job.remote_type, job.salary_raw, job.date_posted) == (
        "Go and Python", "Bengaluru", "hybrid", "INR 20L", None)
    assert job.source_fields["createdAt"] == 1795000000000 and "descriptionPlain" not in job.source_fields


async def test_ashby_golden():
    job_id = "11111111-2222-3333-4444-555555555555"
    url = f"https://jobs.ashbyhq.com/acme/{job_id}"

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.ashbyhq.com/posting-api/job-board/acme?includeCompensation=true"
        return httpx.Response(200, json={"apiVersion": "1", "jobs": [
            {"isListed": True, "jobUrl": url, "applyUrl": url + "/application", "title": "Data Engineer",
             "descriptionHtml": "<p>SQL</p>", "location": "Remote", "workplaceType": "Remote", "isRemote": True,
             "publishedAt": POSTED, "compensation": {"scrapeableCompensationSalarySummary": "$100K - $120K"}},
            {"isListed": False, "jobUrl": url, "title": "Hidden"},
        ]})

    jobs = await AshbyClient(mock(handler), boards={"acme": "Acme"}).fetch_jobs(limit=100, page=1)
    assert [(j.source_job_id, j.title, j.company_name, j.application_url, j.description, j.remote_type,
             j.salary_raw, j.date_posted) for j in jobs] == [
        (job_id, "Data Engineer", "Acme", url + "/application", "<p>SQL</p>", "remote", "$100K - $120K", POSTED_DT)]


async def test_smartrecruiters_golden():
    listing = "https://api.smartrecruiters.com/v1/companies/acme/postings"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/postings"):
            assert str(request.url) == listing + "?offset=0&limit=100"
            return httpx.Response(200, json={"content": [{"id": "744000012345"}], "totalFound": 1,
                                             "offset": 0, "limit": 100})
        assert str(request.url) == listing + "/744000012345"
        return httpx.Response(200, json={
            "id": "744000012345", "active": True, "company": {"identifier": "acme"}, "name": "QA Engineer",
            "postingUrl": "https://jobs.smartrecruiters.com/acme/744000012345-qa-engineer",
            "applyUrl": "https://jobs.smartrecruiters.com/acme/744000012345?oga=true",
            "location": {"city": "Pune", "country": "in", "remote": True}, "releasedDate": POSTED,
            "jobAd": {"sections": {"jobDescription": {"text": "<p>Tests</p>"}, "qualifications": {"text": "Py"}}}})

    jobs = await SmartRecruitersClient(mock(handler), boards={"acme": "Acme"}).fetch_jobs(limit=100, page=1)
    assert jobs == [RawPosting(
        source_job_id="744000012345", title="QA Engineer", company_name="Acme",
        original_url="https://jobs.smartrecruiters.com/acme/744000012345-qa-engineer",
        application_url="https://jobs.smartrecruiters.com/acme/744000012345?oga=true",
        description="<p>Tests</p>\n\nPy", date_posted=POSTED_DT, location="Pune, in", remote_type="remote")]


async def test_remotive_golden():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://remotive.com/api/remote-jobs?category=software-dev&limit=100&search="
        return httpx.Response(200, json={"jobs": [
            {"id": 9988, "url": "https://remotive.com/remote-jobs/software-dev/python-developer-9988",
             "title": "Python Developer", "company_name": "Acme Global", "candidate_required_location": "Worldwide",
             "description": "<p>APIs</p>", "publication_date": POSTED, "salary": "$50k - $60k per year"}]})

    jobs = await RemotiveClient(mock(handler)).fetch_jobs(category="software-dev", limit=100, page=1)
    assert jobs == [RawPosting(
        source_job_id="9988", title="Python Developer", company_name="Acme Global",
        original_url="https://remotive.com/remote-jobs/software-dev/python-developer-9988",
        description="<p>APIs</p>", date_posted=POSTED_DT, location="Worldwide", remote_type="remote",
        salary_raw="$50k - $60k per year")]


async def test_arbeitnow_golden():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://www.arbeitnow.com/api/job-board-api?page=1"
        return httpx.Response(200, json={"links": {"next": "https://www.arbeitnow.com/api/job-board-api?page=2"},
                                         "data": [{"slug": "dev-acme-1", "url": "https://www.arbeitnow.com/jobs/dev-acme-1",
                                                   "title": "Developer", "company_name": "Acme", "remote": True,
                                                   "description": "<p>d</p>", "location": "Berlin",
                                                   "created_at": 1795000000}]})

    client = ArbeitnowClient(mock(handler))
    jobs = await client.fetch_jobs(page=1, limit=100)
    assert client.next_cursor == "2"
    assert [(j.source_job_id, j.title, j.company_name, j.location, j.remote_type, j.date_posted) for j in jobs] == [
        ("dev-acme-1", "Developer", "Acme", "Berlin", "remote", datetime.fromtimestamp(1795000000, UTC))]


async def test_hacker_news_golden_keeps_comment_html():
    comment = ('Acme | Backend Engineer | Remote | $120k - $150k<p>Apply at '
               '<a href="https://boards.greenhouse.io/acme/jobs/123456">here</a></p>')

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/search_by_date":
            return httpx.Response(200, json={"hits": [{"objectID": "40001", "title": "Ask HN: Who is hiring?"}]})
        assert request.url.params["numericFilters"] == "parent_id=40001" and request.url.params["page"] == "0"
        return httpx.Response(200, json={"nbPages": 1, "hits": [
            {"objectID": "40002", "parent_id": 40001, "comment_text": comment, "created_at": POSTED},
            {"objectID": "40003", "parent_id": 40001, "comment_text": "no pipes here"}]})

    client = HackerNewsClient(mock(handler))
    jobs = await client.fetch_jobs(limit=100, page=1)
    assert [(j.source_job_id, j.company_name, j.title, j.location, j.remote_type, j.salary_raw, j.original_url)
            for j in jobs] == [("40002", "Acme", "Backend Engineer", "Remote", "remote", "$120k - $150k",
                                "https://news.ycombinator.com/item?id=40002")]
    assert client.comment_html["40002"] == comment and client.next_cursor is None
