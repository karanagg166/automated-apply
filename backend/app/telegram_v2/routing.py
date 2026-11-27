"""TelegramBot inbound routing: authorization, update dispatch, replies and buttons.

Order (Phase 9C): (a) inline buttons (HITL answers, portal resume, agent Confirm/Cancel) ->
slash commands (/ask <text> goes to the agent) -> (b) swipe-reply to an open HITL card ->
direct resolution -> (c) bare digits while an OTP request is open -> direct -> everything else
-> the LLM agent in the background (it sees the open requests and can resolve them).
"""

from __future__ import annotations

from typing import Any

from backend.app.browser_v2.hitl import Resolution
from backend.app.browser_v2.store import HitlRecord
from backend.app.telegram_v2.agent_bridge import AgentBridgeMixin
from backend.app.telegram_v2.base import (
    OTP_CODE,
    PLAIN_TEXT_KINDS,
    logger,
)
from backend.app.telegram_v2.client import TelegramError, redact
from backend.app.telegram_v2.formatting import OUTCOME_ICON, render_disambiguation
from backend.app.telegram_v2.outbound import _outcome


class RoutingMixin(AgentBridgeMixin):
    def authorized(self, chat_id: Any, user_id: Any) -> bool:
        if chat_id is None or chat_id != self.config.owner_chat_id:
            return False
        return self.config.owner_user_id is None or user_id == self.config.owner_user_id

    async def handle_update(self, update: dict[str, Any]) -> None:
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            message = callback.get("message") or {}
            if not self.authorized((message.get("chat") or {}).get("id"), (callback.get("from") or {}).get("id")):
                logger.warning("telegram_v2 ignored callback from an unauthorized chat")
                return
            await self.handle_callback(callback)
            return
        message = update.get("message")
        if not isinstance(message, dict):
            return
        if not self.authorized((message.get("chat") or {}).get("id"), (message.get("from") or {}).get("id")):
            logger.warning("telegram_v2 ignored message from an unauthorized chat")
            return
        text = (message.get("text") or "").strip()
        message_id = message.get("message_id")
        if text.startswith("/"):
            head = text.split(maxsplit=1)[0].split("@")[0].lower()
            if head == "/ask":
                self.dispatch_agent(text[len(text.split(maxsplit=1)[0]):].strip(), message_id)
                return
            response = await self.handle_command(text)
            if isinstance(response, tuple):
                await self.reply(response[0], message_id, reply_markup=response[1])
            else:
                await self.reply(response, message_id)
            return
        reply_to = message.get("reply_to_message")
        if isinstance(reply_to, dict) and reply_to.get("message_id") is not None:
            hitl = await self.store.find_hitl_by_message(reply_to["message_id"])
            if hitl is not None:
                await self.reply(await self.handle_reply(hitl, text), message_id)
                return
        await self.route_plain(text, message_id)

    # --- Phase 9C: LLM-first free chat --------------------------------------------------------------
    async def answerable(self) -> list[HitlRecord]:
        """OPEN QUESTION/OTP requests (shown in Telegram or the dashboard inbox)."""
        rows, _ = await self.store.list_hitl("OPEN", limit=50)
        return [row for row in rows if row.kind in PLAIN_TEXT_KINDS]

    async def route_plain(self, text: str, message_id: int | None) -> None:
        """Bare digits while an OTP request is open resolve it directly (never sent to an LLM);
        everything else goes to the LLM agent, which sees the open requests and can resolve them."""
        if not text:
            await self.reply("Send text, a swipe-reply to a request, or /help.", message_id)
            return
        if OTP_CODE.fullmatch(text) and await self.resolve_otp(text, message_id):
            return
        self.dispatch_agent(text, message_id)

    async def resolve_otp(self, code: str, message_id: int | None) -> bool:
        rows = [row for row in await self.answerable() if row.kind == "OTP"]
        if not rows:
            return False
        if len(rows) > 1:
            await self.reply(render_disambiguation(rows), message_id)
            return True
        result = await self.resolver.answer(rows[0].id, code, cache_answer=False, via="telegram")
        await self._after_resolution(result)
        await self.reply(_outcome(result), message_id)
        return True

    async def reply(self, text: str, reply_to: int | None = None, *, reply_markup: dict[str, Any] | None = None) -> None:
        """HTML reply, chunked to <= 4000 chars, plain-text fallback on a parse error (client)."""
        assert self.client is not None
        await self.client.send_message(self.chat_id, text, reply_to=reply_to, reply_markup=reply_markup)

    async def _safe_reply(self, text: str, reply_to: int | None = None) -> None:
        try:
            await self.reply(text, reply_to)
        except Exception as exc:  # noqa: BLE001 - replies are best effort
            logger.info("telegram_v2 reply failed: %s", redact(type(exc).__name__))

    # --- callbacks ------------------------------------------------------------------
    async def handle_callback(self, callback: dict[str, Any]) -> None:
        """Idempotent: a double tap finds the request resolved and only re-strips the buttons.

        answerCallbackQuery is always sent (finally), even when resolution fails, so the
        owner's button never keeps spinning.
        """
        assert self.client is not None
        data = str(callback.get("data") or "")
        message = callback.get("message") or {}
        message_id = message.get("message_id")
        action, _, rest = data.partition(":")
        notice = "Done."
        try:
            if action == "resume":
                outcome = await self.resolver.resume_portal(rest, via="telegram")
                notice = outcome.message
                await self._close_messages(outcome)
            elif action in {"ans", "skip", "retry"}:
                notice = await self._resolve_button(action, rest, message_id)
            elif action in {"agc", "agx"}:
                notice = await self.agent_confirmation(action, rest, message_id)
            elif action == "q":
                verb, _, application_id = rest.partition(":")
                notice = await self.queue_button("skip" if verb == "skip" else "go", application_id)
            else:
                notice = "Unknown button."
        except Exception as exc:  # noqa: BLE001 - the toast still answers; nothing half-applied is hidden
            logger.warning("telegram_v2 callback %s failed: %s", action, redact(type(exc).__name__))
            notice = "⚠️ That action failed; nothing was changed. Try again or use /pending."
        finally:
            try:
                await self.client.answer_callback_query(str(callback.get("id") or ""), notice)
            except TelegramError as exc:
                logger.warning("telegram_v2 answerCallbackQuery failed: %s", exc.code)

    async def _resolve_button(self, action: str, rest: str, message_id: int | None) -> str:
        ref, _, index = rest.partition(":")
        hitl = await self.store.find_hitl_by_message(message_id) if message_id is not None else None
        if hitl is None or hitl.ref != ref:
            hitl, problem = await self.resolver.by_ref(ref)
            if problem is not None:
                hitl = None
        if hitl is None:
            # Resolved requests are not OPEN, so by_ref() misses them: say so, never error.
            return "That request is already resolved or no longer exists — nothing changed."
        if hitl.status != "OPEN":
            label = f"Already {hitl.status.lower()}" + (
                f": {hitl.answer_text}" if hitl.answer_text and hitl.kind == "QUESTION" else "")
            await self._edit(hitl, label, icon=OUTCOME_ICON["already"])
            return f"Already {hitl.status.lower()} — nothing changed."
        if action == "ans" and index.isdigit():
            result = await self.resolver.answer_option(hitl.id, int(index), via="telegram")
        elif action == "skip":
            result = await self.resolver.skip(hitl.id, via="telegram")
        elif action == "retry":
            result = await self.resolver.retry(hitl.id, via="telegram")
        else:
            result = Resolution(False, "invalid_option", "Unknown button.")
        await self._after_resolution(result)
        return result.message
