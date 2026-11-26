"""TelegramBot <-> LLM agent bridge: bounded background agent tasks, replies with Confirm/Cancel
buttons for risky writes (callback data `agc:<token>` / `agx:<token>`) and HITL card updates.

The agent never talks to Telegram: it returns HTML text (+ an optional confirmation token) and
this mixin delivers it. At most MAX_AGENT_TASKS run at once; polling is never blocked and a
message is never dropped silently (a busy notice is sent instead).
"""

from __future__ import annotations

import asyncio
import contextlib
import html
from collections.abc import Coroutine
from typing import Any

from backend.app.browser_v2.store import agent_chat_key
from backend.app.telegram_v2.base import MAX_AGENT_TASKS, TelegramBotBase, logger
from backend.app.telegram_v2.client import redact

BUSY = "⏳ The control agent is still working on your earlier messages; try again in a moment."


def confirmation_markup(token: str) -> dict[str, Any]:
    return {"inline_keyboard": [[{"text": "✅ Confirm", "callback_data": f"agc:{token}"},
                                 {"text": "✖️ Cancel", "callback_data": f"agx:{token}"}]]}


class AgentBridgeMixin(TelegramBotBase):
    @property
    def agent(self) -> Any:
        if self._agent is None:
            from backend.app.agent_v2.control_graph import ControlAgent

            self._agent = ControlAgent(self.store, ai=self.ai, mail_events=self.mail_events,
                                       event_bus=self.event_bus, clock=self.clock, wake=self.agent_wake,
                                       profile_sync=self.agent_profile_sync)
        return self._agent

    @property
    def agent_chat_key(self) -> str:
        """sha256-derived conversation key; the raw chat id is never stored."""
        return agent_chat_key("telegram", self.chat_id)

    def _spawn(self, coro: Coroutine[Any, Any, None], message_id: int | None,
               name: str = "telegram-agent") -> asyncio.Task[None] | None:
        if len(self._agent_tasks) >= MAX_AGENT_TASKS:
            coro.close()
            busy = asyncio.create_task(self._safe_reply(BUSY, message_id), name="telegram-agent-busy")
            self._agent_tasks.add(busy)
            busy.add_done_callback(self._agent_tasks.discard)
            return None
        task = asyncio.create_task(coro, name=name)
        self._agent_tasks.add(task)
        task.add_done_callback(self._agent_tasks.discard)
        return task

    def dispatch_agent(self, text: str, message_id: int | None, *,
                       fallback: str | None = None) -> asyncio.Task[None] | None:
        return self._spawn(self._agent_reply(text, message_id, fallback), message_id)

    async def _agent_reply(self, text: str, message_id: int | None, fallback: str | None) -> None:
        try:
            if not text.strip():
                await self.reply("Usage: <code>/ask &lt;text&gt;</code>", message_id)
                return
            agent = self.agent
            run_chat = getattr(agent, "run_chat", None)
            if run_chat is None:  # a plain Phase 6A agent (tests / custom injection)
                result = await agent.run(text)
                if fallback is not None and result.get("verdict") == "help":
                    await self.reply(fallback, message_id)
                    return
                await self.reply("🤖 " + html.escape(str(result.get("reply") or ""), quote=False), message_id)
                return
            result = await run_chat(text, chat_key=self.agent_chat_key, source="telegram")
            await self._deliver_agent(result, message_id)
        except Exception as exc:  # noqa: BLE001 - the agent must never break polling
            logger.warning("telegram_v2 agent failed: %s", type(exc).__name__)
            with contextlib.suppress(Exception):
                await self.reply("⚠️ The control agent hit an error; nothing was changed.", message_id)

    async def _deliver_agent(self, result: dict[str, Any], message_id: int | None) -> None:
        for resolution in result.get("hitl_resolutions") or []:
            with contextlib.suppress(Exception):
                await self._after_resolution(resolution)  # strip the resolved card's buttons
        text = "🤖 " + str(result.get("reply_html") or html.escape(str(result.get("reply") or ""), quote=False))
        confirmation = result.get("confirmation") or {}
        markup = confirmation_markup(str(confirmation["token"])) if confirmation.get("token") else None
        assert self.client is not None
        await self.client.send_message(self.chat_id, text, reply_to=message_id, reply_markup=markup)

    async def drain_agent(self) -> None:
        while self._agent_tasks:
            await asyncio.gather(*list(self._agent_tasks), return_exceptions=True)

    # --- confirmation buttons -------------------------------------------------------------------
    async def agent_confirmation(self, action: str, token: str, message_id: int | None) -> str:
        """`agc` confirms (runs in the background), `agx` cancels. Both are audited by the runner."""
        if self.client is not None and message_id is not None:
            with contextlib.suppress(Exception):
                await self.client.call("editMessageReplyMarkup", {"chat_id": self.chat_id, "message_id": message_id,
                                                                  "reply_markup": {"inline_keyboard": []}})
        agent = self.agent
        method = getattr(agent, "confirm_pending" if action == "agc" else "cancel_pending", None)
        if method is None:
            return "This agent has no pending actions."
        if action == "agx":
            result = await method(token or None, chat_key=self.agent_chat_key, source="telegram")
            await self._deliver_agent(result, message_id)
            return "Cancelled."

        async def run() -> None:
            try:
                await self._deliver_agent(await method(token or None, chat_key=self.agent_chat_key,
                                                       source="telegram"), message_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("telegram_v2 confirmation failed: %s", redact(type(exc).__name__))
                with contextlib.suppress(Exception):
                    await self.reply("⚠️ The confirmed action hit an error; see the audit log.", message_id)

        return "Working…" if self._spawn(run(), message_id, "telegram-agent-confirm") else "Busy; try again."
