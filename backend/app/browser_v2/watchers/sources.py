"""HTTP source fetchers for the fast-poll watchers: one conditional GET -> FeedJobs.

Each fetcher reuses the v2 feed clients' fixed hosts and per-record validation, but issues the
request itself through `ConditionalHttp` with the validators persisted in `watcher_state`, so
an unchanged board costs one 304 (or an unchanged body hash) and no parsing.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from backend.app.browser_v2.adapters.feed_clients.arbeitnow import (
    FEED_URL as ARBEITNOW_URL,
)
from backend.app.browser_v2.adapters.feed_clients.arbeitnow import ArbeitnowClient
from backend.app.browser_v2.adapters.feed_clients.ashby import AshbyClient
from backend.app.browser_v2.adapters.feed_clients.base import (
    RECORD_ERRORS,
    FeedSourceError,
)
from backend.app.browser_v2.adapters.feed_clients.greenhouse import (
    BOARD_TOKEN,
    GreenhouseClient,
)
from backend.app.browser_v2.adapters.feed_clients.greenhouse import (
    feed_url as greenhouse_url,
)
from backend.app.browser_v2.adapters.feed_clients.hacker_news import HackerNewsClient
from backend.app.browser_v2.adapters.feed_clients.http import (
    ConditionalHttp,
    FetchResult,
    Validators,
)
from backend.app.browser_v2.adapters.feed_clients.lever import LeverClient
from backend.app.browser_v2.adapters.feed_clients.models import RawPosting
from backend.app.browser_v2.adapters.feed_clients.remotive import (
    FEED_URL as REMOTIVE_URL,
)
from backend.app.browser_v2.adapters.feed_clients.remotive import RemotiveClient
from backend.app.browser_v2.adapters.feeds import FeedJob
from backend.app.browser_v2.adapters.greenhouse import (
    MAX_BOARDS,
    board_map,
    hosted_apply_url,
)
from backend.app.browser_v2.adapters.himalayas import SEARCH_URL as HIMALAYAS_URL
from backend.app.browser_v2.adapters.himalayas import parse_jobs as parse_himalayas
from backend.app.browser_v2.adapters.lever import created_at
from backend.app.browser_v2.adapters.public_sources import employer_link, to_feed_job
from backend.app.browser_v2.adapters.watchlist import active_boards
from backend.app.browser_v2.adapters.we_work_remotely import MAX_BYTES as WWR_MAX_BYTES
from backend.app.browser_v2.adapters.we_work_remotely import parse_rss
from backend.app.browser_v2.watchers.models import Fetched, Fetcher

RSS_ACCEPT = "application/rss+xml, application/xml;q=0.9, text/xml;q=0.8"
HN_EXCLUDE = frozenset({"news.ycombinator.com", "hn.algolia.com"})


def configured_boards(setting: str, preference: str, prefs: Mapping[str, Any]) -> dict[str, str | None]:
    """Same board allowlist the adapters build in `configure`: <SETTING> + preferences.<name>_boards."""
    boards: dict[str, str | None] = {}
    try:
        from backend.app.core.config import get_settings

        boards |= board_map(getattr(get_settings(), setting, None))
    except Exception:  # noqa: BLE001, S110 - settings are optional for the v2 worker
        pass
    boards |= board_map(prefs.get(preference))
    boards = active_boards(preference.removesuffix("_boards"), boards, prefs)  # Milestone 2: owner-paused boards
    return dict(list(boards.items())[:MAX_BOARDS])


def _json(result: FetchResult, kind: type) -> Any:
    try:
        data = json.loads(result.body or b"")
    except (ValueError, UnicodeError):
        raise FeedSourceError("provider returned invalid JSON") from None
    if not isinstance(data, kind):
        raise FeedSourceError("provider returned an invalid top-level schema")
    return data


def _parse_all(records: Any, parse: Callable[[Any], RawPosting]) -> list[RawPosting]:
    """Per-record validation: a bad record is dropped, a bad collection fails the poll."""
    if not isinstance(records, list):
        raise FeedSourceError("provider returned an invalid record collection")
    output = []
    for record in records:
        try:
            output.append(parse(record))
        except RECORD_ERRORS:
            continue
    return output


def _fetched(result: FetchResult, jobs: list[FeedJob] | None) -> Fetched:
    return Fetched(result.status, result.validators, None if result.not_modified else jobs)


def greenhouse_fetcher(token: str, company: str | None) -> Fetcher:
    async def fetch(http: ConditionalHttp, client: Any, validators: Validators | None) -> Fetched:
        if not BOARD_TOKEN.fullmatch(token):
            raise FeedSourceError("Invalid board token")
        result = await http.get(greenhouse_url(token), validators=validators)  # list view: no `content`
        if result.not_modified:
            return _fetched(result, None)
        source = GreenhouseClient(client, board_token=token, company_name=company, http=http)
        raws = _parse_all(_json(result, dict).get("jobs"), lambda item: source.parse(item, token))
        jobs = [FeedJob(external_job_id=str(r.source_job_id), url=r.original_url, title=r.title,
                        company=r.company_name or company or token,
                        apply_url=hosted_apply_url(token, str(r.source_job_id), r.application_url or r.original_url),
                        posted_at=r.date_posted, location=r.location) for r in raws if r.source_job_id]
        return _fetched(result, jobs)

    return fetch


def lever_fetcher(board: str, company: str | None) -> Fetcher:
    async def fetch(http: ConditionalHttp, client: Any, validators: Validators | None) -> Fetched:
        source = LeverClient(client, http=http, boards={board: company or board})
        result = await http.get(source.feed_url(board), params=source.feed_params(), validators=validators)
        if result.not_modified:
            return _fetched(result, None)
        raws = _parse_all(_json(result, list), lambda item: source.parse(item, board, company or board))
        jobs = [FeedJob(external_job_id=str(r.source_job_id), url=r.original_url, title=r.title,
                        company=r.company_name or company or board, apply_url=r.application_url or r.original_url,
                        posted_at=created_at(dict(r.source_fields or {})), location=r.location)
                for r in raws if r.source_job_id]
        return _fetched(result, jobs)

    return fetch


def ashby_fetcher(board: str, company: str | None) -> Fetcher:
    async def fetch(http: ConditionalHttp, client: Any, validators: Validators | None) -> Fetched:
        source = AshbyClient(client, http=http, boards={board: company or board})
        result = await http.get(source.feed_url(board), params=source.feed_params(), validators=validators)
        if result.not_modified:
            return _fetched(result, None)
        records = source.records(_json(result, dict))
        if not isinstance(records, list):
            raise FeedSourceError("Invalid ATS jobs collection")
        raws = _parse_all(source.visible(records), lambda item: source.parse(item, board, company or board))
        return _fetched(result, [to_feed_job(r, company or board) for r in raws if r.source_job_id])

    return fetch


async def fetch_remotive(http: ConditionalHttp, client: Any, validators: Validators | None) -> Fetched:
    result = await http.get(REMOTIVE_URL, params={"category": "software-dev", "limit": 100, "search": ""},
                            validators=validators)
    if result.not_modified:
        return _fetched(result, None)
    source = RemotiveClient(client, http=http)
    raws = _parse_all(_json(result, dict).get("jobs"), source.parse)
    return _fetched(result, [to_feed_job(r, apply_url=None) for r in raws if r.source_job_id])


async def fetch_arbeitnow(http: ConditionalHttp, client: Any, validators: Validators | None) -> Fetched:
    result = await http.get(ARBEITNOW_URL, params={"page": 1}, validators=validators)
    if result.not_modified:
        return _fetched(result, None)
    source = ArbeitnowClient(client, http=http)
    raws = _parse_all(_json(result, dict).get("data"), lambda item: source.parse(item, 1))
    return _fetched(result, [to_feed_job(r, apply_url=None) for r in raws if r.source_job_id])


async def fetch_hacker_news(http: ConditionalHttp, client: Any, validators: Validators | None) -> Fetched:
    """Two dependent reads (story, then comments): no validators; the 3 h cadence keeps it polite."""
    source = HackerNewsClient(client, http=http)
    raws = await source.fetch_jobs(limit=100, page=1)
    jobs = [to_feed_job(r, apply_url=employer_link(source.comment_html.get(str(r.source_job_id)) or r.description,
                                                   exclude_hosts=HN_EXCLUDE) or "")
            for r in raws if r.source_job_id]
    return Fetched(200, None, jobs)


def himalayas_fetcher(role: str) -> Fetcher:
    async def fetch(http: ConditionalHttp, client: Any, validators: Validators | None) -> Fetched:
        result = await http.get(HIMALAYAS_URL, params={"q": role, "sort": "recent"}, validators=validators)
        if result.not_modified:
            return _fetched(result, None)
        return _fetched(result, parse_himalayas(_json(result, dict)))

    return fetch


def wwr_fetcher(url: str) -> Fetcher:
    async def fetch(http: ConditionalHttp, client: Any, validators: Validators | None) -> Fetched:
        result = await http.get(url, validators=validators, accept=RSS_ACCEPT, max_bytes=WWR_MAX_BYTES)
        if result.not_modified:
            return _fetched(result, None)
        try:
            jobs = parse_rss(result.body or b"")
        except Exception as exc:
            raise FeedSourceError("invalid RSS document") from exc
        return _fetched(result, jobs)

    return fetch
