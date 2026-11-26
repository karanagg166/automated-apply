"""Phase 8 Telegram v2 reliability: chunking, parse-error fallback, supervised polling,
409 diagnostics, idempotent callbacks, reply disambiguation, offset persistence,
HITL expiry and the once-per-IST-day digest (no network; mocked Bot API)."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from backend.app.browser_v2.digest import DigestScheduler
from backend.app.browser_v2.hitl import EXPIRED_REASON, HITLResolutionService
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import HitlRecord, MemoryStore, agent_chat_key
from backend.app.browser_v2.worker import Worker
from backend.app.telegram_v2.client import (
    CHUNK_UNITS,
    TelegramClient,
    html_to_plain,
    split_message,
    utf16_len,
)
from backend.app.telegram_v2.formatting import render_hitl, render_resolved
from backend.tests.test_telegram_v2_bot import (
    OWNER,
    QUESTION,
    STRANGER,
    TOKEN,
    FakeTelegram,
    callback,
    config,
    make_bot,
    msg,
    waiting_job,
)

IST_2105 = datetime(2026, 11, 26, 15, 35, tzinfo=UTC)  # 21:05 Asia/Kolkata


class ParseRejectingTelegram(FakeTelegram):
    """Rejects any HTML send/edit with Telegram's entity-parse 400 (like a stray '<' in a title)."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content or b"{}")
        method = request.url.path.rsplit("/", 1)[-1]
        if method in {"sendMessage", "editMessageText"} and payload.get("parse_mode") == "HTML":
            self.calls.append((method, payload))
            return httpx.Response(400, json={"ok": False, "error_code": 400, "description":
                                             "Bad Request: can't parse entities: Unsupported start tag \"x\""})
        return super().__call__(request)


def client_for(fake: FakeTelegram) -> TelegramClient:
    return TelegramClient(TOKEN, transport=httpx.MockTransport(fake), min_send_interval=0)


# --- chunking + formatting safety ---------------------------------------------------------
def test_split_message_respects_utf16_limit_and_line_boundaries():
    lines = [f"• <b>line {i}</b> " + "🚀" * 40 + " &amp; done" for i in range(200)]
    chunks = split_message("\n".join(lines))
    assert len(chunks) > 1
    assert all(utf16_len(c) <= CHUNK_UNITS for c in chunks)
    # every chunk keeps its tags balanced (split on line boundaries only)
    assert all(c.count("<b>") == c.count("</b>") for c in chunks)
    assert "".join(chunks).count("line 199") == 1


def test_split_message_hard_splits_one_giant_line_without_breaking_entities():
    text = ("word &amp; " * 1200).strip()
    chunks = split_message(text)
    assert len(chunks) >= 3 and all(utf16_len(c) <= CHUNK_UNITS for c in chunks)
    for chunk in chunks:
        assert not chunk.endswith("&amp") and not chunk.startswith("amp;")


async def test_long_reply_is_sent_in_chunks_with_keyboard_on_last_and_reply_on_first():
    fake = FakeTelegram()
    client = client_for(fake)
    markup = {"inline_keyboard": [[{"text": "Skip", "callback_data": "skip:abc123"}]]}
    await client.send_message(OWNER, "\n".join(f"row {i} " + "x" * 90 for i in range(120)),
                              reply_markup=markup, reply_to=7)
    sent = fake.sent()
    assert len(sent) >= 3
    assert "reply_parameters" in sent[0] and all("reply_parameters" not in p for p in sent[1:])
    assert sent[-1]["reply_markup"] == markup and all("reply_markup" not in p for p in sent[:-1])
    await client.aclose()


async def test_parse_error_falls_back_to_plain_text_once():
    fake = ParseRejectingTelegram()
    client = client_for(fake)
    result = await client.send_message(OWNER, "<b>Acme & <Sons></b> · C++_dev [remote] `x`")
    assert result["message_id"] > 0
    html_try, plain_try = fake.sent()
    assert html_try["parse_mode"] == "HTML" and "parse_mode" not in plain_try
    assert "<b>" not in plain_try["text"] and "Acme &" in plain_try["text"]
    await client.edit_message_text(OWNER, 5, "<i>edited</i> & done")
    edits = fake.sent("editMessageText")
    assert edits[-1]["text"] == "edited & done" and "parse_mode" not in edits[-1]
    await client.aclose()


def test_hitl_card_escapes_hostile_titles_and_companies():
    hostile = HitlRecord(id="0f" * 16, platform="naukri", kind="QUESTION", prompt_text="Rate <C++> & `Go`?",
                         status="OPEN", context={"options": ["<b>", "A&B"]},
                         company_name="Tom & Jerry <Pvt>_*[x]", role_title="SDE <II> & `infra`")
    text, markup = render_hitl(hostile)
    assert "<Pvt>" not in text and "&lt;Pvt&gt;" in text and "&amp; Jerry" in text
    assert "&lt;C++&gt;" in text and markup is not None
    resolved = render_resolved(hostile, "Answered: <b>", icon="⏭")
    assert "&lt;b&gt;" in resolved and "⏭" in resolved and "Tap a button" not in resolved
    assert html_to_plain(text).count("Tom & Jerry <Pvt>") == 1


# --- polling resilience -------------------------------------------------------------------
class FlakyStore(MemoryStore):
    def __init__(self, failures: int):
        super().__init__()
        self.failures = failures

    async def update_telegram_state(self, **changes):
        if self.failures > 0:
            self.failures -= 1
            raise ConnectionResetError("db hiccup after sleep/wake")
        return await super().update_telegram_state(**changes)


async def test_poll_loop_survives_store_errors_and_keeps_polling():
    store = FlakyStore(failures=3)
    fake = FakeTelegram()
    bot = make_bot(store, fake, poll_timeout=0, dispatch_interval=0.01)
    bot.poll_timeout = 0
    stop = asyncio.Event()
    import backend.app.telegram_v2.bot as bot_module

    original = bot_module.MAX_ERROR_BACKOFF_SEC
    bot_module.MAX_ERROR_BACKOFF_SEC = 0.01
    try:
        task = asyncio.create_task(bot.run(stop))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if sum(1 for name, _ in fake.calls if name == "getUpdates") >= 3:
                break
        assert not task.done(), "poll loop must never exit on errors"
        stop.set()
        await asyncio.wait_for(task, 2)
    finally:
        bot_module.MAX_ERROR_BACKOFF_SEC = original
    assert sum(1 for name, _ in fake.calls if name == "getUpdates") >= 3


async def test_network_error_backs_off_boundedly_then_recovers():
    store = MemoryStore()
    fake = FakeTelegram()
    down = {"on": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if down["on"]:
            raise httpx.ConnectError("Network is unreachable (mac asleep)")
        return fake(request)

    bot = make_bot(store, fake)
    bot.client = TelegramClient(TOKEN, transport=httpx.MockTransport(handler), min_send_interval=0)
    delays = [await bot.poll_once() for _ in range(8)]
    assert delays[0] > 0 and delays == sorted(delays) and max(delays) <= 60
    assert (await store.get_telegram_state()).polling_state == "error"
    down["on"] = False
    assert await bot.poll_once() == 0
    assert (await store.get_telegram_state()).polling_state == "polling"
    await bot.client.aclose()


async def test_conflict_diagnosis_reports_webhook_and_absent_legacy_agent():
    class WebhookTelegram(FakeTelegram):
        def __call__(self, request):
            if request.url.path.endswith("/getWebhookInfo"):
                self.calls.append(("getWebhookInfo", {}))
                return httpx.Response(200, json={"ok": True, "result": {"url": "https://example.com/hook"}})
            return super().__call__(request)

    async def not_loaded():
        return False

    fake = WebhookTelegram()
    fake.conflict = True
    store = MemoryStore()
    bot = make_bot(store, fake, conflict_backoff=60, legacy_probe=not_loaded)
    delays = [await bot.poll_once() for _ in range(6)]
    assert delays == [60, 120, 240, 480, 600, 600]  # exponential, capped at 10 min
    error = (await store.get_telegram_state()).last_error
    assert "webhook is set" in error and "rust is still loaded" not in error
    assert sum(1 for name, _ in fake.calls if name == "getWebhookInfo") == 1  # diagnosed once per episode
    await bot.client.aclose()


async def test_offset_survives_restart_and_old_commands_never_replay():
    store = MemoryStore()
    fake = FakeTelegram()
    fake.batches = [[{"update_id": 10, **msg("/pause")}, {"update_id": 11, **msg("/status")}]]
    bot = make_bot(store, fake)
    await bot.poll_once()
    assert (await store.get_telegram_state()).last_update_id == 11
    await bot.client.aclose()
    # restart: a new process reads the persisted offset and Telegram redelivers nothing old
    fake2 = FakeTelegram()
    fake2.batches = [[{"update_id": 11, **msg("/unpause")}, {"update_id": 12, **msg("/help")}]]
    bot2 = make_bot(store, fake2)
    await bot2.poll_once()
    assert fake2.calls[0][1]["offset"] == 12
    replies = [p["text"] for p in fake2.sent()]
    assert len(replies) == 1 and "HITL bot" in replies[0]  # update 11 (already handled) was skipped
    await bot2.client.aclose()


# --- authorization ------------------------------------------------------------------------
async def test_unauthorized_messages_and_callbacks_are_silently_ignored():
    store = MemoryStore()
    fake = FakeTelegram()
    bot = make_bot(store, fake, cfg=config(TELEGRAM_OWNER_USER_ID=str(OWNER)))
    _, hitl = await waiting_job(store)
    await store.mark_hitl_delivered(hitl.id, 500)
    await bot.handle_update(msg("Yes", chat=STRANGER, reply_to=500))
    await bot.handle_update(callback(f"ans:{hitl.ref}:0", 500, chat=STRANGER))
    await bot.handle_update(msg("Yes", chat=OWNER, user=STRANGER))  # right chat, wrong user (group)
    assert (await store.get_hitl(hitl.id)).status == "OPEN"
    assert fake.sent() == [] and fake.sent("answerCallbackQuery") == []
    await bot.client.aclose()


# --- callbacks ----------------------------------------------------------------------------
async def test_double_tap_is_idempotent_and_always_answers_the_callback():
    store = MemoryStore()
    fake = FakeTelegram()
    bot = make_bot(store, fake)
    record, hitl = await waiting_job(store)
    await store.mark_hitl_delivered(hitl.id, 500)
    await bot.handle_update(callback(f"ans:{hitl.ref}:0", 500, cid="a"))
    await bot.handle_update(callback(f"ans:{hitl.ref}:1", 500, cid="b"))
    answers = fake.sent("answerCallbackQuery")
    assert [a["callback_query_id"] for a in answers] == ["a", "b"]
    assert "Already answered" in answers[1]["text"]
    final = await store.get_hitl(hitl.id)
    assert final.status == "ANSWERED" and final.answer_text == "Yes"
    requeues = [e for e in store.events if e["application_id"] == record.id and e["reason"] == "hitl_resolved_requeued"]
    assert len(requeues) == 1  # never double-enqueued
    edits = fake.sent("editMessageText")
    assert edits and all(e["reply_markup"] == {"inline_keyboard": []} for e in edits)
    assert "✅ Answered: Yes" in edits[0]["text"]
    await bot.client.aclose()


async def test_skip_button_edits_with_skip_icon_and_callback_answered_even_on_error():
    store = MemoryStore()
    fake = FakeTelegram()
    bot = make_bot(store, fake)
    _, hitl = await waiting_job(store)
    await store.mark_hitl_delivered(hitl.id, 501)
    await bot.handle_update(callback(f"skip:{hitl.ref}", 501, cid="s"))
    assert "⏭ Skipped" in fake.sent("editMessageText")[-1]["text"]

    async def boom(*_a, **_k):
        raise RuntimeError("db down")

    _, other = await waiting_job(store, 2)
    await store.mark_hitl_delivered(other.id, 502)
    bot.resolver.skip = boom
    await bot.handle_update(callback(f"skip:{other.ref}", 502, cid="err"))
    last = fake.sent("answerCallbackQuery")[-1]
    assert last["callback_query_id"] == "err" and "failed" in last["text"]
    await bot.client.aclose()


# --- reply resolution ---------------------------------------------------------------------
async def test_swipe_reply_targets_the_exact_request_among_several():
    store = MemoryStore()
    fake = FakeTelegram()
    bot = make_bot(store, fake)
    _, first = await waiting_job(store, 1, options=())
    _, second = await waiting_job(store, 2, options=(), prompt="Current city?")
    await store.mark_hitl_delivered(first.id, 601)
    await store.mark_hitl_delivered(second.id, 602)
    await bot.handle_update(msg("Pune", reply_to=602))
    assert (await store.get_hitl(second.id)).answer_text == "Pune"
    assert (await store.get_hitl(first.id)).status == "OPEN"
    await bot.client.aclose()


async def test_unthreaded_reply_goes_to_the_agent_and_offline_lists_refs_without_guessing():
    """Phase 9C: plain text is LLM-first; with no provider the deterministic fallback never guesses."""
    store = MemoryStore()
    fake = FakeTelegram()
    bot = make_bot(store, fake)
    _, first = await waiting_job(store, 1, options=())
    _, second = await waiting_job(store, 2, options=(), company="Beta & <Co>")
    await bot.handle_update(msg("Bangalore"))
    await bot.drain_agent()
    reply = fake.sent()[-1]["text"]
    assert first.ref in reply and second.ref in reply and "won't guess" in reply and "&lt;Co&gt;" in reply
    assert (await store.get_hitl(first.id)).status == "OPEN" and (await store.get_hitl(second.id)).status == "OPEN"
    await bot.client.aclose()


async def test_chit_chat_and_unthreaded_answers_both_go_to_the_agent():
    class RecordingAgent:
        def __init__(self):
            self.calls = []

        async def run_chat(self, text, *, chat_key, source):
            self.calls.append((text, chat_key, source))
            return {"reply_html": "noted", "confirmation": None, "hitl_resolutions": []}

    store = MemoryStore()
    fake = FakeTelegram()
    agent = RecordingAgent()
    bot = make_bot(store, fake, agent=agent)
    _, hitl = await waiting_job(store, options=())
    await bot.handle_update(msg("thanks!"))
    await bot.handle_update(msg("Immediately"))
    await bot.drain_agent()
    assert [c[0] for c in agent.calls] == ["thanks!", "Immediately"]
    assert all(c[2] == "telegram" and c[1] == agent_chat_key("telegram", OWNER) for c in agent.calls)
    assert (await store.get_hitl(hitl.id)).status == "OPEN"  # only the agent's tool may resolve it
    assert fake.sent()[-1]["text"] == "🤖 noted"
    await bot.client.aclose()


async def test_agent_tasks_are_bounded_and_never_block_polling():
    gate = asyncio.Event()

    class SlowAgent:
        async def run(self, text):
            await gate.wait()
            return {"reply": "done", "verdict": "ok"}

    store = MemoryStore()
    fake = FakeTelegram()
    bot = make_bot(store, fake, agent=SlowAgent())
    for i in range(5):
        await bot.handle_update(msg(f"/ask question {i}", message_id=i + 1))
    await asyncio.sleep(0.01)
    busy = [p["text"] for p in fake.sent() if "still working" in p["text"]]
    assert len(busy) == 2  # 3 running + 2 told to retry; polling was never blocked
    gate.set()
    await bot.drain_agent()
    assert sum(1 for p in fake.sent() if p["text"] == "🤖 done") == 3
    await bot.client.aclose()


# --- HITL expiry --------------------------------------------------------------------------
async def test_stale_hitl_expires_job_filtered_and_auth_never_expires():
    store = MemoryStore()
    record, question = await waiting_job(store, 1)
    _, otp = await waiting_job(store, 2, kind="OTP", options=())
    auth_id = await store.create_hitl(None, "naukri", "AUTH", "[Naukri] Session expired", {})
    old = datetime.now(UTC) - timedelta(days=8)
    for row in store.hitl:
        row["created_at"] = old
    service = HITLResolutionService(store)
    expired = await service.expire_stale()
    assert {h.id for h in expired} == {question.id, otp.id}
    assert (await store.get_hitl(auth_id)).status == "OPEN"
    job = await store.get_application(record.id)
    assert job.state is S.FILTERED_OUT and job.reason == EXPIRED_REASON
    assert await service.expire_stale() == []  # idempotent


async def test_expiry_never_touches_never_replay_jobs():
    store = MemoryStore()
    record, _hitl = await waiting_job(store, 1)
    record = await store.transition(record, S.SUBMISSION_UNKNOWN, "questionnaire_stalled")
    for row in store.hitl:
        row["created_at"] = datetime.now(UTC) - timedelta(days=30)
    await HITLResolutionService(store).expire_stale()
    assert (await store.get_application(record.id)).state is S.SUBMISSION_UNKNOWN


# --- digest -------------------------------------------------------------------------------
def _service(store: MemoryStore) -> Any:
    return _Service(store)


class _Service:
    """Minimal BrowserService stand-in for housekeeping-only Worker tests."""

    def __init__(self, store):
        self.store = store
        self.adapters: dict = {}
        self.ai = None


async def test_digest_fires_once_per_ist_day_across_worker_restarts():
    store = MemoryStore()
    sent: list[str] = []

    async def notify(text):
        sent.append(text)

    first = Worker(_service(store), clock=lambda: IST_2105, notify=notify, digest=DigestScheduler(store, hour=21))
    await first.housekeeping()
    await first.housekeeping()
    restarted = Worker(_service(store), clock=lambda: IST_2105 + timedelta(minutes=3), notify=notify,
                       digest=DigestScheduler(store, hour=21))
    await restarted.housekeeping()
    assert len(sent) == 1 and "Daily digest" in sent[0]
    before = Worker(_service(store), clock=lambda: IST_2105 - timedelta(hours=1), notify=notify,
                    digest=DigestScheduler(store, hour=21))
    await before.housekeeping()
    assert len(sent) == 1
    tomorrow = IST_2105 + timedelta(days=1)
    nextday = Worker(_service(store), clock=lambda: tomorrow, notify=notify, digest=DigestScheduler(store, hour=21))
    await nextday.housekeeping()
    assert len(sent) == 2


async def test_digest_send_failure_releases_the_claim_for_a_retry():
    store = MemoryStore()
    attempts: list[str] = []

    async def flaky(text):
        attempts.append(text)
        if len(attempts) == 1:
            raise httpx.ConnectError("offline")

    worker = Worker(_service(store), clock=lambda: IST_2105, notify=flaky, digest=DigestScheduler(store, hour=21))
    await worker.housekeeping()
    assert (await store.get_telegram_state()).last_digest_on is None
    await worker.housekeeping()
    assert len(attempts) == 2 and (await store.get_telegram_state()).last_digest_on is not None


@pytest.mark.parametrize("hour", [None])
async def test_digest_disabled_never_sends(hour):
    store = MemoryStore()
    sent: list[str] = []

    async def notify(text):
        sent.append(text)

    await Worker(_service(store), clock=lambda: IST_2105, notify=notify,
                 digest=DigestScheduler(store, hour=hour)).housekeeping()
    assert sent == [] and QUESTION


async def test_waiting_worker_keeps_heartbeating_between_cycles():
    """Live 2026-11-27: a RUNNING worker sleeps 10 min between cycles; health calls >5 min stale."""
    from backend.app.browser_v2.store import WorkerControl, WorkerState

    store = MemoryStore(worker=WorkerControl(desired_state=WorkerState.RUNNING))

    async def no_wait(_seconds):
        return None

    worker = Worker(_service(store), sleeper=no_wait, idle_poll_sec=15)
    assert await worker.sleep(600, heartbeat="SLEEPING") is True
    assert store.heartbeats.count("SLEEPING") >= 9  # ~1/min across the 10-min wait
    assert await worker.sleep(120) is True and store.heartbeats.count("SLEEPING") <= 10  # jitter sleeps: none
