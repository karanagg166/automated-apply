"""Phase 6A: multi-resume picker, failure-screenshot ring buffer, nightly digest, event bus backends,
SFT exporter, live quota caps, worker hooks (pause, auto-login, mail watchers, digest) and the new
/api/v1/v2 routes."""

from __future__ import annotations

import json
import os
import stat
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.app.ai_v2.embeddings import DeterministicTestEmbedder
from backend.app.ai_v2.runtime import AIRuntime
from backend.app.ai_v2.semantic_cache import MemoryCacheStore
from backend.app.ai_v2.sft_export import export_sft_dataset
from backend.app.ai_v2.usage import MemoryUsageStore
from backend.app.api.v1.automation_v2 import get_ai_runtime, get_v2_store
from backend.app.browser_v2.adapters.base import AuthStatus, JobListing, SessionCheck
from backend.app.browser_v2.digest import DigestScheduler, build_digest, digest_hour
from backend.app.browser_v2.quota import QuotaHitProcessor, fallback_daily_cap
from backend.app.browser_v2.receipts import (
    FAILURE_KEEP,
    prune_failures,
    screenshot_path,
)
from backend.app.browser_v2.resume import pick_resume
from backend.app.browser_v2.rules import PortalRules
from backend.app.browser_v2.service import BrowserService
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore
from backend.app.browser_v2.worker import Worker
from backend.app.events_v2.bus import (
    CloudAmqpBus,
    InProcessBus,
    PostgresBus,
    UpstashRedisBus,
    build_event_bus,
    bus_status,
    clean_payload,
)
from backend.app.mail_v2.reader import MailEventStore, ScanReport
from backend.app.main import app
from backend.tests.phase6a_fixtures import PDF

IST_EVENING = datetime(2026, 11, 26, 16, 0, tzinfo=UTC)  # 21:30 IST
BASE = "/api/v1/v2"


# --- resume picker ---------------------------------------------------------------------------------
def write_pdf(path):
    path.write_bytes(PDF)
    return str(path)


def test_resume_picker_scores_title_and_jd_and_falls_back(tmp_path):
    files = {"backend": write_pdf(tmp_path / "b.pdf"), "fullstack": write_pdf(tmp_path / "f.pdf"),
             "ai": {"path": write_pdf(tmp_path / "a.pdf"), "keywords": ["rag"]}}
    assert pick_resume(files, title="Backend Engineer (Go)", description="APIs, Postgres").label == "backend"
    assert pick_resume(files, title="GenAI Engineer", description="LLM agents with RAG").label == "ai"
    assert pick_resume(files, title="Full Stack Developer", description="React + Node.js").label == "fullstack"
    tie = pick_resume({**files, "fullstack": {"path": files["fullstack"], "primary": True}},
                      title="Engineer", description="general")
    assert (tie.label, tie.reason) == ("fullstack", "primary_variant")
    fallback = write_pdf(tmp_path / "fallback.pdf")
    assert pick_resume({"x": str(tmp_path / "missing.pdf")}, title="t", description=None,
                       fallback_path=fallback).path == fallback
    not_pdf = tmp_path / "cv.docx"
    not_pdf.write_bytes(b"PK")
    assert pick_resume({"x": str(not_pdf)}, title="t", description=None).reason == "no_resume_configured"


# --- failure screenshot ring buffer ----------------------------------------------------------------------
def test_ring_buffer_keeps_newest_20_failures_and_never_touches_receipts(tmp_path):
    root = tmp_path / "receipts"
    failures = root / "failures"
    failures.mkdir(parents=True)
    (root / "naukri").mkdir()
    receipt = root / "naukri" / "naukri-1-receipt.png"
    receipt.write_bytes(b"x")
    for index in range(30):
        path = failures / f"f{index:02d}.png"
        path.write_bytes(b"x")
        os.utime(path, (time.time() - 1000 + index, time.time() - 1000 + index))
    assert prune_failures(failures) == 10 and len(list(failures.iterdir())) == FAILURE_KEEP
    assert sorted(p.name for p in failures.iterdir())[0] == "f10.png" and receipt.exists()
    assert prune_failures(root / "naukri") == 0  # refuses any folder but failures/
    assert screenshot_path("greenhouse", "1", "receipt", root=root).parent == root / "greenhouse"
    assert screenshot_path("greenhouse", "1", "question", root=root).parent == failures


# --- nightly digest ------------------------------------------------------------------------------------------
async def test_digest_content_and_once_per_day_schedule():
    store = MemoryStore()
    record = await store.upsert_discovered(JobListing(platform="naukri", external_job_id="1", url="https://x/1"))
    record = await store.transition(record, S.APPLYING, "apply_started")
    await store.transition(record, S.APPLIED, "confirmed", receipt={"source": "t"})
    queued = await store.upsert_discovered(JobListing(platform="naukri", external_job_id="2", url="https://x/2"))
    queued = await store.transition(queued, S.SCORED, "passed")
    queued = await store.transition(queued, S.QUOTA_HIT_PENDING, "dashboard_daily_limit")
    await store.transition(queued, S.DRAFTED_AND_QUEUED, "quota_hit_queued_no_email", retry_after=IST_EVENING)
    text = await build_digest(store, datetime.now(UTC))
    assert "Applied today: 1" in text and "Naukri: 1/50" in text and "Queued for tomorrow's retry: 1" in text
    assert "never sent automatically" in text and "Open HITL requests: 0" in text
    scheduler = DigestScheduler(store, hour=21)
    assert not await scheduler.due(IST_EVENING - timedelta(hours=1))  # 20:30 IST
    assert await scheduler.due(IST_EVENING)
    await scheduler.mark_sent(IST_EVENING)
    assert not await scheduler.due(IST_EVENING + timedelta(minutes=30))
    assert not await DigestScheduler(store, hour=21).due(IST_EVENING)  # restart-safe (telegram_v2_state)
    assert digest_hour({"DIGEST_DISABLED": "true"}) is None and digest_hour({"DIGEST_HOUR_IST": "7"}) == 7
    assert digest_hour({"DIGEST_HOUR_IST": "99"}) == 21


# --- event bus ---------------------------------------------------------------------------------------------------
async def test_in_process_and_postgres_bus_dispatch_and_scrub():
    bus = PostgresBus(None)
    seen = []

    async def handler(topic, payload):
        seen.append((topic, payload))

    bus.subscribe("job.applied", handler)
    bus.subscribe("*", handler)
    await bus.publish("job.applied", {"platform": "naukri", "otp_code": "482913", "cookie": "x", "title": "SDE"})
    await bus.drain()
    assert seen == [("job.applied", {"platform": "naukri", "title": "SDE"})] * 2
    with pytest.raises(ValueError):
        await bus.publish("job.deleted", {})
    with pytest.raises(ValueError):
        bus.subscribe("nope", handler)
    assert clean_payload({"body": "secret", "a": 1}) == {"a": 1}

    class Conn:
        def __init__(self):
            self.calls = []

        async def execute(self, *args):
            self.calls.append(args)

    conn = Conn()
    notify = PostgresBus(conn)
    await notify.publish("hitl.opened", {"platform": "naukri"})
    assert conn.calls == [("SELECT pg_notify($1, $2)", "automated_apply_events", '{"topic": "hitl.opened"}')]
    status = await notify.status()
    assert status["backend"] == "postgres" and status["remote"]["pg_notify"] is True


async def test_cloudamqp_http_publish_and_graceful_offline_fallback():
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/get"):
            return httpx.Response(200, json=[{"payload": json.dumps({"topic": "job.applied"})}])
        return httpx.Response(200, json={"routed": True})

    url = "amqps://user:TEST_FAKE_TOKEN_ONLY@rabbit.example.com/vhost1"
    bus = CloudAmqpBus(url, transport=httpx.MockTransport(handler))
    await bus.publish("job.applied", {"platform": "lever"})
    assert requests[0].url.path == "/api/exchanges/vhost1/amq.default/publish"
    assert json.loads(requests[0].content)["routing_key"] == "automated-apply.events"
    assert (await bus.fetch_remote())[0]["topic"] == "job.applied"
    assert (await bus.status())["remote"]["ok"] is True
    await bus.close()
    offline = CloudAmqpBus(url, transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    local = []

    async def collect(topic, payload):
        local.append(topic)

    offline.subscribe("job.applied", collect)
    for _ in range(6):
        await offline.publish("job.applied", {})
    await offline.drain()
    assert len(local) == 6 and offline.remote_errors == 5 and (await offline.status())["healthy"] is False
    await offline.close()
    with pytest.raises(ValueError):
        CloudAmqpBus("http://rabbit.example.com/x")


async def test_upstash_redis_rest_streams():
    commands = []

    def handler(request):
        body = json.loads(request.content)
        commands.append(body)
        assert request.headers["authorization"] == "Bearer TEST_FAKE_TOKEN_ONLY"
        if body[0] == "XREVRANGE":
            return httpx.Response(200, json={"result": [["1-0", ["topic", "hitl.resolved", "event",
                                                                 json.dumps({"topic": "hitl.resolved"})]]]})
        return httpx.Response(200, json={"result": "1-0"})

    bus = UpstashRedisBus("https://eu1-x.upstash.io", "TEST_FAKE_TOKEN_ONLY", transport=httpx.MockTransport(handler))
    await bus.publish("hitl.resolved", {"ref": "abcd"})
    assert commands[0][:6] == ["XADD", "automated-apply:events", "MAXLEN", "~", "1000", "*"]
    assert (await bus.fetch_remote())[0]["topic"] == "hitl.resolved"
    await bus.close()


async def test_build_event_bus_selection_and_status():
    assert isinstance(build_event_bus({}), PostgresBus)
    assert isinstance(build_event_bus({"EVENT_BUS_BACKEND": "cloudamqp"}), PostgresBus)  # unconfigured -> fallback
    assert isinstance(build_event_bus({"EVENT_BUS_BACKEND": "cloudamqp",
                                       "CLOUDAMQP_URL": "amqps://u:TEST_FAKE_TOKEN_ONLY@h.example.com/v"}),
                      CloudAmqpBus)
    assert isinstance(build_event_bus({"EVENT_BUS_BACKEND": "upstash_redis",
                                       "UPSTASH_REDIS_REST_URL": "https://x.upstash.io",
                                       "UPSTASH_REDIS_REST_TOKEN": "TEST_FAKE_TOKEN_ONLY"}), UpstashRedisBus)
    assert isinstance(build_event_bus({"EVENT_BUS_BACKEND": "upstash_redis",
                                       "UPSTASH_REDIS_REST_URL": "http://insecure", "UPSTASH_REDIS_REST_TOKEN": "t"}),
                      PostgresBus)
    status = await bus_status(build_event_bus({"EVENT_BUS_BACKEND": "cloudamqp"}),
                              {"EVENT_BUS_BACKEND": "cloudamqp"})
    assert status["fell_back"] is True and status["backend"] == "postgres" and "job.applied" in status["topics"]
    assert isinstance(InProcessBus(), InProcessBus)


# --- SFT exporter ---------------------------------------------------------------------------------------------
async def test_sft_export_is_verified_only_pii_scrubbed_jsonl(tmp_path):
    ai = AIRuntime.build(MemoryCacheStore(), MemoryUsageStore(), embedder=DeterministicTestEmbedder(), env={})
    await ai.cache.store_verified_user_answer("What is your notice period?", "Immediate")
    await ai.cache.store_verified_user_answer("Share a contact number", "Call me on +91 98450 12345")
    await ai.cache.put("screening_qa", "Are you comfortable with on-call?", "Yes", "llm")  # not verified -> skipped
    profile = {"full_name": "Test Candidate", "phone": "+91 98450 12345", "email": "candidate@example.com"}
    reviewed = [("Why do you want to join?", "I'm Test Candidate and I love backend work"),
                ("What is your notice period?", "duplicate ignored")]
    out = tmp_path / "sft" / "dataset.jsonl"
    result = await export_sft_dataset(out, cache_store=ai.cache.store, reviewed=reviewed, profile=profile)
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert result["examples"] == 3 == len(lines) and result["pii_scrubbed"]
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    text = out.read_text()
    assert "98450" not in text and "Test Candidate" not in text and "on-call" not in text
    assert lines[0]["messages"][1]["role"] == "user" and lines[0]["messages"][2]["role"] == "assistant"
    assert result["by_source"] == {"semantic_cache_user": 2, "reviewed_answer_draft": 1}
    with pytest.raises(ValueError):
        await export_sft_dataset(tmp_path / "x.json", cache_store=ai.cache.store, reviewed=[], profile={})


# --- live quota caps from portal_rules ------------------------------------------------------------------------
async def test_quota_caps_come_from_portal_rules_with_env_fallback(monkeypatch):
    monkeypatch.setenv("QUOTA_FALLBACK_DAILY_CAP", "7")
    assert fallback_daily_cap() == 7 and fallback_daily_cap(PortalRules("naukri")) == 7
    assert fallback_daily_cap(PortalRules("naukri", quota_fallback_daily_cap=3)) == 3
    store = MemoryStore()
    for i in range(4):
        record = await store.upsert_discovered(JobListing(platform="naukri", external_job_id=f"q{i}",
                                                          url=f"https://x/{i}", title="SDE", company="Acme"))
        record = await store.transition(record, S.SCORED, "passed")
        await store.transition(record, S.QUOTA_HIT_PENDING, "dashboard_daily_limit")
    rules = PortalRules("naukri", enabled=True, quota_drafts_per_cycle=2)
    report = await QuotaHitProcessor(store).process(rules, {}, quota_exhausted=True)
    assert report.queued == 2 and await store.count_state(S.QUOTA_HIT_PENDING) == 2
    zero = await QuotaHitProcessor(store).process(PortalRules("naukri", quota_drafts_per_cycle=0), {},
                                                  quota_exhausted=True)
    assert zero.queued == 0


# --- worker hooks ------------------------------------------------------------------------------------------------
class Manager:
    running = True

    @asynccontextmanager
    async def job(self):
        yield object()

    async def maybe_recycle_between_jobs(self, max_age_sec=10800):
        return False

    async def close(self):
        return None


class Portal:
    platform = "instahyre"

    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.discovered = 0

    async def check_session(self, page):
        return SessionCheck(self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0])

    async def discover_jobs(self, page, *, query, limit=20, job_age_days=None):
        self.discovered += 1
        return []


class FakeAutoLogin:
    def __init__(self, ok):
        self.ok = ok
        self.calls = 0

    async def attempt(self, portal, page, adapter):
        from backend.app.browser_v2.auth import AutoLoginResult

        self.calls += 1
        return AutoLoginResult(self.ok, "password", "logged_in" if self.ok else "still_logged_out",
                               None if self.ok else "AUTH")


def worker_for(adapter, store=None, **kw):
    store = store or MemoryStore(rules={"instahyre": PortalRules("instahyre", enabled=True, active_hours_start=None,
                                                                 active_hours_end=None)})
    service = BrowserService(Manager(), store, {"instahyre": adapter})
    return Worker(service, force_dry_run=True, idle_poll_sec=0.01, inspection_pause_sec=(0, 0), **kw), service, store


async def test_paused_until_skips_only_that_portal():
    adapter = Portal([AuthStatus.OK])
    worker, _, store = worker_for(adapter)
    await store.update_rules("instahyre", {"paused_until": datetime.now(UTC) + timedelta(hours=3)}, 1)
    report = await worker.cycle(run_once=True)
    assert report.portals[0].skipped == "paused_until" and adapter.discovered == 0
    await store.update_rules("instahyre", {"paused_until": None}, 2)
    report = await worker.cycle(run_once=True)
    assert report.portals[0].skipped is None and adapter.discovered == 1


async def test_auto_login_runs_before_the_auth_hitl():
    adapter = Portal([AuthStatus.AUTH_REQUIRED, AuthStatus.OK])
    worker, service, store = worker_for(adapter)
    service.auto_login = FakeAutoLogin(ok=True)
    report = await worker.cycle(run_once=True)
    assert service.auto_login.calls == 1 and report.portals[0].skipped is None
    assert not await store.open_hitl_exists("instahyre", "AUTH")
    assert {"auto_login": "password"} in report.portals[0].outcomes

    failing = Portal([AuthStatus.AUTH_REQUIRED])
    worker, service, store = worker_for(failing)
    service.auto_login = FakeAutoLogin(ok=False)
    published = []

    class Bus:
        async def publish(self, topic, payload):
            published.append(topic)

    service.event_bus = Bus()
    report = await worker.cycle(run_once=True)
    rows, _ = await store.list_hitl("OPEN")
    assert report.portals[0].skipped == "auth_required" and rows[0].kind == "AUTH"
    assert rows[0].context["auto_login"] == "still_logged_out" and published == ["portal.auth_required"]


async def test_housekeeping_runs_mail_watchers_every_15_minutes_and_the_digest_once():
    sent = []

    async def notify(text):
        sent.append(text)

    class Reader:
        any_configured = True
        events = MailEventStore()

        def __init__(self):
            self.scans = 0

        async def scan_recruiter_replies(self, store, notify=None):
            self.scans += 1
            if notify:
                await notify("📬 Recruiter reply from Acme: Re: Backend")
            return ScanReport(new_events=1, alerts=["📬 Recruiter reply from Acme: Re: Backend"], tier="imap")

        async def scan_job_alert_emails(self, store):
            return ScanReport(discovered=2)

    clock = {"now": IST_EVENING}
    reader = Reader()
    store = MemoryStore()
    worker, _, _ = worker_for(Portal([AuthStatus.OK]), store=store, notify=notify, mail_reader=reader,
                              digest=DigestScheduler(store, hour=21))
    worker.clock = lambda: clock["now"]
    await worker.housekeeping()
    assert reader.scans == 1 and any(t.startswith("🌙 Daily digest") for t in sent)
    clock["now"] += timedelta(minutes=5)
    await worker.housekeeping()
    assert reader.scans == 1 and sum(t.startswith("🌙") for t in sent) == 1
    clock["now"] += timedelta(minutes=15)
    await worker.housekeeping()
    assert reader.scans == 2 and sum(t.startswith("🌙") for t in sent) == 1
    assert worker.housekeeping_log[0]["alert_jobs"] == 2


# --- API -----------------------------------------------------------------------------------------------------
@pytest.fixture
def api_store():
    memory = MemoryStore(profile={"preferences": {}, "verified_skills": []})
    runtime = AIRuntime.build(MemoryCacheStore(), MemoryUsageStore(), embedder=DeterministicTestEmbedder(), env={})

    async def store_override():
        yield memory

    async def ai_override():
        return runtime

    app.dependency_overrides.update({get_v2_store: store_override, get_ai_runtime: ai_override})
    yield memory
    for dependency in (get_v2_store, get_ai_runtime):
        app.dependency_overrides.pop(dependency, None)


async def test_new_routes_require_the_owner_bearer(async_client, phase2_auth, api_store):
    for method, path in (("GET", "/events/status"), ("GET", "/mail/replies"), ("POST", "/agent/chat")):
        response = await async_client.request(method, BASE + path, headers={"Authorization": "Bearer wrong"},
                                              json={"text": "status"})
        assert response.status_code in (401, 403), path


async def test_agent_chat_events_status_and_mail_replies(async_client, phase2_auth, api_store):
    chat = await async_client.post(f"{BASE}/agent/chat", headers=phase2_auth,
                                   json={"text": "raise Naukri daily limit to 60"})
    assert chat.status_code == 200 and chat.json()["ok"] and chat.json()["tool"] == "update_portal_rule"
    assert (await api_store.get_rules("naukri")).max_applies_per_day == 60
    refused = (await async_client.post(f"{BASE}/agent/chat", headers=phase2_auth,
                                       json={"text": "send all drafts now"})).json()
    assert refused["verdict"] == "rejected" and not refused["ok"]
    assert (await async_client.post(f"{BASE}/agent/chat", headers=phase2_auth, json={"text": ""})).status_code == 422
    events = (await async_client.get(f"{BASE}/events/status", headers=phase2_auth)).json()
    assert events["backend"] in ("postgres", "cloudamqp", "upstash_redis") and "job.applied" in events["topics"]
    replies = (await async_client.get(f"{BASE}/mail/replies", headers=phase2_auth)).json()
    assert replies["permission"] == "READ_ONLY" and replies["items"] == [] and set(replies["tiers"]) == {
        "imap", "gmail_api", "mail_app"}


async def test_patch_portal_rules_quota_fields_and_pause(async_client, phase2_auth, api_store):
    rules = (await async_client.get(f"{BASE}/portal-rules", headers=phase2_auth)).json()
    lever = next(r for r in rules if r["platform"] == "lever")
    assert lever["adapter_status"] == "ready" and lever["quota_fallback_daily_cap"] == 10
    body = {"revision": lever["revision"], "quota_fallback_daily_cap": 4, "quota_drafts_per_cycle": 2,
            "paused_until": "2026-11-27T10:00:00+05:30"}
    response = await async_client.patch(f"{BASE}/portal-rules/lever", headers=phase2_auth, json=body)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["quota_fallback_daily_cap"] == 4 and data["quota_drafts_per_cycle"] == 2
    assert datetime.fromisoformat(data["paused_until"]) == datetime(2026, 11, 27, 4, 30, tzinfo=UTC)
    for bad in ({"quota_fallback_daily_cap": 101}, {"quota_drafts_per_cycle": -1},
                {"paused_until": "2026-11-27T10:00:00"}):
        response = await async_client.patch(f"{BASE}/portal-rules/lever", headers=phase2_auth,
                                            json={"revision": data["revision"], **bad})
        assert response.status_code == 422, bad
