"""Fresh private /start challenge discovery; never guesses or executes commands."""
import asyncio
import math
import time

from backend.app.local_agent.telegram import TelegramError


def private_start_pair(message, bot_username, challenge):
    if not isinstance(message, dict):
        return None
    sender, chat = message.get("from"), message.get("chat")
    if not isinstance(sender, dict) or not isinstance(chat, dict):
        return None
    user_id, chat_id = sender.get("id"), chat.get("id")
    if (chat.get("type") != "private" or type(user_id) is not int or user_id <= 0
            or type(chat_id) is not int or chat_id <= 0 or sender.get("is_bot")
            or message.get("forward_origin") or message.get("forward_date") or message.get("sender_chat")):
        return None
    text = message.get("text")
    if not isinstance(text, str) or len(text) > 256:
        return None
    parts = text.split()
    if len(parts) != 2 or parts[1] != challenge:
        return None
    command, _, mention = parts[0].partition("@")
    if command != "/start" or mention and mention.casefold() != bot_username.casefold():
        return None
    return user_id, chat_id


async def discover_owner(api, bot_username, challenge, *, timeout_seconds=120,
                         on_progress=None, clock=time.monotonic, sleep=asyncio.sleep):
    deadline = clock() + timeout_seconds
    offset, seen, private_seen, failures = None, 0, 0, 0
    for _ in range(300):
        remaining = deadline - clock()
        if remaining <= 0:
            break
        payload = {"timeout": min(20, max(1, math.ceil(remaining))), "limit": 100,
                   "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        try:
            # Total setup time is bounded even if a transport stalls.
            async with asyncio.timeout(remaining):
                updates = await api.call("getUpdates", payload)
        except TimeoutError:
            break
        except TelegramError as exc:
            if exc.code not in {"telegram_network_or_response_error", "telegram_rate_limited"}:
                raise
            failures += 1
            if failures > 3:
                raise
            delay = max(exc.retry_after, min(5, 2 ** failures))
            if delay >= deadline - clock():
                raise
            if on_progress:
                on_progress({"state": "retrying", "error_code": exc.code})
            await sleep(delay)
            continue
        failures = 0
        if not isinstance(updates, list) or len(updates) > 100:
            raise TelegramError("telegram_updates_response_invalid")
        for update in updates:
            if not isinstance(update, dict) or type(update.get("update_id")) is not int or update["update_id"] < 0:
                raise TelegramError("telegram_updates_response_invalid")
            # Telegram confirms only the updates actually observed on the next
            # positive-offset poll. No negative offsets or drop_pending_updates.
            if offset is not None and update["update_id"] < offset:
                continue
            offset = update["update_id"] + 1
            seen += 1
            message = update.get("message", {})
            if isinstance(message, dict) and isinstance(message.get("chat"), dict) and message["chat"].get("type") == "private":
                private_seen += 1
            pair = private_start_pair(message, bot_username, challenge)
            if pair:
                return pair
        if on_progress:
            on_progress({"state": "waiting", "updates_seen": seen, "private_messages_seen": private_seen})
        if not updates:
            await sleep(min(.25, max(0, deadline - clock())))
    raise TelegramError("telegram_private_start_not_observed_before_deadline")
