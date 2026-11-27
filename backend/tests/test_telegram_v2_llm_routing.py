"""Phase 9C Telegram routing: buttons / swipe-reply / OTP digits / slash commands stay direct,
everything else goes to the LLM agent; Confirm/Cancel buttons with a 10-minute TTL; typing
"confirm"; the 12-turn memory window and /forget (mocked Bot API, scripted LLM)."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import agent_chat_key
from backend.tests.agent_v2_fakes import (
    NOW,
    ScriptedRouter,
    agent,
    final,
    store_with_profile,
    tool,
)
from backend.tests.test_telegram_v2_bot import (
    OWNER,
    FakeTelegram,
    callback,
    last_reply,
    make_bot,
    msg,
    waiting_job,
)

KEY = agent_chat_key("telegram", OWNER)


class ExplodingAgent:
    async def run_chat(self, text, *, chat_key, source):  # pragma: no cover - must not be reached
        raise AssertionError(f"agent must not see {text!r}")


async def test_swipe_reply_otp_digits_and_commands_never_reach_the_agent():
    store = store_with_profile()
    fake = FakeTelegram()
    bot = make_bot(store, fake, agent=ExplodingAgent())
    _, question = await waiting_job(store, 1, options=())
    otp_job, otp = await waiting_job(store, 2, kind="OTP", prompt="Naukri needs OTP", options=())
    await store.mark_hitl_delivered(question.id, 700)
    await bot.handle_update(msg("Pune", reply_to=700))
    assert (await store.get_hitl(question.id)).answer_text == "Pune"
    await bot.handle_update(msg("482913"))
    assert (await store.get_hitl(otp.id)).answer_text == "482913"
    assert (await store.get_application(otp_job.id)).state is S.SCORED
    await bot.handle_update(msg("/pending"))
    await bot.handle_update(msg("/status"))
    await bot.drain_agent()
    assert "Open HITL" in last_reply(fake)
    await bot.client.aclose()


async def test_digits_without_an_open_otp_and_free_text_go_to_the_agent():
    store = store_with_profile()
    fake = FakeTelegram()
    router = ScriptedRouter([final("60 is a number."), final("All good.")])
    bot = make_bot(store, fake, agent=agent(store, router))
    await bot.handle_update(msg("60"))
    await bot.drain_agent()
    await bot.handle_update(msg("what should we try next?"))
    await bot.drain_agent()
    assert len(router.prompts) == 2 and last_reply(fake) == "🤖 All good."
    await bot.handle_update(msg("thanks!"))  # a pleasantry: the zero-LLM semantic router answers it
    await bot.drain_agent()
    assert len(router.prompts) == 2 and last_reply(fake).startswith("🤖 ") and last_reply(fake) != "🤖 All good."
    await bot.client.aclose()


async def test_llm_agent_resolves_the_open_question_and_strips_the_card():
    store = store_with_profile()
    fake = FakeTelegram()
    record, hitl = await waiting_job(store, 1)
    router = ScriptedRouter([tool("resolve_hitl_via_agent", hitl_id_or_ref=hitl.ref, answer="Yes"),
                             final("Answered the relocation question.")])
    bot = make_bot(store, fake, agent=agent(store, router))
    await bot.dispatch_once()
    await bot.handle_update(msg("yes, I can relocate", message_id=55))
    await bot.drain_agent()
    assert (await store.get_hitl(hitl.id)).answer_text == "Yes"
    assert (await store.get_application(record.id)).state is S.SCORED
    assert hitl.ref in router.prompts[0][2]  # the open request was in the agent's context
    reply = fake.sent()[-1]
    assert reply["text"].startswith("🤖 Answered") and "re-queued" in reply["text"]
    assert reply["reply_parameters"]["message_id"] == 55
    assert fake.sent("editMessageText")[-1]["reply_markup"] == {"inline_keyboard": []}
    await bot.client.aclose()


async def risky_bot(store, fake, clock):
    router = ScriptedRouter([tool("update_portal_rule", portals=["naukri"], patch={"auto_apply_enabled": True}),
                             final("This enables live auto-apply; please confirm.")])
    bot = make_bot(store, fake, agent=agent(store, router, clock=lambda: clock["now"]))
    await bot.handle_update(msg("turn on auto apply for naukri", message_id=10))
    await bot.drain_agent()
    markup = fake.sent()[-1]["reply_markup"]["inline_keyboard"][0]
    confirm, cancel = markup[0]["callback_data"], markup[1]["callback_data"]
    assert confirm.startswith("agc:") and cancel.startswith("agx:") and confirm[4:] == cancel[4:]
    assert not (await store.get_rules("naukri")).auto_apply_enabled
    return bot, confirm, cancel


async def test_confirm_button_applies_the_risky_write_and_is_audited():
    store, fake, clock = store_with_profile(), FakeTelegram(), {"now": NOW}
    bot, confirm, _ = await risky_bot(store, fake, clock)
    await bot.handle_update(callback(confirm, fake.next_message_id, cid="ok1"))
    await bot.drain_agent()
    assert (await store.get_rules("naukri")).auto_apply_enabled
    assert fake.sent("answerCallbackQuery")[-1]["callback_query_id"] == "ok1"
    assert any(p.get("reply_markup") == {"inline_keyboard": []} for p in fake.sent("editMessageReplyMarkup"))
    assert "Portal rules updated" in last_reply(fake)
    assert [e.outcome for e in store.agent_audit] == ["needs_confirmation", "ok"]
    await bot.handle_update(callback(confirm, fake.next_message_id, cid="ok2"))  # double tap: nothing left
    await bot.drain_agent()
    assert "Nothing to confirm" in last_reply(fake) and len(store.agent_audit) == 2
    await bot.client.aclose()


async def test_cancel_button_and_ttl_expiry_change_nothing_but_are_audited():
    store, fake, clock = store_with_profile(), FakeTelegram(), {"now": NOW}
    bot, _, cancel = await risky_bot(store, fake, clock)
    await bot.handle_update(callback(cancel, fake.next_message_id, cid="c1"))
    assert fake.sent("answerCallbackQuery")[-1]["text"] == "Cancelled."
    assert not (await store.get_rules("naukri")).auto_apply_enabled
    assert [e.outcome for e in store.agent_audit] == ["needs_confirmation", "cancelled"]

    store2, fake2, clock2 = store_with_profile(), FakeTelegram(), {"now": NOW}
    bot2, confirm2, _ = await risky_bot(store2, fake2, clock2)
    clock2["now"] += timedelta(minutes=10, seconds=1)
    await bot2.handle_update(callback(confirm2, fake2.next_message_id, cid="late"))
    await bot2.drain_agent()
    assert not (await store2.get_rules("naukri")).auto_apply_enabled and "expired" in last_reply(fake2)
    assert [e.error for e in store2.agent_audit][-1] == "confirmation_expired"
    await bot.client.aclose()
    await bot2.client.aclose()


async def test_typing_confirm_in_telegram_confirms_the_latest_pending_item():
    store, fake, clock = store_with_profile(), FakeTelegram(), {"now": NOW}
    bot, _, _ = await risky_bot(store, fake, clock)
    await bot.handle_update(msg("confirm"))
    await bot.drain_agent()
    assert (await store.get_rules("naukri")).auto_apply_enabled and "Portal rules updated" in last_reply(fake)
    await bot.client.aclose()


async def test_memory_window_is_twelve_turns_and_forget_clears_it():
    store = store_with_profile()
    fake = FakeTelegram()
    router = ScriptedRouter([final(f"reply {i}") for i in range(10)])
    bot = make_bot(store, fake, agent=agent(store, router))
    for i in range(9):
        await bot.handle_update(msg(f"note number {i}", message_id=i + 1))
        await bot.drain_agent()
    assert len(store.agent_turns) == 18 and all(t.chat_key == KEY for t in store.agent_turns)
    last_prompt = router.prompts[-1][2]
    assert "note number 7" in last_prompt and "note number 1" not in last_prompt  # last 12 turns only
    assert len(await store.recent_turns(KEY, 12)) == 12
    await bot.handle_update(msg("/forget"))
    assert "Forgot 18" in last_reply(fake) and await store.recent_turns(KEY) == []
    await bot.handle_update(msg("fresh start"))
    await bot.drain_agent()
    assert '"history":[]' in router.prompts[-1][2]
    await bot.client.aclose()


async def test_messages_are_never_dropped_when_the_agent_is_busy():
    gate = asyncio.Event()

    class SlowAgent:
        async def run_chat(self, text, *, chat_key, source):
            await gate.wait()
            return {"reply_html": f"done {text}", "confirmation": None, "hitl_resolutions": []}

    store = store_with_profile()
    fake = FakeTelegram()
    bot = make_bot(store, fake, agent=SlowAgent())
    for i in range(4):
        await bot.handle_update(msg(f"question {i}", message_id=i + 1))
    await asyncio.sleep(0.01)
    assert sum("still working" in p["text"] for p in fake.sent()) == 1
    gate.set()
    await bot.drain_agent()
    assert sorted(p["text"] for p in fake.sent() if p["text"].startswith("🤖")) == [
        "🤖 done question 0", "🤖 done question 1", "🤖 done question 2"]
    await bot.client.aclose()
