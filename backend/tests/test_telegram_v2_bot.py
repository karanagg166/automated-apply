"""Phase 4 Telegram HITL bot against a mocked Bot API (no network).

Covers owner-only auth, token redaction, 409 conflict resilience, the outbound
dispatcher (all kinds, msg id persistence, no double-send), inbound matching
(button > command > swipe-reply > plain text), option validation, semantic
cache learning (user overrides llm; /once and OTP never cached), priority
re-enqueue + never-replay, and the remote-control commands.
"""

import asyncio
import json
import logging

import httpx
import pytest

from backend.app.ai_v2.embeddings import DeterministicTestEmbedder
from backend.app.ai_v2.semantic_cache import MemoryCacheStore, SemanticCache
from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore, WorkerState
from backend.app.telegram_v2.bot import TelegramBot, telegram_status
from backend.app.telegram_v2.client import (
    TelegramClient,
    TelegramNetworkError,
    install_log_redaction,
    redact,
)
from backend.app.telegram_v2.config import TelegramConfig
from backend.app.telegram_v2.formatting import CONFLICT_MESSAGE

TOKEN = "123456789:TEST_FAKE_TOKEN_ONLY_abcdefghijklmnop"
OWNER = 4242
STRANGER = 9999
QUESTION = "Are you willing to relocate to Pune?"


class FakeTelegram:
    """Scripted Bot API: records every call; getUpdates serves queued batches."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.batches: list[list[dict]] = []
        self.conflict = False
        self.next_message_id = 100

    def __call__(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        payload = json.loads(request.content or b"{}")
        self.calls.append((method, payload))
        if method == "getUpdates":
            if self.conflict:
                return httpx.Response(409, json={"ok": False, "error_code": 409,
                                                 "description": "Conflict: terminated by other getUpdates request"})
            return httpx.Response(200, json={"ok": True, "result": self.batches.pop(0) if self.batches else []})
        if method == "sendMessage":
            self.next_message_id += 1
            return httpx.Response(200, json={"ok": True, "result": {"message_id": self.next_message_id}})
        return httpx.Response(200, json={"ok": True, "result": True})

    def sent(self, method="sendMessage"):
        return [payload for name, payload in self.calls if name == method]


def config(**extra):
    env = {"TELEGRAM_BOT_TOKEN": TOKEN, "TELEGRAM_OWNER_CHAT_ID": str(OWNER)} | extra
    return TelegramConfig.from_env(env)


@pytest.fixture
def fake():
    return FakeTelegram()


@pytest.fixture
def cache():
    return SemanticCache(MemoryCacheStore(), DeterministicTestEmbedder())


@pytest.fixture
def store():
    return MemoryStore()


def make_bot(store, fake, cache=None, **kw):
    return TelegramBot(kw.pop("cfg", config()), store, cache=cache, transport=httpx.MockTransport(fake),
                       min_send_interval=0, **kw)


async def waiting_job(store, i=1, *, kind="QUESTION", prompt=QUESTION, options=("Yes", "No"),
                      company="Acme", state=S.WAITING_FOR_USER):
    record = await store.upsert_discovered(JobListing(
        platform="naukri", external_job_id=f"j{i}", url=f"https://example.com/{i}",
        title="Python Developer", company=company))
    record = await store.transition(record, S.APPLYING, "apply_started", count_attempt=True)
    record = await store.transition(record, state, "question_requires_owner")
    hitl_id = await store.create_hitl(record, "naukri", kind, prompt,
                                      {"options": list(options), "context": {"resolver_reason": "llm_unconfigured"}})
    return record, await store.get_hitl(hitl_id)


def msg(text, *, chat=OWNER, user=None, reply_to=None, message_id=1):
    message = {"message_id": message_id, "chat": {"id": chat, "type": "private"},
               "from": {"id": user if user is not None else chat}, "text": text}
    if reply_to is not None:
        message["reply_to_message"] = {"message_id": reply_to}
    return {"message": message}


def callback(data, message_id, *, chat=OWNER, user=None, cid="cb1"):
    return {"callback_query": {"id": cid, "data": data, "from": {"id": user if user is not None else chat},
                               "message": {"message_id": message_id, "chat": {"id": chat}}}}


def last_reply(fake):
    return fake.sent()[-1]["text"]


# --- config, auth, redaction ------------------------------------------------------------
async def test_unconfigured_bot_records_status_and_returns(store, fake):
    bot = make_bot(store, fake, cfg=TelegramConfig.from_env({}))
    await asyncio.wait_for(bot.run(asyncio.Event()), timeout=1)
    status = await telegram_status(store, bot.config)
    assert status["configured"] is False and status["polling_state"] == "unconfigured"
    assert "TELEGRAM_BOT_TOKEN" in (status["last_error"] or "") and fake.calls == []


def test_malformed_token_is_unconfigured_and_never_echoed():
    cfg = TelegramConfig.from_env({"TELEGRAM_BOT_TOKEN": "not-a-token", "TELEGRAM_OWNER_CHAT_ID": "4242"})
    assert not cfg.configured and cfg.problem == "TELEGRAM_BOT_TOKEN is malformed"
    assert "not-a-token" not in json.dumps(cfg.public()) and "not-a-token" not in repr(cfg)


async def test_unauthorized_chat_and_user_are_ignored(store, fake):
    bot = make_bot(store, fake, cfg=config(TELEGRAM_OWNER_USER_ID="77"))
    await store.set_worker_control(WorkerState.RUNNING)
    await bot.handle_update(msg("/pause", chat=STRANGER))
    await bot.handle_update(msg("/pause", chat=OWNER, user=STRANGER))  # owner chat, wrong user id
    await bot.handle_update(callback("resume:naukri", 5, chat=STRANGER))
    assert fake.calls == []  # no reply at all
    assert (await store.get_worker_control()).desired_state is WorkerState.RUNNING
    await bot.handle_update(msg("/pause", chat=OWNER, user=77))
    assert (await store.get_worker_control()).desired_state is WorkerState.PAUSED


async def test_bot_token_never_leaks_in_errors_logs_or_status(store, caplog):
    def broken(request):
        raise httpx.ConnectError(f"cannot reach {request.url}", request=request)

    client = TelegramClient(TOKEN, transport=httpx.MockTransport(broken), min_send_interval=0)
    with pytest.raises(TelegramNetworkError) as error:
        await client.get_updates(None, timeout=0)
    assert TOKEN not in str(error.value) and error.value.__cause__ is None and TOKEN not in repr(client)
    await client.aclose()
    install_log_redaction()
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("httpx").warning("HTTP Request: POST https://api.telegram.org/bot%s/getUpdates", TOKEN)
    # Another redaction filter (legacy local_agent) may run first; either way the token is gone.
    assert TOKEN not in caplog.text and "REDACTED" in caplog.text
    assert redact(f"https://api.telegram.org/bot{TOKEN}/getMe") == "https://api.telegram.org/bot<REDACTED>/getMe"
    bot = TelegramBot(config(), store, transport=httpx.MockTransport(broken), min_send_interval=0)
    assert await bot.poll_once() > 0
    status = await telegram_status(store, bot.config)
    assert status["polling_state"] == "error" and TOKEN not in json.dumps(status, default=str)
    assert status["owner_chat_id"] == "•242"
    await bot.client.aclose()


# --- 409 conflict ---------------------------------------------------------------------------
async def test_conflict_sets_status_backs_off_and_recovers(store, fake, caplog):
    fake.conflict = True
    bot = make_bot(store, fake, conflict_backoff=60)
    with caplog.at_level(logging.WARNING):
        assert await bot.poll_once() == 60
        assert await bot.poll_once() == 60
    assert caplog.text.count("409 conflict") == 1  # no log spam
    status = await telegram_status(store, bot.config)
    assert status["polling_state"] == "conflict" and status["conflict_detected"] is True
    assert status["last_error"] == CONFLICT_MESSAGE and status["conflict_detected_at"] is not None
    fake.conflict = False
    assert await bot.poll_once() == 0
    status = await telegram_status(store, bot.config)
    assert status["polling_state"] == "polling" and status["last_error"] is None
    await bot.client.aclose()


async def test_conflict_never_crashes_the_running_loop(store, fake):
    fake.conflict = True
    bot = make_bot(store, fake, conflict_backoff=0.01, dispatch_interval=0.01)
    stop = asyncio.Event()
    ticks = 0

    async def application_worker():
        nonlocal ticks
        while not stop.is_set():
            ticks += 1
            await asyncio.sleep(0.005)

    task = asyncio.create_task(bot.run(stop))
    worker = asyncio.create_task(application_worker())
    await asyncio.sleep(0.15)
    stop.set()
    await asyncio.wait_for(asyncio.gather(task, worker), timeout=2)
    assert ticks > 5 and len(fake.sent("getUpdates")) >= 2
    assert (await store.get_telegram_state()).polling_state == "stopped"


# --- outbound dispatcher ---------------------------------------------------------------------
async def test_dispatcher_formats_every_kind_and_persists_message_ids(store, fake):
    _, question = await waiting_job(store, 1)
    await store.create_hitl(None, "naukri", "AUTH", "[Naukri] Session expired", {})
    await waiting_job(store, 2, kind="CAPTCHA", prompt="Naukri needs CAPTCHA", options=())
    await waiting_job(store, 3, kind="OTP", prompt="Naukri needs OTP", options=())
    await waiting_job(store, 4, kind="ERROR", prompt="apply_control_changed", options=())
    bot = make_bot(store, fake)
    assert await bot.dispatch_once() == 5
    sent = fake.sent()
    q = sent[0]
    assert QUESTION in q["text"] and "Acme" in q["text"] and "llm_unconfigured" in q["text"]
    assert f"/once {question.ref}" in q["text"] and "1. Yes" in q["text"]
    buttons = [b["callback_data"] for row in q["reply_markup"]["inline_keyboard"] for b in row]
    assert buttons == [f"ans:{question.ref}:0", f"ans:{question.ref}:1", f"skip:{question.ref}"]
    auth = sent[1]
    assert "login-setup --portal naukri" in auth["text"] and "/resume naukri" in auth["text"]
    assert auth["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == "resume:naukri"
    assert "retry:" in json.dumps(sent[2]["reply_markup"]) and "OTP code" in sent[3]["text"]
    assert "/retry" in sent[4]["text"] and "skip:" in json.dumps(sent[4]["reply_markup"])
    rows, _ = await store.list_hitl("OPEN")
    assert sorted(r.telegram_msg_id for r in rows) == [101, 102, 103, 104, 105]
    # A restarted bot on the same store never re-sends delivered requests.
    restarted = make_bot(store, fake)
    assert await restarted.dispatch_once() == 0 and len(fake.sent()) == 5


async def test_many_options_fall_back_to_numbered_text(store, fake):
    options = tuple(f"Option {i}" for i in range(1, 9))
    await waiting_job(store, 1, options=options)
    bot = make_bot(store, fake)
    await bot.dispatch_once()
    sent = fake.sent()[0]
    assert "8. Option 8" in sent["text"]
    assert [b["callback_data"][:4] for row in sent["reply_markup"]["inline_keyboard"] for b in row] == ["skip"]


async def test_dispatch_is_throttled_to_one_message_per_second(store):
    clock = {"now": 0.0}
    waits: list[float] = []

    async def sleeper(seconds):
        waits.append(seconds)
        clock["now"] += seconds

    fake = FakeTelegram()
    client = TelegramClient(TOKEN, transport=httpx.MockTransport(fake), clock=lambda: clock["now"],
                            sleeper=sleeper)
    for i in range(3):
        await waiting_job(store, i)
    bot = TelegramBot(config(), store, client=client)
    assert await bot.dispatch_once() == 3
    assert waits == [1.0, 1.0]
    await client.aclose()


# --- inbound resolution --------------------------------------------------------------------
async def test_swipe_reply_resolves_exact_item_among_many(store, fake, cache):
    jobs = [await waiting_job(store, i, company=f"Co{i}") for i in range(1, 6)]
    bot = make_bot(store, fake, cache)
    await bot.dispatch_once()
    target = await store.get_hitl(jobs[2][1].id)
    await bot.handle_update(msg("Yes", reply_to=target.telegram_msg_id, message_id=500))
    statuses = {r.id: r.status for r in (await store.list_hitl(None))[0]}
    assert statuses[target.id] == "ANSWERED" and list(statuses.values()).count("OPEN") == 4
    resolved = await store.get_hitl(target.id)
    assert resolved.answer_text == "Yes" and resolved.resolved_via == "telegram"
    app = await store.get_application(jobs[2][0].id)
    assert app.state is S.SCORED and app.retry_after is not None
    events = await store.application_events(app.id)
    assert events[-1]["event_type"] == "hitl_resolved_requeued" and events[-1]["payload"]["answer"] == "Yes"
    hit = await cache.lookup("screening_qa", QUESTION)
    assert hit is not None and hit.entry.answer_text == "Yes" and hit.entry.source == "user"
    assert "re-queued" in last_reply(fake) and fake.sent()[-1]["reply_parameters"]["message_id"] == 500
    edits = fake.sent("editMessageText")
    assert edits[-1]["message_id"] == target.telegram_msg_id and edits[-1]["reply_markup"] == {"inline_keyboard": []}


async def test_plain_text_refuses_to_guess_between_open_questions(store, fake):
    _, first = await waiting_job(store, 1)
    _, second = await waiting_job(store, 2)
    bot = make_bot(store, fake)
    await bot.handle_update(msg("Yes"))
    await bot.drain_agent()  # Phase 6A: non-command free text is routed via the background agent task
    assert "won't guess" in last_reply(fake) and first.ref in last_reply(fake) and second.ref in last_reply(fake)
    assert [r.status for r in (await store.list_hitl(None))[0]] == ["OPEN", "OPEN"]
    await bot.handle_update(msg(f"/skip {first.ref}"))
    await bot.handle_update(msg("no"))  # exactly one QUESTION open now
    assert (await store.get_hitl(second.id)).answer_text == "No"


async def test_inline_button_resolves_once_and_rejects_double_click(store, fake, cache):
    record, hitl = await waiting_job(store, 1)
    bot = make_bot(store, fake, cache)
    await bot.dispatch_once()
    delivered = await store.get_hitl(hitl.id)
    await bot.handle_update(callback(f"ans:{hitl.ref}:0", delivered.telegram_msg_id, cid="c1"))
    assert (await store.get_hitl(hitl.id)).answer_text == "Yes"
    assert fake.sent("answerCallbackQuery")[-1]["callback_query_id"] == "c1"
    assert fake.sent("editMessageText")[-1]["reply_markup"] == {"inline_keyboard": []}
    entries_before = (await cache.stats())["total_entries"]
    events_before = len(await store.application_events(record.id))
    await bot.handle_update(callback(f"ans:{hitl.ref}:1", delivered.telegram_msg_id, cid="c2"))
    assert "Already answered" in fake.sent("answerCallbackQuery")[-1]["text"]
    assert (await store.get_hitl(hitl.id)).answer_text == "Yes"
    assert (await cache.stats())["total_entries"] == entries_before
    assert len(await store.application_events(record.id)) == events_before


async def test_invalid_option_keeps_request_open_then_index_maps(store, fake):
    _, hitl = await waiting_job(store, 1)
    bot = make_bot(store, fake)
    await bot.dispatch_once()
    message_id = (await store.get_hitl(hitl.id)).telegram_msg_id
    await bot.handle_update(msg("Maybe later", reply_to=message_id))
    assert "not one of the options" in last_reply(fake) and "1. Yes" in last_reply(fake)
    assert (await store.get_hitl(hitl.id)).status == "OPEN"
    await bot.handle_update(msg("2", reply_to=message_id))
    assert (await store.get_hitl(hitl.id)).answer_text == "No"


async def test_user_answer_overrides_prior_llm_cache_entry(store, fake, cache):
    await cache.put("screening_qa", QUESTION, "No", "llm")
    _, hitl = await waiting_job(store, 1)
    bot = make_bot(store, fake, cache)
    await bot.handle_update(msg(f"/answer {hitl.ref} yes"))
    hit = await cache.lookup("screening_qa", QUESTION)
    assert hit.entry.answer_text == "Yes" and hit.entry.source == "user"


async def test_once_and_otp_answers_are_never_cached(store, fake, cache):
    once_job, once = await waiting_job(store, 1, prompt="What is your notice period in days?", options=())
    otp_job, otp = await waiting_job(store, 2, kind="OTP", prompt="Naukri needs OTP", options=())
    bot = make_bot(store, fake, cache)
    await bot.handle_update(msg(f"/once {once.ref} 30"))
    await bot.dispatch_once()
    await bot.handle_update(msg("482913", reply_to=(await store.get_hitl(otp.id)).telegram_msg_id))
    assert (await cache.stats())["total_entries"] == 0
    assert (await store.get_application(once_job.id)).state is S.SCORED
    assert (await store.get_application(otp_job.id)).state is S.SCORED
    assert await store.hitl_answers(once_job.id) == {"What is your notice period in days?": "30"}
    assert await store.hitl_answers(otp_job.id) == {"Naukri needs OTP": "482913"}
    otp_event = (await store.application_events(otp_job.id))[-1]
    assert otp_event["payload"]["answer"] == "[redacted]"


@pytest.mark.parametrize("terminal", [S.APPLIED, S.SUBMISSION_UNKNOWN])
async def test_terminal_applications_are_never_requeued(store, fake, cache, terminal):
    record, hitl = await waiting_job(store, 1)
    current = await store.get_application(record.id)
    if terminal is S.APPLIED:
        current = await store.transition(current, S.APPLYING, "operator_retry")
    await store.transition(current, terminal, "confirmed_elsewhere")
    bot = make_bot(store, fake, cache)
    await bot.handle_update(msg(f"/answer {hitl.ref} Yes"))
    assert (await store.get_hitl(hitl.id)).status == "ANSWERED"
    assert (await store.get_application(record.id)).state is terminal
    assert "never re-applied" in last_reply(fake)
    assert await store.requeued_applications("naukri") == []


async def test_skip_retry_and_resume_portal(store, fake):
    skipped_job, skip = await waiting_job(store, 1)
    error_job, error = await waiting_job(store, 2, kind="ERROR", prompt="apply_control_changed", options=())
    await store.record_auth("naukri", "AUTH_REQUIRED")
    auth_id = await store.create_hitl(None, "naukri", "AUTH", "[Naukri] Session expired", {})
    bot = make_bot(store, fake)
    await bot.dispatch_once()
    await bot.handle_update(msg(f"/skip {skip.ref}"))
    skipped = await store.get_application(skipped_job.id)
    assert skipped.state is S.FILTERED_OUT and skipped.reason == "skipped_by_owner_hitl"
    assert (await store.get_hitl(skip.id)).status == "CANCELLED"
    await bot.handle_update(msg(f"/retry {error.ref}"))
    assert (await store.get_application(error_job.id)).state is S.SCORED
    await bot.handle_update(msg("/resume linkedin"))
    assert "Unknown portal" in last_reply(fake)
    await bot.handle_update(msg("/resume naukri"))
    assert (await store.get_rules("naukri")).auth_status == "UNKNOWN"
    auth = await store.get_hitl(auth_id)
    assert auth.status == "ANSWERED" and auth.resolved_via == "telegram"
    assert any(e["message_id"] == auth.telegram_msg_id for e in fake.sent("editMessageText"))


async def test_resume_button_callback(store, fake):
    await store.record_auth("naukri", "AUTH_REQUIRED")
    await store.create_hitl(None, "naukri", "AUTH", "[Naukri] Session expired", {})
    bot = make_bot(store, fake)
    await bot.dispatch_once()
    await bot.handle_update(callback("resume:naukri", fake.next_message_id))
    assert (await store.get_rules("naukri")).auth_status == "UNKNOWN"
    assert await store.count_open_hitl() == 0 and "resumed" in fake.sent("answerCallbackQuery")[-1]["text"]


async def test_remote_control_commands(store, fake):
    _, hitl = await waiting_job(store, 1)
    bot = make_bot(store, fake)
    await bot.handle_update(msg("/pause"))
    assert (await store.get_worker_control()).desired_state is WorkerState.PAUSED
    await bot.handle_update(msg("/start_worker"))
    assert (await store.get_worker_control()).desired_state is WorkerState.RUNNING
    await bot.handle_update(msg("/pause@AutomatedApplyBot"))
    await bot.handle_update(msg("/unpause"))
    assert (await store.get_worker_control()).desired_state is WorkerState.RUNNING
    await bot.handle_update(msg("/status"))
    status = last_reply(fake)
    assert "Worker <b>RUNNING</b>" in status and "DRY RUN" in status and "naukri" in status
    assert "Open HITL: <b>1</b>" in status
    await bot.handle_update(msg("/pending"))
    assert hitl.ref in last_reply(fake) and "QUESTION" in last_reply(fake)
    await bot.handle_update(msg("/help"))
    assert "/once" in last_reply(fake)
    await bot.handle_update(msg("/selfdestruct"))
    assert last_reply(fake) == "Unknown command. /help"


# --- offsets ---------------------------------------------------------------------------------
async def test_offset_persists_and_restart_never_replays_old_commands(store, fake):
    fake.batches = [[{"update_id": 10, **msg("/pause")}, {"update_id": 11, "message": {"chat": "broken"}}]]
    bot = make_bot(store, fake)
    assert await bot.poll_once() == 0
    assert (await store.get_telegram_state()).last_update_id == 11  # poison update still advances
    assert (await store.get_worker_control()).desired_state is WorkerState.PAUSED
    restarted = make_bot(store, fake)
    await restarted.poll_once()
    assert fake.sent("getUpdates")[-1]["offset"] == 12
    assert fake.sent("getUpdates")[-1]["allowed_updates"] == ["message", "callback_query"]
    assert fake.sent("getUpdates")[-1]["timeout"] == 25
