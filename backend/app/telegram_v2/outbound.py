"""TelegramBot outbound: HITL dispatch, test ping and message edits after resolution."""

from __future__ import annotations

import contextlib
from typing import Any

from backend.app.browser_v2.hitl import PortalResume, Resolution
from backend.app.browser_v2.store import HitlRecord
from backend.app.telegram_v2.base import TelegramBotBase, logger
from backend.app.telegram_v2.client import (
    TelegramBadRequest,
    TelegramError,
    TelegramRateLimited,
    is_not_modified,
)
from backend.app.telegram_v2.formatting import (
    OUTCOME_ICON,
    render_hitl,
    render_resolved,
)

URGENT_KINDS = frozenset({"OTP", "CAPTCHA"})  # break quiet hours: they expire in minutes


class OutboundMixin(TelegramBotBase):
    # --- outbound -------------------------------------------------------------------
    async def dispatch_once(self, limit: int = 25) -> int:
        """Send undelivered OPEN requests (P0 cards); persist telegram_msg_id right after each send.

        Quiet hours hold QUESTION/ERROR/AUTH cards until morning (OTP/CAPTCHA are time-critical and
        always go out); an AUTH card for a portal alerted < 6 h ago waits for the cooldown. A card
        Telegram rejects (400) no longer blocks the newer ones. Then cards of requests resolved
        anywhere else (dashboard, MCP, expiry) are edited in place.
        """
        assert self.client is not None
        sent = 0
        now = self.clock()
        config = self.notify_config
        quiet = bool(config is not None and config.in_quiet(now) and not config.quiet_hitl_override)
        for hitl in await self.store.undelivered_hitl(limit):
            if quiet and hitl.kind not in URGENT_KINDS:
                continue
            if hitl.kind == "AUTH" and await self._auth_recently_alerted(hitl.platform, now):
                continue
            text, markup = render_hitl(hitl)
            try:
                message = await self.client.send_message(self.chat_id, text, reply_markup=markup)
            except TelegramRateLimited as exc:  # the client already waited + retried
                logger.info("telegram_v2 dispatch rate limited; retry in %ss", exc.retry_after)
                break
            except TelegramBadRequest as exc:
                logger.warning("telegram_v2 dispatch of %s rejected: %s", hitl.ref, exc.code)
                continue
            except TelegramError as exc:
                logger.warning("telegram_v2 dispatch of %s failed: %s", hitl.ref, exc.code)
                break
            message_id = (message or {}).get("message_id")
            if isinstance(message_id, int):
                await self.store.mark_hitl_delivered(hitl.id, message_id)
                sent += 1
                if hitl.kind == "AUTH" and self.notifier is not None:
                    await self.notifier.mark_sent(f"auth:{hitl.platform}", "portal.auth_required", 0, message_id)
        await self.sync_closed_cards()
        return sent

    async def _auth_recently_alerted(self, platform: str, now: Any) -> bool:
        if self.notifier is None:
            return False
        return await self.notifier.recently_sent(f"auth:{platform}", self.notifier.config.auth_cooldown, now)

    async def sync_closed_cards(self, limit: int = 10) -> int:
        """Edit (and strip the buttons of) cards whose request was resolved outside Telegram."""
        try:
            rows = await self.store.unsynced_closed_hitl(limit)
        except Exception:  # noqa: BLE001 - followup 007 not applied yet: lazy edit on tap still works
            return 0
        for hitl in rows:
            via = f" via {hitl.resolved_via}" if hitl.resolved_via and hitl.resolved_via != "telegram" else ""
            label = {"ANSWERED": "Resolved" + via, "CANCELLED": "Skipped" + via,
                     "EXPIRED": "Expired"}.get(hitl.status, hitl.status.title())
            if hitl.status == "ANSWERED" and hitl.kind == "QUESTION" and hitl.answer_text:
                label = f"Answered{via}: {hitl.answer_text}"
            icon = {"CANCELLED": OUTCOME_ICON["skipped"], "EXPIRED": "⌛"}.get(hitl.status, "✅")
            await self._edit(hitl, label, icon=icon)
            with contextlib.suppress(Exception):
                await self.store.mark_hitl_card_closed(hitl.id)
        return len(rows)

    async def send_test_ping(self) -> dict[str, Any]:
        assert self.client is not None
        message = await self.client.send_message(
            self.chat_id, "✅ automated-apply v2: Telegram HITL bot can reach you. Send /help for commands.")
        return {"sent": True, "message_id": (message or {}).get("message_id")}

    # --- message edits after resolution -----------------------------------------------
    async def _after_resolution(self, result: Resolution) -> None:
        if result.ok and result.hitl is not None and self.event_bus is not None:
            with contextlib.suppress(Exception):
                await self.event_bus.publish("hitl.resolved", {"ref": result.hitl.ref, "kind": result.hitl.kind,
                                                               "platform": result.hitl.platform,
                                                               "outcome": result.code})
        if result.ok and result.hitl is not None:
            if result.code == "answered":
                label = f"Answered: {result.answer}" if result.hitl.kind == "QUESTION" else "Answered"
                if result.cached:
                    label += " (saved to cache)"
            else:
                label = {"skipped": "Skipped", "retried": "Retrying"}.get(result.code, result.code)
            await self._edit(result.hitl, label, icon=OUTCOME_ICON.get(result.code, "✅"))

    async def _close_messages(self, outcome: PortalResume) -> None:
        for hitl in outcome.resolved:
            await self._edit(hitl, "Portal resumed", icon=OUTCOME_ICON["resumed"])

    async def _edit(self, hitl: HitlRecord, outcome: str, *, icon: str = "✅") -> None:
        if self.client is None or hitl.telegram_msg_id is None:
            return
        try:
            await self.client.edit_message_text(self.chat_id, hitl.telegram_msg_id,
                                                render_resolved(hitl, outcome, icon=icon))
            with contextlib.suppress(Exception):  # followup 007: never re-edited by sync_closed_cards
                await self.store.mark_hitl_card_closed(hitl.id)
        except TelegramBadRequest as exc:
            if not is_not_modified(exc):  # "not modified" = already edited by a double tap
                logger.info("telegram_v2 edit of %s rejected: %s", hitl.ref, exc.code)
        except TelegramError as exc:
            logger.info("telegram_v2 edit of %s failed: %s", hitl.ref, exc.code)


def _html(text: str) -> str:
    from html import escape

    return escape(text)


def _outcome(result: Resolution) -> str:
    return ("✅ " if result.ok else "⚠️ ") + _html(result.message)
