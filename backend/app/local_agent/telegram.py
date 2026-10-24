"""Official Bot API long polling. A separate worker; no webhook changes or shell tools."""
import asyncio
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5

import httpx
from sqlalchemy import select

from backend.app.local_agent.contracts import Actor, Command
from backend.app.local_agent.models import TelegramDelivery, TelegramState
from backend.app.local_agent.service import dispatch

HELP = "/start /help /ping /status /connections /jobs /apply <https-url> — previews only. No submissions, email sends or paid calls."


@asynccontextmanager
async def worker_lock(settings):
    """Keep the process lease outside the session pool, including one-slot pools."""
    import asyncpg

    from backend.app.db.safety import database_connect_args, database_target
    target = database_target(settings)
    if target.drivername != "postgresql+asyncpg":
        raise TelegramError("telegram_postgresql_required")
    connection = await asyncpg.connect(settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1),
        **database_connect_args(settings))
    try:
        if not await connection.fetchval("SELECT pg_try_advisory_lock(407001, 1)"):
            raise TelegramError("telegram_worker_already_running")
        yield
    finally:
        await connection.close()


class TelegramError(Exception):
    def __init__(self, code, retry_after=0):
        super().__init__(code)
        self.code, self.retry_after = code, retry_after


class TokenLogFilter(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot[REDACTED]", record.getMessage())
        record.args = ()
        return True


def install_redaction():
    for name in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection"):
        logger = logging.getLogger(name)
        logger.addFilter(TokenLogFilter())
        logger.setLevel(logging.WARNING)


def parse_command(text, bot_username=None):
    if not isinstance(text, str) or len(text) > 2048:
        raise TelegramError("invalid_command")
    first, _, argument = text.strip().partition(" ")
    command, _, mention = first.partition("@")
    if mention and mention.lower() != (bot_username or "").lower():
        raise TelegramError("wrong_bot_mention")
    if command not in {"/start", "/help", "/ping", "/status", "/connections", "/jobs", "/apply"}:
        raise TelegramError("unsupported_command")
    if command != "/apply" and argument.strip():
        if command != "/start" or not re.fullmatch(r"aa_[0-9a-f]{24}", argument.strip()):
            raise TelegramError("unexpected_argument")
    return command, argument.strip()


def authorized(message, settings):
    return bool(settings.TELEGRAM_OWNER_USER_ID and settings.TELEGRAM_OWNER_CHAT_ID
        and message.get("chat", {}).get("type") == "private"
        and type(message.get("from", {}).get("id")) is int
        and type(message.get("chat", {}).get("id")) is int
        and message["from"]["id"] == settings.TELEGRAM_OWNER_USER_ID
        and message["chat"]["id"] == settings.TELEGRAM_OWNER_CHAT_ID
        and not message.get("from", {}).get("is_bot")
        and not message.get("forward_origin") and not message.get("sender_chat"))


class BotAPI:
    def __init__(self, settings, client=None):
        self.settings, self.client = settings, client
        install_redaction()

    async def call(self, method, payload=None):
        if method not in {"getMe", "getWebhookInfo", "getUpdates", "sendMessage"}:
            raise TelegramError("telegram_capability_denied")
        if not self.settings.TELEGRAM_BOT_TOKEN:
            raise TelegramError("telegram_not_configured")
        # The official API requires the token in its path. Never log request/response objects.
        url = "https://api.telegram.org/bot" + self.settings.TELEGRAM_BOT_TOKEN.get_secret_value() + "/" + method
        try:
            if self.client:
                response = await self.client.post(url, json=payload or {}, timeout=40)
            else:
                async with httpx.AsyncClient(timeout=40, follow_redirects=False, trust_env=False) as client:
                    response = await client.post(url, json=payload or {})
            if len(response.content) > 1024 * 1024:
                raise TelegramError("telegram_response_size")
            if response.status_code in {401, 404}:
                raise TelegramError("telegram_authentication_failed")
            if response.status_code == 409:
                try:
                    conflict = response.json()
                    webhook = isinstance(conflict, dict) and "webhook" in str(conflict.get("description", "")).lower()
                except ValueError:
                    webhook = False
                raise TelegramError("telegram_webhook_conflict_owner_approval_required" if webhook else "telegram_polling_conflict")
            if response.status_code == 429:
                body = response.json()
                raise TelegramError("telegram_rate_limited", min(300, max(1, int(body.get("parameters", {}).get("retry_after", 5)))))
            if response.status_code != 200:
                raise TelegramError("telegram_transport_error")
            body = response.json()
            if not isinstance(body, dict) or body.get("ok") is not True:
                raise TelegramError("telegram_api_error")
            return body["result"]
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            raise TelegramError("telegram_network_or_response_error") from None

    async def verify(self):
        me = await self.call("getMe")
        if not isinstance(me, dict) or not me.get("is_bot") or type(me.get("id")) is not int:
            raise TelegramError("telegram_identity_invalid")
        webhook = await self.call("getWebhookInfo")
        if not isinstance(webhook, dict):
            raise TelegramError("telegram_webhook_status_invalid")
        if webhook.get("url"):
            raise TelegramError("telegram_webhook_conflict_owner_approval_required")
        return me


async def reply_for(session, settings, message, update_id, bot_username):
    try:
        command, argument = parse_command(message.get("text"), bot_username)
        if command in {"/start", "/help"}:
            return HELP
        if command == "/ping":
            return "pong — your authorized private message reached the local worker."
        operation = {"/status": "health", "/connections": "connection_status", "/jobs": "get_discovery_status", "/apply": "preview_application_url"}[command]
        request = Command(command=operation, url=argument if command == "/apply" else None,
            request_id=uuid5(NAMESPACE_URL, f"telegram:{settings.TELEGRAM_OWNER_CHAT_ID}:{update_id}"))
        result = await dispatch(session, settings, Actor(channel="telegram", identity=str(settings.TELEGRAM_OWNER_USER_ID)), request)
        if not result.ok:
            return f"Preview denied: {result.error_code}"
        if command == "/apply":
            # Don't echo URL query parameters, personal answers, compensation or resume content.
            return f"URL preview saved ({result.data['platform']}). No application submitted. Reference: {result.correlation_id}"
        if command == "/jobs":
            return f"Discovery deployment enabled: {result.data['deployment_enabled']}; schedule enabled: {result.data['schedule_enabled']}. No discovery executed."
        rows = result.data["connections"]
        if command == "/status":
            rows = [row for row in rows if row["name"] in {"Supabase PostgreSQL", "Local FastAPI"}]
        return "\n".join(f"{row['name']}: {row['state']}" for row in rows)
    except Exception:
        return "Command rejected or service unavailable. Use /help; only HTTPS URL previews are supported."


async def process_update(session, settings, update, bot_username):
    update_id = update.get("update_id")
    if type(update_id) is not int or update_id < 0:
        raise TelegramError("invalid_update_id")
    state = await session.get(TelegramState, "primary", with_for_update=True)
    if state is None:
        raise TelegramError("worker_not_verified")
    if update_id < state.next_update_id:
        return False
    message = update.get("message", {})
    if authorized(message, settings):
        reply = await reply_for(session, settings, message, update_id, bot_username)
        session.add(TelegramDelivery(update_id=update_id, reply=reply, state="pending"))
    state.next_update_id = update_id + 1
    state.last_poll_at = datetime.now(timezone.utc)
    await session.flush()
    return authorized(message, settings)


async def run_worker(settings, session_factory, api=None, stop=None):
    if not settings.TELEGRAM_OWNER_USER_ID or not settings.TELEGRAM_OWNER_CHAT_ID:
        raise TelegramError("telegram_owner_binding_required")
    bot = api or BotAPI(settings)
    me = await bot.verify()
    stop = stop or asyncio.Event()
    async with session_factory() as session:
        state = await session.get(TelegramState, "primary")
        if state is None:
            state = TelegramState(key="primary", next_update_id=0)
            session.add(state)
        if state.bot_id and state.bot_id != str(me["id"]):
            raise TelegramError("telegram_bot_identity_changed")
        state.bot_id = str(me["id"])
        state.evidence_type = "live_poll" if api is None else "simulated_transport"
        await session.commit()
    failures = 0
    while not stop.is_set():
        try:
            async with session_factory() as session:
                state = await session.get(TelegramState, "primary")
                offset = state.next_update_id
            updates = await bot.call("getUpdates", {"offset": offset, "timeout": 25, "limit": 20, "allowed_updates": ["message"]})
            for update in updates:
                async with session_factory() as session:
                    await process_update(session, settings, update, me.get("username"))
                    await session.commit()
            async with session_factory() as session:
                state = await session.get(TelegramState, "primary")
                state.last_poll_at, state.last_error = datetime.now(timezone.utc), None
                await session.commit()
            # Mark attempted before network dispatch. Ambiguous interruption is never replayed.
            async with session_factory() as session:
                delivery = await session.scalar(select(TelegramDelivery).where(TelegramDelivery.state == "pending").order_by(TelegramDelivery.update_id).with_for_update().limit(1))
                if delivery:
                    delivery.state = "sending"
                    delivery_id, reply = delivery.update_id, delivery.reply
                    await session.commit()
                else:
                    delivery_id = None
            if delivery_id is not None:
                try:
                    await bot.call("sendMessage", {"chat_id": settings.TELEGRAM_OWNER_CHAT_ID, "text": reply[:3500], "link_preview_options": {"is_disabled": True}})
                except TelegramError as exc:
                    if exc.code == "telegram_rate_limited":
                        async with session_factory() as session:
                            delivery = await session.get(TelegramDelivery, delivery_id)
                            delivery.state = "pending"
                            await session.commit()
                    raise
                async with session_factory() as session:
                    delivery = await session.get(TelegramDelivery, delivery_id)
                    delivery.state = "sent"
                    await session.commit()
                await asyncio.sleep(1)
            failures = 0
        except TelegramError as exc:
            async with session_factory() as session:
                state = await session.get(TelegramState, "primary")
                state.last_error = exc.code
                await session.commit()
            if exc.code in {"telegram_authentication_failed", "telegram_polling_conflict", "telegram_webhook_conflict_owner_approval_required"}:
                raise
            failures += 1
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(exc.retry_after, min(60, 2 ** min(failures, 6))))
            except TimeoutError:
                pass
