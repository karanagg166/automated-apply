"""TelegramBot lifecycle: run/stop, the dispatch loop, polling state and 409 diagnosis."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from backend.app.telegram_v2.base import LEGACY_AGENT_LABEL, TelegramBotBase, logger
from backend.app.telegram_v2.client import redact


class PollingMixin(TelegramBotBase):
    # --- lifecycle -----------------------------------------------------------------
    async def run(self, stop_event: asyncio.Event) -> None:
        """Poll + dispatch until stop_event; never raises into the worker loop."""
        if not self.config.configured or self.client is None:
            with contextlib.suppress(Exception):
                await self._set_state("unconfigured", last_error=self.config.problem)
            logger.info("telegram_v2 unconfigured (%s); worker continues without Telegram", self.config.problem)
            return
        from backend.app.browser_v2.worker.instance_lock import (
            WorkerAlreadyRunning,
            instance_lock,
        )

        try:  # one getUpdates poller per host: fail fast instead of a 409 loop with ourselves
            with instance_lock("telegram-poller"):
                await self._run_locked(stop_event)
        except WorkerAlreadyRunning:
            logger.error("telegram_v2: another poller on this host holds the lock; not polling (run only one "
                         "worker / `cli telegram`)")
            with contextlib.suppress(Exception):
                await self._set_state("conflict", last_error="another local poller holds telegram-poller.lock")
            if self.owns_client:
                await self.client.aclose()

    async def _prepare_polling(self) -> None:
        """Long polling: drop a stale webhook (409 otherwise) and publish the command menu."""
        assert self.client is not None
        try:
            webhook = await self.client.get_webhook_info()
            if isinstance(webhook, dict) and webhook.get("url"):
                await self.client.delete_webhook()
                logger.warning("telegram_v2 deleted a stale webhook (long-polling mode)")
        except Exception as exc:  # noqa: BLE001 - diagnosis on 409 still covers it
            logger.info("telegram_v2 webhook check failed: %s", type(exc).__name__)
        register = getattr(self, "register_commands", None)
        if register is not None:
            await register()

    async def _run_locked(self, stop_event: asyncio.Event) -> None:
        assert self.client is not None
        try:  # a DB hiccup here must not kill Telegram for the worker's lifetime
            await self._set_state("starting", last_error=None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("telegram_v2 state write failed at start: %s", type(exc).__name__)
        await self._prepare_polling()
        tasks = [asyncio.create_task(self._poll_loop(stop_event), name="telegram-poll"),
                 asyncio.create_task(self._dispatch_loop(stop_event), name="telegram-dispatch")]
        stopper = asyncio.create_task(stop_event.wait())
        try:
            await asyncio.wait([*tasks, stopper], return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (*tasks, stopper, *self._agent_tasks):
                task.cancel()
            await asyncio.gather(*tasks, stopper, *self._agent_tasks, return_exceptions=True)
            with contextlib.suppress(Exception):
                await self._set_state("stopped")
            if self.owns_client:
                await self.client.aclose()

    async def _wait(self, stop_event: asyncio.Event, seconds: float) -> None:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop_event.wait(), timeout=max(0.0, seconds))

    async def _dispatch_loop(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.dispatch_once()
            except Exception as exc:  # noqa: BLE001 - keep dispatching on the next tick
                logger.warning("telegram_v2 dispatch failed: %s", redact(type(exc).__name__))
            await self._wait(stop_event, self.dispatch_interval)

    async def _set_state(self, polling_state: str, **changes: Any) -> None:
        self._state = polling_state
        await self.store.update_telegram_state(polling_state=polling_state, **changes)

    async def diagnose_conflict(self) -> str:
        """Why getUpdates returned 409: legacy launchd agent, a webhook, or another process."""
        parts: list[str] = []
        try:
            loaded = await self.legacy_probe()
        except Exception:  # noqa: BLE001
            loaded = None
        if loaded:
            parts.append(f"legacy {LEGACY_AGENT_LABEL} is still loaded (launchctl) and polls this bot token; "
                         f"unload it (cutover_v2 apply) to free the token")
        try:
            webhook = await self.client.get_webhook_info() if self.client is not None else None
        except Exception:  # noqa: BLE001
            webhook = None
        if isinstance(webhook, dict) and webhook.get("url"):
            parts.append("a webhook is set for this bot token (getUpdates is refused while it exists)")
        if not parts:
            parts.append("another process is polling this bot token" + (
                f" ({LEGACY_AGENT_LABEL} is not loaded)" if loaded is False else ""))
        return "409 conflict: " + "; ".join(parts)
