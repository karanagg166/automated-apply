"""Phase 5 Layer 4: the whole v2 system end to end (no network, no browser).

Worker + rules + 4-tier screening (profile facts / semantic cache / free LLM / HITL)
+ Telegram HITL bot + enrichment + Gmail draft bridge + the idempotent state machine:

  A. happy path: filters, Tier 0/1/2 answers, APPLIED receipt, cross-portal dedup
  B. HITL learning loop: unknown question -> Telegram -> swipe-reply -> cache -> re-queue
     -> APPLIED -> the next similar question is a Tier 1 hit at 0 LLM tokens
  C. quota hit: park -> cached recruiter email -> 1 IMAP draft -> DRAFTED_AND_QUEUED ->
     next IST day -> automatic retry -> APPLIED with still exactly 1 draft
  D. IMAP failure -> silent Mail.app fallback; a NO_EMAIL_FOUND job is still queued
  E. chaos: LLM 429/503 + Telegram 409 + one portal AUTH_REQUIRED -> isolation, no crash,
     SUBMISSION_UNKNOWN never replayed
"""

import imaplib
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.app.ai_v2.embeddings import DeterministicTestEmbedder
from backend.app.ai_v2.runtime import AIRuntime
from backend.app.ai_v2.semantic_cache import MemoryCacheStore
from backend.app.ai_v2.usage import MemoryUsageStore
from backend.app.browser_v2.adapters.base import ApplyResult, AuthStatus, HitlQuestion
from backend.app.browser_v2.quota import QuotaHitProcessor
from backend.app.browser_v2.rules import parse_applicants
from backend.app.browser_v2.service import BrowserService
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore, WorkerControl, WorkerState
from backend.app.browser_v2.worker import Worker
from backend.app.enrichment_v2.config import EnrichmentConfig
from backend.app.enrichment_v2.service import EnrichmentService
from backend.app.enrichment_v2.store import MemoryEnrichmentStore
from backend.app.mail_v2.composer import DraftComposer
from backend.app.mail_v2.config import MailConfig
from backend.app.telegram_v2.bot import TelegramBot
from backend.tests.test_ai_v2_pipeline import KEYS, LLM
from backend.tests.test_browser_v2_worker import (
    NOON_IST,
    FakeAdapter,
    FakeManager,
    Sleeps,
    job,
    rules,
)
from backend.tests.test_mail_v2 import FakeIMAP, FakeMailApp
from backend.tests.test_mail_v2 import mail_service as build_mail
from backend.tests.test_telegram_v2_bot import FakeTelegram, msg
from backend.tests.test_telegram_v2_bot import config as telegram_config

PROFILE = {
    "full_name": "Test Candidate Person", "phone": "+91 98765 43210", "email": "test.candidate@example.com",
    "verified_experience_years": 2, "verified_skills": ["Python", "FastAPI"],
    "preferences": {"target_roles": ["Python Developer"], "tech_stack": ["Python"], "notice_period_days": 30,
                    "company_blacklist": ["BadCorp"], "skill_years": {"python": 2}},
}
NIGHT = "Are you willing to work night shifts?"
STARTUP = "Are you comfortable working in a fast-paced startup environment?"
ONCALL = "Are you comfortable with on-call rotations?"


class PipelineAdapter(FakeAdapter):
    """FakeAdapter that answers scripted screening questions through the injected 4-tier answerer."""

    def __init__(self, platform, jobs, *, questions=None, **kw):
        super().__init__(platform, jobs, **kw)
        self.questions = questions or {}
        self.answerer = None
        self.tiers: list[tuple[str, str, object]] = []

    async def apply_job(self, page, detail, profile, *, dry_run=True, existing_state=None, hitl_answers=None):
        job_id = detail.listing.external_job_id
        if not dry_run:
            for question, options in self.questions.get(job_id, ()):
                if hitl_answers and question in hitl_answers:
                    self.tiers.append((job_id, question, "hitl"))
                    continue
                resolved = await self.answerer.resolve(question, tuple(options), profile)
                if resolved.answer is None:
                    self.applied.append((job_id, False))
                    return ApplyResult(S.WAITING_FOR_USER, "unknown_question", False, clicked_apply=True,
                                       question=HitlQuestion(kind="QUESTION", prompt=question,
                                                             options=tuple(options)))
                self.tiers.append((job_id, question, resolved.tier))
        return await super().apply_job(page, detail, profile, dry_run=dry_run, existing_state=existing_state,
                                       hitl_answers=hitl_answers)


class Clock:
    def __init__(self, now=NOON_IST):
        self.now = now

    def __call__(self):
        return self.now


def runtime(llm=None, env=KEYS):
    llm = llm or LLM()
    ai = AIRuntime.build(MemoryCacheStore(), MemoryUsageStore(), embedder=DeterministicTestEmbedder(), env=env,
                         transport=httpx.MockTransport(llm.handler))
    ai.bind_profile(PROFILE)
    return ai, llm


def system(rule_map, adapters, *, ai=None, clock=None, mail=None, enrichment=None, notify=None):
    clock = clock or Clock()
    store = MemoryStore(rules=rule_map, profile=PROFILE,
                        worker=WorkerControl(desired_state=WorkerState.RUNNING, dry_run=False))
    service = BrowserService(FakeManager(), store, adapters=adapters, ai=ai)  # type: ignore[arg-type]
    quota = QuotaHitProcessor(store, enrichment=enrichment, mail=mail(store) if mail else None,
                              composer=DraftComposer(None), clock=clock)
    worker = Worker(service, clock=clock, sleeper=Sleeps(), idle_poll_sec=5, quota=quota, notify=notify)
    return store, worker


def state(store, platform, job_id):
    return store.records[(platform, job_id)].state


@pytest.fixture(autouse=True)
def clean():
    FakeIMAP.instances.clear()


# --- A. happy path ---------------------------------------------------------------------------
async def test_pipeline_a_filters_tiered_answers_apply_receipt_and_cross_portal_dedup():
    ai, llm = runtime()
    await ai.cache.store_verified_user_answer(NIGHT, "No")
    naukri = PipelineAdapter("naukri", [job(1, company="Acme"), job(2, company="Oldco"),
                                        job(3, company="BadCorp Pvt Ltd")],
                             details={"naukri-1": {"applicants": parse_applicants("100+ applicants")},
                                      "naukri-2": {"age": 9}},
                             questions={"naukri-1": [("What is your notice period?", ()), (NIGHT, ("Yes", "No")),
                                                     (STARTUP, ("Yes", "No"))]})
    instahyre = PipelineAdapter("instahyre", [job(1, "instahyre", company="Acme Technologies")])
    store, worker = system({"naukri": rules(), "instahyre": rules("instahyre", enabled=False)},
                           {"naukri": naukri, "instahyre": instahyre}, ai=ai)
    report = await worker.cycle()
    portal = {p.platform: p for p in report.portals}["naukri"]
    assert state(store, "naukri", "naukri-1") is S.APPLIED and portal.applied == 1
    assert store.records[("naukri", "naukri-1")].receipt == {"source": "fake"}
    assert [t for _, _, t in naukri.tiers] == [0, 1, 2]  # profile fact, cache, free LLM
    assert len(llm.bodies) == 1 and "98765" not in llm.bodies[0]
    assert state(store, "naukri", "naukri-2") is S.FILTERED_OUT
    assert store.records[("naukri", "naukri-2")].reason == "posting_too_old"
    assert store.records[("naukri", "naukri-3")].reason == "company_blacklisted: BadCorp"
    # Same role on a second portal is never applied twice.
    await store.update_rules("instahyre", {"enabled": True}, 1)
    await worker.cycle()
    duplicate = store.records[("instahyre", "instahyre-1")]
    assert duplicate.state is S.FILTERED_OUT and duplicate.reason.startswith("duplicate_of: naukri:naukri-1")
    assert instahyre.applied == []


# --- B. HITL learning loop ---------------------------------------------------------------------
async def test_pipeline_b_hitl_answer_is_learned_and_reused_at_zero_tokens():
    ai, llm = runtime(env={})  # no LLM keys: unknown questions must reach the owner
    adapter = PipelineAdapter("naukri", [job(1)], questions={"naukri-1": [(ONCALL, ("Yes", "No"))],
                                                             "naukri-2": [(ONCALL + " sometimes", ("Yes", "No"))]})
    store, worker = system({"naukri": rules()}, {"naukri": adapter}, ai=ai)
    await worker.cycle()
    assert state(store, "naukri", "naukri-1") is S.WAITING_FOR_USER
    (hitl,) = (await store.list_hitl("OPEN"))[0]
    fake = FakeTelegram()
    bot = TelegramBot(telegram_config(), store, ai=ai, transport=httpx.MockTransport(fake), min_send_interval=0)
    assert await bot.dispatch_once() == 1
    sent = fake.sent()[0]
    assert ONCALL in sent["text"] and (await store.get_hitl(hitl.id)).telegram_msg_id == 101
    await bot.handle_update({"update_id": 1, **msg("Yes", reply_to=101)})  # owner swipe-reply
    answered = await store.get_hitl(hitl.id)
    assert (answered.status, answered.answer_text, answered.resolved_via) == ("ANSWERED", "Yes", "telegram")
    rows, _ = await ai.cache.store.list_entries("screening_qa", None, 10, 0)
    assert [(r.source, r.answer_text) for r in rows] == [("user", "Yes")]
    assert state(store, "naukri", "naukri-1") is S.SCORED  # priority re-queue
    adapter.jobs = [job(2)]
    report = await worker.cycle()
    assert report.portals[0].requeued == 1 and state(store, "naukri", "naukri-1") is S.APPLIED
    assert state(store, "naukri", "naukri-2") is S.APPLIED
    assert adapter.tiers == [("naukri-1", ONCALL, "hitl"), ("naukri-2", ONCALL + " sometimes", 1)]
    assert llm.bodies == []  # 0 LLM tokens end to end
    await bot.client.aclose()


# --- C. quota hit: draft once, retry tomorrow ---------------------------------------------------
async def test_pipeline_c_quota_hit_drafts_once_and_retries_next_ist_day():
    clock = Clock()
    enrichment_store = MemoryEnrichmentStore()
    await enrichment_store.put_cache("company1.com", status="FOUND",
                                     emails=[{"email": "talent@company1.com", "source": "apollo", "score": 90}],
                                     source="apollo", expires_at=NOON_IST + timedelta(days=30))
    enrichment = EnrichmentService(enrichment_store, config=EnrichmentConfig(keys={}, fetch_pages=False),
                                   clock=clock)
    adapter = PipelineAdapter("naukri", [job(1)], details={"naukri-1": {
        "description": "Python FastAPI role. Company site: https://company1.com/about"}})
    messages: list[str] = []

    async def notify(text):
        messages.append(text)

    store, worker = system({"naukri": rules(max_applies_per_day=1, max_applies_per_hour=1)}, {"naukri": adapter},
                           clock=clock, mail=build_mail, enrichment=enrichment, notify=notify)
    store.applied_at.append(("naukri", NOON_IST - timedelta(hours=2)))  # today's single slot is used
    day1 = await worker.cycle()
    record = store.records[("naukri", "naukri-1")]
    assert day1.portals[0].skipped == "dashboard_daily_limit" and adapter.applied == []
    assert record.state is S.DRAFTED_AND_QUEUED and record.reason == "quota_hit_drafted_and_queued"
    assert record.retry_after == datetime(2026, 11, 27, 2, 30, tzinfo=UTC)  # 08:00 IST tomorrow
    assert [(d["recipient_email"], d["channel"], d["status"]) for d in store.drafts] == \
        [("talent@company1.com", "imap", "CREATED")]
    assert messages == ["Naukri daily limit hit — created 1 Gmail draft & queued 1 job for tomorrow 08:00 IST"]

    await worker.cycle()  # same day: nothing new, still one draft
    assert len(store.drafts) == 1 and record.state is S.DRAFTED_AND_QUEUED

    clock.now = datetime(2026, 11, 27, 3, 30, tzinfo=UTC)  # 09:00 IST next day, quota reset
    adapter.jobs = []
    day2 = await worker.cycle()
    assert day2.portals[0].retried == 1 and record.state is S.APPLIED
    assert adapter.applied == [("naukri-1", False)] and len(store.drafts) == 1
    appends = [c for i in FakeIMAP.instances for c in i.calls if c[0] == "append"]
    assert len(appends) == 1 and b"talent@company1.com" in appends[0][3]
    reasons = [e["reason"] for e in store.events if e["application_id"] == record.id]
    assert reasons == ["passed_filters", "dashboard_daily_limit", "quota_hit_drafted_and_queued",
                       "quota_retry_due", "apply_started", "confirmation_text"]


# --- D. IMAP failure -> Mail.app; no-email job still queued --------------------------------------
async def test_pipeline_d_imap_failure_falls_back_and_no_email_job_gets_no_draft(monkeypatch):
    clock = Clock()
    runner = FakeMailApp()
    monkeypatch.setattr(MailConfig, "mail_app_available", property(lambda self: True))

    def mail(store):
        return build_mail(store, imap_kw={"login_error": imaplib.IMAP4.error("AUTHENTICATIONFAILED")},
                          mail_app=runner)

    enrichment = EnrichmentService(config=EnrichmentConfig(keys={}, fetch_pages=False), clock=clock)
    adapter = PipelineAdapter("naukri", [job(1), job(2)], details={
        "naukri-1": {"description": "Python. Send your CV to careers@company1.com"},
        "naukri-2": {"description": "Python FastAPI. Apply on the portal only."}})
    store, worker = system({"naukri": rules(max_applies_per_day=1)}, {"naukri": adapter}, clock=clock, mail=mail,
                           enrichment=enrichment)
    store.applied_at.append(("naukri", NOON_IST - timedelta(hours=2)))
    report = await worker.cycle()
    first, second = store.records[("naukri", "naukri-1")], store.records[("naukri", "naukri-2")]
    assert (first.state, first.reason) == (S.DRAFTED_AND_QUEUED, "quota_hit_drafted_and_queued")
    assert (second.state, second.reason) == (S.DRAFTED_AND_QUEUED, "quota_hit_queued_no_email")
    assert [d["channel"] for d in store.drafts] == ["mail_app"] and len(runner.requests) == 1
    assert runner.requests[0]["recipient"] == "careers@company1.com"
    assert store.events[-1]["payload"]["draft_reason"] == "quota_hit_no_recruiter_email"
    assert report.portals[0].drafted == 1 and report.portals[0].queued_for_retry == 2
    fell_back = next(e for e in store.events if e["reason"] == "quota_hit_drafted_and_queued")["payload"]
    assert fell_back["fell_back"] is True and fell_back["channel"] == "mail_app"


# --- E. chaos & fault isolation ------------------------------------------------------------------
async def test_pipeline_e_chaos_isolates_failures_and_never_replays():
    class Chaos(LLM):
        def handler(self, request):
            self.bodies.append(request.content.decode())
            status = 429 if request.url.host == "api.groq.com" else 503
            return httpx.Response(status, headers={"retry-after": "30"}, json={"error": "busy"})

    ai, llm = runtime(Chaos())
    naukri = PipelineAdapter("naukri", [job(1)], auth=AuthStatus.AUTH_REQUIRED)
    instahyre = PipelineAdapter("instahyre", [job(1, "instahyre"), job(2, "instahyre"), job(3, "instahyre")],
                                questions={"instahyre-2": [(STARTUP, ("Yes", "No"))]})
    store, worker = system({"naukri": rules(), "instahyre": rules("instahyre")},
                           {"naukri": naukri, "instahyre": instahyre}, ai=ai)
    unknown = await store.upsert_discovered(job(3, "instahyre"))
    unknown = await store.transition(unknown, S.APPLYING, "apply_started")
    await store.transition(unknown, S.SUBMISSION_UNKNOWN, "exception_after_reservation:TimeoutError")

    fake = FakeTelegram()
    fake.conflict = True
    bot = TelegramBot(telegram_config(), store, ai=ai, transport=httpx.MockTransport(fake), min_send_interval=0,
                      conflict_backoff=0)
    await bot.poll_once()  # HTTP 409: recorded, never raised
    assert (await store.get_telegram_state()).polling_state == "conflict"

    report = await worker.cycle()
    by = {p.platform: p for p in report.portals}
    assert by["naukri"].skipped == "auth_required" and naukri.inspected == []
    assert store.rules["naukri"].auth_status == "AUTH_REQUIRED"
    assert await store.open_hitl_exists("naukri", "AUTH")
    assert state(store, "instahyre", "instahyre-1") is S.APPLIED  # portal 2 keeps running
    assert state(store, "instahyre", "instahyre-2") is S.WAITING_FOR_USER  # LLM exhausted -> owner, non-blocking
    assert state(store, "instahyre", "instahyre-3") is S.SUBMISSION_UNKNOWN
    assert "instahyre-3" not in [j for j, _ in instahyre.applied]  # never replayed
    attempts = [json.loads(b) for b in llm.bodies]
    assert len(attempts) == 2  # groq 429 then gemini 503, both now cooling down
    assert (await worker.cycle()).portals  # a second cycle under the same chaos still completes
    assert "instahyre-3" not in [j for j, _ in instahyre.applied]
    await bot.client.aclose()


# --- F. Phase 6A: Telegram free chat changes a live rule mid-run without interrupting the job ---------
class BlockingAdapter(FakeAdapter):
    """The first live apply waits (an application being filled in Brave) until released."""

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        import asyncio

        self.in_flight = asyncio.Event()
        self.release = asyncio.Event()

    async def apply_job(self, page, detail, profile, *, dry_run=True, existing_state=None, hitl_answers=None):
        if not dry_run and not self.in_flight.is_set():
            self.in_flight.set()
            await self.release.wait()
        return await super().apply_job(page, detail, profile, dry_run=dry_run, existing_state=existing_state,
                                       hitl_answers=hitl_answers)


async def test_pipeline_f_telegram_free_chat_updates_rules_mid_run_without_interrupting():
    import asyncio

    adapter = BlockingAdapter("naukri", [job(1), job(2), job(3)])
    store, worker = system({"naukri": rules("naukri", max_applies_per_day=2, max_applies_per_hour=2)},
                           {"naukri": adapter})
    fake = FakeTelegram()
    bot = TelegramBot(telegram_config(), store, transport=httpx.MockTransport(fake), min_send_interval=0)
    cycle = asyncio.create_task(worker.cycle(await store.get_worker_control()))
    await adapter.in_flight.wait()
    assert state(store, "naukri", "naukri-1") is S.APPLYING  # reserved before the click, now in flight
    await bot.handle_update({"update_id": 1, **msg("raise Naukri daily limit to 3")})
    await bot.drain_agent()
    reply = [p for m, p in fake.calls if m == "sendMessage"][-1]["text"]
    assert "Updated Naukri" in reply and (await store.get_rules("naukri")).max_applies_per_day == 3
    assert not cycle.done() and state(store, "naukri", "naukri-1") is S.APPLYING  # untouched
    adapter.release.set()
    report = await cycle
    assert state(store, "naukri", "naukri-1") is S.APPLIED and report.portals[0].applied == 2
    # The new daily cap (3) is read at the start of the NEXT cycle (no restart); hourly cap still 2.
    await bot.handle_update({"update_id": 2, **msg("set naukri hourly limit to 3")})
    await bot.drain_agent()
    second = await worker.cycle(await store.get_worker_control())
    assert second.portals[0].applied == 1 and state(store, "naukri", "naukri-3") is S.APPLIED
