"""10-portal worker orchestration end to end (no network, no browser).

One live cycle across all 10 adapters, in portal-priority order:
  1 naukri            APPLIED (receipt) -> cross-portal dedup blocks the same role on
  2 instahyre         FILTERED_OUT duplicate_of naukri (never applied)
  3 internshala       dashboard daily cap -> enrichment -> exactly 1 Gmail draft -> DRAFTED_AND_QUEUED
                      -> next IST day retry -> APPLIED, still exactly 1 draft
  4 wellfound         unseen screening question -> WAITING_FOR_USER (non-blocking) -> Telegram ->
                      swipe-reply -> semantic cache learns (source='user') -> priority re-queue
  5 work_at_a_startup AUTH_REQUIRED -> auto re-login (Keychain + email OTP) recovers in-cycle
  6-10 greenhouse, lever, himalayas, we_work_remotely, hiringcafe: applied cleanly in the same cycle
Concurrently a Telegram free-chat "pause internshala for 3 hours" is executed while a job is in
flight without interrupting it; every component shares ONE store (one serialized DB connection in
production) and APPLIED / SUBMISSION_UNKNOWN are never replayed. A second test isolates a portal
whose auto-login hits an SMS OTP.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.app.browser_v2.adapters.base import AuthStatus, SessionCheck
from backend.app.browser_v2.auth import AutoLoginResult
from backend.app.browser_v2.quota import QuotaHitProcessor
from backend.app.browser_v2.service import BrowserService
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore, WorkerControl, WorkerState
from backend.app.browser_v2.worker import Worker
from backend.app.enrichment_v2.config import EnrichmentConfig
from backend.app.enrichment_v2.service import EnrichmentService
from backend.app.enrichment_v2.store import MemoryEnrichmentStore
from backend.app.mail_v2.composer import DraftComposer
from backend.app.telegram_v2.bot import TelegramBot
from backend.tests.test_browser_v2_worker import (
    NOON_IST,
    FakeManager,
    Sleeps,
    job,
    rules,
)
from backend.tests.test_mail_v2 import FakeIMAP
from backend.tests.test_mail_v2 import mail_service as build_mail
from backend.tests.test_telegram_v2_bot import FakeTelegram, msg
from backend.tests.test_telegram_v2_bot import config as telegram_config
from backend.tests.test_v2_full_pipeline_e2e import (
    PROFILE,
    Clock,
    PipelineAdapter,
    runtime,
)

PRIORITY = ("naukri", "instahyre", "internshala", "wellfound", "work_at_a_startup",
            "greenhouse", "lever", "himalayas", "we_work_remotely", "hiringcafe")
ONCALL = "Are you comfortable with weekend on-call rotations for our payments platform?"


class PriorityStore(MemoryStore):
    """MemoryStore whose rules are iterated in the simulation's portal-priority order."""

    async def list_rules(self):
        return [self.rules[k] for k in PRIORITY if k in self.rules]


class GatedAdapter(PipelineAdapter):
    """Holds its first live apply open (a form being filled in Brave) until released."""

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.in_flight = asyncio.Event()
        self.release = asyncio.Event()

    async def apply_job(self, page, detail, profile, *, dry_run=True, existing_state=None, hitl_answers=None):
        if not dry_run and not self.in_flight.is_set():
            self.in_flight.set()
            await self.release.wait()
        return await super().apply_job(page, detail, profile, dry_run=dry_run, existing_state=existing_state,
                                       hitl_answers=hitl_answers)


class ReloginAdapter(PipelineAdapter):
    async def check_session(self, page):
        return SessionCheck(self.auth, reason=None if self.auth is AuthStatus.OK else "login")


class FakeAutoLogin:
    """Keychain password + email-OTP re-login; `sms=True` models a portal that demands an SMS OTP."""

    def __init__(self, *, sms: bool = False) -> None:
        self.sms = sms
        self.calls: list[str] = []

    async def attempt(self, portal, page, adapter):
        self.calls.append(portal)
        if self.sms:
            return AutoLoginResult(False, "password+email_otp", "otp_rejected_or_sms_otp", "OTP")
        adapter.auth = AuthStatus.OK
        return AutoLoginResult(True, "password+email_otp", "logged_in")


def all_rules(**overrides):
    values = {name: rules(name) for name in PRIORITY}
    values["internshala"] = rules("internshala", max_applies_per_day=1, max_applies_per_hour=1)
    values.update(overrides)
    return values


def build_system(adapters, *, ai, clock, enrichment, auto_login):
    store = PriorityStore(rules=all_rules(), profile=PROFILE,
                          worker=WorkerControl(desired_state=WorkerState.RUNNING, dry_run=False))
    service = BrowserService(FakeManager(), store, adapters=adapters, ai=ai)  # type: ignore[arg-type]
    service.auto_login = auto_login
    quota = QuotaHitProcessor(store, enrichment=enrichment, mail=build_mail(store), composer=DraftComposer(None),
                              clock=clock)
    worker = Worker(service, clock=clock, sleeper=Sleeps(), idle_poll_sec=5, quota=quota)
    return store, service, quota, worker


def st(store, platform, job_id):
    return store.records[(platform, job_id)].state


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    FakeIMAP.instances.clear()
    monkeypatch.delenv("DRY_RUN", raising=False)


async def test_ten_portals_one_cycle_dedup_quota_hitl_relogin_chat_and_never_replay():
    clock = Clock()
    ai, llm = runtime(env={})  # no LLM keys: the unseen question must reach the owner
    enrichment_store = MemoryEnrichmentStore()
    await enrichment_store.put_cache("internco.example", status="FOUND",
                                     emails=[{"email": "talent@internco.example", "source": "apollo", "score": 90}],
                                     source="apollo", expires_at=NOON_IST + timedelta(days=30))
    enrichment = EnrichmentService(enrichment_store, config=EnrichmentConfig(keys={}, fetch_pages=False), clock=clock)
    gated = GatedAdapter("greenhouse", [job(1, "greenhouse", company="Greenco")])
    adapters: dict[str, PipelineAdapter] = {
        "naukri": PipelineAdapter("naukri", [job(1, "naukri", company="Acme")]),
        "instahyre": PipelineAdapter("instahyre", [job(1, "instahyre", company="Acme Technologies")]),
        "internshala": PipelineAdapter("internshala", [job(1, "internshala", company="InternCo")], details={
            "internshala-1": {"description": "Python FastAPI. Company site: https://internco.example/about"}}),
        "wellfound": PipelineAdapter("wellfound", [job(1, "wellfound", company="Wellco")],
                                     questions={"wellfound-1": [(ONCALL, ("Yes", "No"))]}),
        "work_at_a_startup": ReloginAdapter("work_at_a_startup", [job(1, "work_at_a_startup", company="YC Co")],
                                            auth=AuthStatus.AUTH_REQUIRED),
        "greenhouse": gated,
        "lever": PipelineAdapter("lever", [job(1, "lever", company="Leverco"), job(2, "lever", company="Doneco"),
                                           job(3, "lever", company="Unknownco")]),
        "himalayas": PipelineAdapter("himalayas", [job(1, "himalayas", company="Himco")]),
        "we_work_remotely": PipelineAdapter("we_work_remotely", [job(1, "we_work_remotely", company="Remoteco")]),
        "hiringcafe": PipelineAdapter("hiringcafe", [job(1, "hiringcafe", company="Cafeco")]),
    }
    login = FakeAutoLogin()
    store, service, quota, worker = build_system(adapters, ai=ai, clock=clock, enrichment=enrichment,
                                                 auto_login=login)
    # Terminal history that must never be replayed.
    for job_id, terminal in (("lever-2", S.APPLIED), ("lever-3", S.SUBMISSION_UNKNOWN)):
        record = await store.upsert_discovered(job(int(job_id[-1]), "lever"))
        record = await store.transition(record, S.APPLYING, "apply_started")
        await store.transition(record, terminal, "historical")
    store.applied_at.append(("internshala", NOON_IST - timedelta(hours=2)))  # today's single slot used

    fake = FakeTelegram()
    bot = TelegramBot(telegram_config(), store, ai=ai, transport=httpx.MockTransport(fake), min_send_interval=0)
    cycle = asyncio.create_task(worker.cycle(await store.get_worker_control()))
    await gated.in_flight.wait()
    assert st(store, "greenhouse", "greenhouse-1") is S.APPLYING  # reserved before the click, now in flight
    await bot.handle_update({"update_id": 1, **msg("pause internshala for 3 hours")})
    await bot.drain_agent()
    paused = (await store.get_rules("internshala")).paused_until
    assert paused is not None and paused > datetime.now(UTC) + timedelta(hours=2)
    assert not cycle.done() and st(store, "greenhouse", "greenhouse-1") is S.APPLYING  # untouched by the chat
    gated.release.set()
    report = await cycle
    by = {p.platform: p for p in report.portals}
    assert [p.platform for p in report.portals] == list(PRIORITY)

    # 1-2: applied once, the same role elsewhere is a duplicate.
    assert st(store, "naukri", "naukri-1") is S.APPLIED and by["naukri"].applied == 1
    dup = store.records[("instahyre", "instahyre-1")]
    assert dup.state is S.FILTERED_OUT and dup.reason.startswith("duplicate_of: naukri:naukri-1")
    assert adapters["instahyre"].applied == []
    # 3: quota -> exactly one draft, queued for tomorrow 08:00 IST.
    intern = store.records[("internshala", "internshala-1")]
    assert intern.state is S.DRAFTED_AND_QUEUED and by["internshala"].skipped == "dashboard_daily_limit"
    assert intern.retry_after == datetime(2026, 11, 27, 2, 30, tzinfo=UTC)
    assert [(d["recipient_email"], d["status"]) for d in store.drafts] == [("talent@internco.example", "CREATED")]
    # 4: non-blocking HITL; later portals kept running in the same cycle.
    assert st(store, "wellfound", "wellfound-1") is S.WAITING_FOR_USER
    # 5: auto re-login recovered the portal without waking the owner.
    assert login.calls == ["work_at_a_startup"] and {"auto_login": "password+email_otp"} in by[
        "work_at_a_startup"].outcomes
    assert st(store, "work_at_a_startup", "work_at_a_startup-1") is S.APPLIED
    assert not await store.open_hitl_exists("work_at_a_startup", "AUTH")
    # 6-10 clean, and terminal history never replayed.
    for name in ("greenhouse", "lever", "himalayas", "we_work_remotely", "hiringcafe"):
        assert st(store, name, f"{name}-1") is S.APPLIED, name
        assert by[name].errors == 0 and by[name].skipped is None, name
    assert [j for j, _ in adapters["lever"].applied] == ["lever-1"]
    assert st(store, "lever", "lever-2") is S.APPLIED and st(store, "lever", "lever-3") is S.SUBMISSION_UNKNOWN

    # Telegram HITL: dispatch, owner swipe-reply, cache learns, priority re-queue.
    assert await bot.dispatch_once() == 1
    prompt = next(p for m, p in fake.calls if m == "sendMessage" and ONCALL in p["text"])
    assert prompt  # the HITL card was sent; swipe-reply to the message id Telegram returned for it
    open_rows, _ = await store.list_hitl("OPEN", limit=20)
    card = next(row for row in open_rows if row.kind == "QUESTION" and row.telegram_msg_id is not None)
    await bot.handle_update({"update_id": 2, **msg("Yes", reply_to=card.telegram_msg_id)})
    rows, _ = await ai.cache.store.list_entries("screening_qa", None, 10, 0)
    assert [(r.source, r.answer_text) for r in rows] == [("user", "Yes")]
    assert st(store, "wellfound", "wellfound-1") is S.SCORED

    # One shared store = one serialized DB connection in production (Supabase 5-connection role).
    assert worker.store is service.store is bot.store is quota.store is store

    # Next IST day (pause expired, quota reset): internshala retries, wellfound applies with the HITL answer.
    clock.now = datetime(2026, 11, 27, 3, 30, tzinfo=UTC)
    for adapter in adapters.values():
        adapter.jobs = []
    day2 = await worker.cycle(await store.get_worker_control())
    day2_by = {p.platform: p for p in day2.portals}
    assert intern.state is S.APPLIED and day2_by["internshala"].retried == 1 and len(store.drafts) == 1
    assert st(store, "wellfound", "wellfound-1") is S.APPLIED and day2_by["wellfound"].requeued == 1
    assert adapters["wellfound"].tiers == [("wellfound-1", ONCALL, "hitl")]
    # Never replayed, and never APPLIED twice anywhere (one APPLIED transition per application).
    to_applied = [e["application_id"] for e in store.events if e["to"] == S.APPLIED and e["reason"] != "historical"]
    assert len(to_applied) == len(set(to_applied)) == 9  # 10 portals minus the instahyre duplicate
    attempted = [(name, j) for name, a in adapters.items() for j, _ in a.applied]
    assert ("lever", "lever-2") not in attempted and ("lever", "lever-3") not in attempted
    assert llm.bodies == []  # zero LLM tokens in this run (no keys; HITL + cache answered)
    await bot.client.aclose()


async def test_sms_otp_relogin_isolates_only_that_portal():
    clock = Clock()
    adapters = {
        "work_at_a_startup": ReloginAdapter("work_at_a_startup", [job(1, "work_at_a_startup")],
                                            auth=AuthStatus.AUTH_REQUIRED),
        "lever": PipelineAdapter("lever", [job(1, "lever")]),
    }
    login = FakeAutoLogin(sms=True)
    store, _, _, worker = build_system(adapters, ai=None, clock=clock, enrichment=None, auto_login=login)
    store.rules = {k: v for k, v in store.rules.items() if k in adapters}
    report = await worker.cycle(await store.get_worker_control())
    by = {p.platform: p for p in report.portals}
    assert by["work_at_a_startup"].skipped == "auth_required" and adapters["work_at_a_startup"].inspected == []
    assert await store.open_hitl_exists("work_at_a_startup", "AUTH")
    assert st(store, "lever", "lever-1") is S.APPLIED  # the other portal kept running
    await worker.cycle(await store.get_worker_control())
    open_auth = [h for h in store.hitl if h.get("platform") == "work_at_a_startup" and h.get("kind") == "AUTH"
                 and h.get("status") == "OPEN"]
    assert len(open_auth) == 1  # one open AUTH request, not one per cycle
