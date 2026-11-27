"""Zero-spam Telegram (followup 007): tiers, ledger cooldown, quiet hours, budget, mute, rollup,
digest, HITL card edit-in-place, transport 429/401/parse/chunking (no network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from backend.app.browser_v2.store import MemoryStore
from backend.app.events_v2.bus import InProcessBus
from backend.app.telegram_v2.client import TelegramClient, TelegramUnauthorized
from backend.app.telegram_v2.notify_policy import (
    TOPICS,
    NotifyConfig,
    Priority,
    classify,
    dedup_key,
)
from backend.app.telegram_v2.notify_router import NotificationRouter
from backend.tests.test_telegram_v2_bot import (
    OWNER,
    TOKEN,
    FakeTelegram,
    make_bot,
    waiting_job,
)

NOON_IST = datetime(2026, 11, 28, 6, 30, tzinfo=UTC)  # 12:00 IST
NIGHT_IST = datetime(2026, 11, 28, 19, 0, tzinfo=UTC)  # 00:30 IST (quiet)


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.edits: list[tuple[int, str]] = []
        self.rate_limited = 0

    async def send_message(self, chat_id: int, text: str, **kw: Any) -> dict[str, Any]:
        self.sent.append({"chat_id": chat_id, "text": text} | kw)
        return {"message_id": 500 + len(self.sent)}

    async def edit_message_text(self, chat_id: int, message_id: int, text: str, **kw: Any) -> None:
        self.edits.append((message_id, text))


class Clock:
    def __init__(self, now: datetime = NOON_IST) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


async def no_sleep(_: float) -> None:
    return None


def router(store: Any = None, clock: Clock | None = None, **config: Any) -> tuple[NotificationRouter, FakeClient]:
    client = FakeClient()
    r = NotificationRouter(client, OWNER, store if store is not None else MemoryStore(),
                           NotifyConfig(**config), clock=clock or Clock(), sleeper=no_sleep)
    return r, client


async def settle(r: NotificationRouter) -> None:
    await r.flush_rollup()
    if r._sender is not None:
        await r.queue.join()


ERROR = {"platform": "naukri", "fingerprint": "TimeoutError", "detail": "TimeoutError: page.goto 45s"}


# --- tiers ----------------------------------------------------------------------------------------
async def test_p2_and_p3_events_are_never_pushed_only_queued_for_the_digest():
    r, client = router()
    await r.handle("job.applied", {"platform": "naukri", "external_job_id": "1", "priority": 2, "title": "SWE"})
    await r.handle("job.priority_discovered", {"platform": "lever", "external_job_id": "9", "ats_supported": True})
    await r.handle("job.quota_hit", {"platform": "naukri", "reason": "daily"})
    await r.handle("portal.auth_required", {"platform": "naukri"})  # P3: the AUTH HITL card is the alert
    await settle(r)
    assert client.sent == []
    lines = [item.text for item in await r.pending_digest()]
    assert len(lines) == 3 and any("applied: naukri" in line for line in lines)


async def test_first_mover_win_is_a_silent_rollup_not_a_ping_storm():
    r, client = router()
    for i in range(3):
        await r.handle("job.applied", {"platform": "greenhouse", "external_job_id": str(i), "priority": 0,
                                       "title": f"Backend {i}", "first_mover_lag_seconds": 300})
    await settle(r)
    assert len(client.sent) == 1 and client.sent[0]["silent"] is True
    assert "3 updates" in client.sent[0]["text"] and "5m after discovery" in client.sent[0]["text"]


def test_policy_maps_auth_like_breaker_reasons_to_p0_and_keys_are_bounded():
    config = NotifyConfig()
    assert classify("portal.circuit_open", {"platform": "x", "reason": "login wall"}, config, NOON_IST).priority \
        is Priority.P0
    assert classify("portal.circuit_open", {"platform": "x", "reason": "3 timeouts"}, config, NOON_IST).priority \
        is Priority.P1
    assert classify("hitl.opened", {}, config, NOON_IST) is None
    key = dedup_key("err", "naukri", "x" * 200)
    assert len(key) <= 64 and key == dedup_key("err", "naukri", "x" * 200)
    assert set(TOPICS) >= {"system.error", "portal.circuit_closed", "quota.summary"}


# --- dedup ledger -----------------------------------------------------------------------------------
async def test_identical_error_fires_once_within_cooldown_and_counts_suppressed():
    store, clock = MemoryStore(), Clock()
    r, client = router(store, clock)
    for _ in range(4):
        await r.handle("system.error", ERROR)
    await settle(r)
    assert len(client.sent) == 1
    entry = await store.ledger_get(dedup_key("err", "naukri", "TimeoutError"))
    assert entry is not None and entry.suppressed_count == 3
    clock.now += timedelta(hours=2, minutes=1)
    await r.handle("system.error", ERROR)
    await settle(r)
    assert len(client.sent) == 2
    assert (await store.ledger_get(dedup_key("err", "naukri", "TimeoutError"))).suppressed_count == 0


async def test_ledger_survives_a_restart_so_a_new_process_does_not_resend():
    store, clock = MemoryStore(), Clock()
    first, client = router(store, clock)
    await first.handle("portal.circuit_open", {"platform": "naukri", "reason": "login wall"})
    await settle(first)
    restarted, client2 = router(store, clock)
    clock.now += timedelta(hours=1)
    await restarted.handle("portal.circuit_open", {"platform": "naukri", "reason": "login wall"})
    await settle(restarted)
    assert len(client.sent) == 1 and client2.sent == []


async def test_breaker_recovery_edits_the_open_alert_card_instead_of_a_new_message():
    store = MemoryStore()
    r, client = router(store)
    await r.handle("portal.circuit_open", {"platform": "naukri", "reason": "login wall"})
    await settle(r)
    message_id = (await store.ledger_get("circuit:naukri")).message_id
    await r.handle("portal.circuit_closed", {"platform": "naukri"})
    await settle(r)
    assert len(client.sent) == 1 and client.edits and client.edits[0][0] == message_id
    assert (await store.ledger_get("circuit:naukri")).resolved_at is not None


# --- quiet hours, budget, mute --------------------------------------------------------------------
@pytest.mark.parametrize("ist_time,quiet", [("23:29", False), ("23:31", True), ("07:59", True), ("08:01", False)])
def test_quiet_hours_respect_ist_boundaries(ist_time, quiet):
    from zoneinfo import ZoneInfo

    hour, minute = map(int, ist_time.split(":"))
    local = datetime(2026, 11, 28, hour, minute, tzinfo=ZoneInfo("Asia/Kolkata"))
    assert NotifyConfig().in_quiet(local.astimezone(UTC)) is quiet


async def test_quiet_hours_defer_p1_and_p0_breaker_alerts_into_the_morning_digest():
    r, client = router(clock=Clock(NIGHT_IST))
    await r.handle("system.error", ERROR)
    await r.handle("portal.circuit_open", {"platform": "naukri", "reason": "session expired"})
    await settle(r)
    assert client.sent == []
    assert all("held: quiet hours" in item.text for item in await r.pending_digest())


async def test_hourly_push_budget_caps_non_p0_and_collapses_overflow_into_the_digest():
    clock = Clock()
    r, client = router(clock=clock, max_pushes_per_hour=2)
    for i in range(5):
        await r.handle("system.error", {"platform": "naukri", "fingerprint": f"E{i}"})
        await settle(r)  # each its own rollup window
        clock.now += timedelta(minutes=1)
    assert len(client.sent) == 2
    assert sum("hourly budget" in item.text for item in await r.pending_digest()) == 3
    await r.handle("portal.circuit_open", {"platform": "lever", "reason": "captcha wall"})  # P0 ignores budget
    await settle(r)
    assert len(client.sent) == 3


async def test_mute_is_persisted_and_holds_non_p0_until_it_expires():
    store, clock = MemoryStore(), Clock()
    r, client = router(store, clock)
    await r.set_mute(clock.now + timedelta(hours=2))
    restarted, client2 = router(store, clock)
    await restarted.handle("system.error", ERROR)
    await restarted.handle("portal.circuit_open", {"platform": "naukri", "reason": "otp challenge"})
    await settle(restarted)
    assert len(client2.sent) == 1 and "circuit breaker" in client2.sent[0]["text"]  # only the P0
    assert (await store.get_telegram_state()).muted_until == clock.now + timedelta(hours=2)


async def test_notify_early_bird_preference_off_downgrades_job_wins_to_the_digest():
    async def prefs() -> dict[str, Any]:
        return {"notify_early_bird": False}

    client = FakeClient()
    r = NotificationRouter(client, OWNER, MemoryStore(), NotifyConfig(), clock=Clock(), sleeper=no_sleep,
                           prefs_provider=prefs)
    await r.handle("job.applied", {"platform": "lever", "external_job_id": "1", "priority": 0})
    await settle(r)
    assert client.sent == [] and len(await r.pending_digest()) == 1


async def test_router_registers_on_the_bus_and_html_is_escaped():
    bus = InProcessBus()
    r, client = router()
    assert set(r.register(bus)) == set(TOPICS)
    await bus.publish("job.priority_discovered", {"platform": "hn", "external_job_id": "7", "ats_supported": False,
                                                  "company": "<Acme & Co>", "apply_url": "https://acme.example/jobs"})
    await bus.drain()
    await settle(r)
    assert "&lt;Acme &amp; Co&gt;" in client.sent[0]["text"] and "https://acme.example/jobs" in client.sent[0]["text"]


async def test_shutdown_moves_unsent_rollup_into_the_persistent_digest():
    store = MemoryStore()
    r, client = router(store)
    await r.handle("mail.recruiter_reply", {"alert": "Interview invite from Acme"})
    await r.close()
    assert client.sent == []
    assert any("Interview invite" in item.text for item in await store.digest_pending())


# --- digest ---------------------------------------------------------------------------------------
async def test_empty_digest_is_skipped_and_queued_items_are_delivered_once():
    from backend.app.browser_v2.digest import DigestScheduler
    from backend.app.browser_v2.worker import Worker
    from backend.tests.test_telegram_v2_reliability import IST_2105, _service

    store = MemoryStore()
    sent: list[str] = []

    async def notify(text: str) -> None:
        sent.append(text)

    worker = Worker(_service(store), clock=lambda: IST_2105, notify=notify,
                    digest=DigestScheduler(store, hours=(9, 21), skip_empty=True))
    await worker.housekeeping()
    assert sent == []  # nothing happened: no message at all
    r, _ = router(store, Clock(IST_2105))
    worker.notifier = r
    await r.handle("job.applied", {"platform": "naukri", "external_job_id": "1", "priority": 3, "title": "SWE"})
    worker.digest = DigestScheduler(store, hours=(9, 21), skip_empty=True)
    await store.update_telegram_state(last_digest_slot=None)
    await worker.housekeeping()
    assert len(sent) == 1 and "applied: naukri" in sent[0]
    assert await r.pending_digest() == []


# --- HITL cards -----------------------------------------------------------------------------------
async def test_dashboard_resolution_edits_the_telegram_card_in_place_and_strips_buttons(store):
    from backend.app.browser_v2.hitl import HITLResolutionService

    fake = FakeTelegram()
    bot = make_bot(store, fake)
    _, hitl = await waiting_job(store)
    await bot.dispatch_once()
    card_id = fake.sent()[-1] and (await store.get_hitl(hitl.id)).telegram_msg_id
    await HITLResolutionService(store).answer(hitl.id, "Yes", cache_answer=False, via="dashboard")
    await bot.dispatch_once()
    edits = fake.sent("editMessageText")
    assert len(edits) == 1 and edits[0]["message_id"] == card_id
    assert edits[0]["reply_markup"] == {"inline_keyboard": []} and "via dashboard" in edits[0]["text"]
    await bot.dispatch_once()
    assert len(fake.sent("editMessageText")) == 1  # synced exactly once
    await bot.client.aclose()


async def test_quiet_hours_hold_question_cards_but_otp_goes_out(store):
    fake = FakeTelegram()
    bot = make_bot(store, fake, clock=lambda: NIGHT_IST, notify_config=NotifyConfig())
    await waiting_job(store, 1, kind="QUESTION")
    await waiting_job(store, 2, kind="OTP", prompt="Enter the OTP", options=())
    await bot.dispatch_once()
    assert len(fake.sent()) == 1 and "OTP" in fake.sent()[0]["text"]
    await bot.client.aclose()


@pytest.fixture
def store():
    return MemoryStore()


async def test_double_tap_resolves_once(store):
    fake = FakeTelegram()
    bot = make_bot(store, fake)
    _, hitl = await waiting_job(store)
    await bot.dispatch_once()
    message_id = (await store.get_hitl(hitl.id)).telegram_msg_id
    from backend.tests.test_telegram_v2_bot import callback

    await bot.handle_update(callback(f"ans:{hitl.ref}:0", message_id, cid="a"))
    await bot.handle_update(callback(f"ans:{hitl.ref}:0", message_id, cid="b"))
    answered = [row for row in store.hitl if row["status"] == "ANSWERED"]
    assert len(answered) == 1 and len(fake.sent("answerCallbackQuery")) == 2
    await bot.client.aclose()


# --- transport ------------------------------------------------------------------------------------
class Script:
    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(json.loads(request.content or b"{}"))
        return self.responses.pop(0) if self.responses else httpx.Response(
            200, json={"ok": True, "result": {"message_id": len(self.calls)}})


def client_for(script: Script, sleeps: list[float]) -> TelegramClient:
    async def sleeper(seconds: float) -> None:
        sleeps.append(seconds)

    return TelegramClient(TOKEN, transport=httpx.MockTransport(script), min_send_interval=0, sleeper=sleeper)


async def test_429_pauses_for_retry_after_then_resends_without_dropping():
    sleeps: list[float] = []
    script = Script(httpx.Response(429, json={"ok": False, "parameters": {"retry_after": 7}}))
    client = client_for(script, sleeps)
    result = await client.send_message(OWNER, "hello")
    assert result["message_id"] == 2 and len(script.calls) == 2 and any(s >= 7.4 for s in sleeps)
    await client.aclose()


async def test_401_trips_the_outbound_circuit_instead_of_looping():
    script = Script(httpx.Response(401, json={"ok": False}))
    client = client_for(script, [])
    with pytest.raises(TelegramUnauthorized):
        await client.send_message(OWNER, "x")
    with pytest.raises(TelegramUnauthorized):
        await client.send_message(OWNER, "y")
    assert len(script.calls) == 1 and client.circuit_open
    await client.aclose()


async def test_parse_error_falls_back_to_plain_text_and_long_text_is_chunked():
    script = Script(httpx.Response(400, json={"ok": False, "description": "Bad Request: can't parse entities"}))
    client = client_for(script, [])
    await client.send_message(OWNER, "<b>Acme &amp; Co</b>")
    assert "parse_mode" not in script.calls[1] and script.calls[1]["text"] == "Acme & Co"
    long_text = "\n".join(f"line {i} " + "x" * 90 for i in range(100))
    await client.send_message(OWNER, long_text)
    chunks = [c["text"] for c in script.calls[2:]]
    assert len(chunks) >= 3 and all(len(c) <= 4096 for c in chunks)
    assert "".join(c.replace("\n", "") for c in chunks) == long_text.replace("\n", "")
    await client.aclose()


async def test_silent_flag_maps_to_disable_notification():
    script = Script()
    client = client_for(script, [])
    await client.send_message(OWNER, "quiet win", silent=True)
    assert script.calls[0]["disable_notification"] is True
    await client.aclose()


# --- ops commands ---------------------------------------------------------------------------------
async def test_ops_commands_hitl_mute_pause_resume_health(store):
    from backend.tests.test_telegram_v2_bot import last_reply, msg

    fake = FakeTelegram()
    r, _ = router(store)
    bot = make_bot(store, fake, notifier=r)
    await bot.handle_update(msg("/hitl"))
    assert "0 open questions" in last_reply(fake)
    await bot.handle_update(msg("/mute 2h"))
    assert "Muted" in last_reply(fake) and (await store.get_telegram_state()).muted_until is not None
    await bot.handle_update(msg("/mute off"))
    assert (await store.get_telegram_state()).muted_until is None
    await bot.handle_update(msg("/pause naukri"))
    assert (await store.get_rules("naukri")).paused_until is not None
    await bot.handle_update(msg("/resume naukri"))
    assert (await store.get_rules("naukri")).paused_until is None
    await bot.handle_update(msg("/pause all"))
    assert (await store.get_worker_control()).desired_state.value == "PAUSED"
    await bot.handle_update(msg("/resume all"))
    assert (await store.get_worker_control()).desired_state.value == "RUNNING"
    await bot.handle_update(msg("/health"))
    assert "Health" in last_reply(fake) and "Pushes:" in last_reply(fake)
    await bot.client.aclose()


async def test_queue_buttons_fit_64_bytes_and_a_double_tap_skips_once(store):
    from backend.app.browser_v2.adapters.base import JobListing
    from backend.tests.test_telegram_v2_bot import callback, msg

    fake = FakeTelegram()
    bot = make_bot(store, fake)
    record = await store.upsert_discovered(JobListing(platform="lever", external_job_id="q1", url="https://x/1",
                                                      title="SWE", company="Acme"))
    await store.set_owner_priority(record.id, 1, "test")
    await bot.handle_update(msg("/queue"))
    keyboard = fake.sent()[-1]["reply_markup"]["inline_keyboard"]
    data = [button["callback_data"] for row in keyboard for button in row]
    assert data and all(len(d.encode()) <= 64 for d in data)
    skip = next(d for d in data if d.startswith("q:skip:"))
    await bot.handle_update(callback(skip, 9, cid="1"))
    await bot.handle_update(callback(skip, 9, cid="2"))
    toasts = [p.get("text") for p in fake.sent("answerCallbackQuery")]
    assert toasts == ["⏭ Skipped.", "Already filtered_out — nothing changed."]
    await bot.client.aclose()


async def test_polling_start_registers_commands_and_deletes_a_stale_webhook(store):
    import asyncio

    class WebhookFake(FakeTelegram):
        def __call__(self, request):
            if request.url.path.endswith("/getWebhookInfo"):
                self.calls.append(("getWebhookInfo", {}))
                return httpx.Response(200, json={"ok": True, "result": {"url": "https://old.example/hook"}})
            return super().__call__(request)

    fake = WebhookFake()
    bot = make_bot(store, fake)
    stop = asyncio.Event()
    task = asyncio.create_task(bot.run(stop))
    await asyncio.sleep(0.05)
    stop.set()
    await task
    methods = [name for name, _ in fake.calls]
    assert "deleteWebhook" in methods and "setMyCommands" in methods
    assert methods.index("deleteWebhook") < methods.index("getUpdates")
