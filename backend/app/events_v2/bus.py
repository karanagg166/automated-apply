"""Async lifecycle EventBus with three FREE backends (EVENT_BUS_BACKEND).

- `postgres` (default): in-process asyncio dispatch (zero extra RAM / connections) plus an
  optional `pg_notify('automated_apply_events', ...)` wake-up over the worker's EXISTING
  single asyncpg connection (never a new Supabase connection).
- `cloudamqp`: free CloudAMQP RabbitMQ via its HTTPS management API
  (CLOUDAMQP_URL = the instance's amqps URL -> POST /api/exchanges/<vhost>/amq.default/publish
  and /api/queues/<vhost>/<queue>/get). Pure httpx, no AMQP SDK.
- `upstash_redis`: free Upstash Redis REST Streams (UPSTASH_REDIS_REST_URL +
  UPSTASH_REDIS_REST_TOKEN): XADD on publish, XRANGE for remote reads. Pure httpx.

Remote backends always dispatch locally too, and fall back to local-only (never raise)
when unconfigured or offline. Payloads are small JSON with ids/labels only: no secrets,
cookies, OTPs or email bodies ever go on the bus.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import quote, unquote, urlsplit

import httpx

logger = logging.getLogger(__name__)

TOPICS = ("job.applied", "job.quota_hit", "hitl.opened", "hitl.resolved", "mail.recruiter_reply",
          "portal.auth_required", "agent.action")
NOTIFY_CHANNEL = "automated_apply_events"
STREAM = "automated-apply:events"
QUEUE = "automated-apply.events"
MAX_PAYLOAD = 4_000
SENSITIVE_KEYS = re.compile(r"password|token|cookie|secret|otp|code|body|authorization", re.IGNORECASE)
Handler = Callable[[str, dict[str, Any]], Awaitable[None]]


def clean_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Drop sensitive keys and bound size (the bus may leave the Mac on remote backends)."""
    safe = {k: v for k, v in payload.items() if not SENSITIVE_KEYS.search(str(k))}
    text = json.dumps(safe, default=str)
    if len(text) > MAX_PAYLOAD:
        safe = {k: v for k, v in safe.items() if isinstance(v, (int, float, bool)) or (
            isinstance(v, str) and len(v) < 200)}
    return json.loads(json.dumps(safe, default=str))


class EventBus(Protocol):
    backend: str

    async def publish(self, topic: str, payload: Mapping[str, Any]) -> None: ...

    def subscribe(self, topic: str, handler: Handler) -> None: ...

    async def status(self) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class InProcessBus:
    """Local asyncio dispatch; handlers run as tasks so a slow subscriber never blocks the worker."""

    backend = "in_process"

    def __init__(self, *, history: int = 100) -> None:
        self.handlers: dict[str, list[Handler]] = defaultdict(list)
        self.recent: deque[dict[str, Any]] = deque(maxlen=history)
        self.published = 0
        self.errors = 0
        self._tasks: set[asyncio.Task[None]] = set()

    def subscribe(self, topic: str, handler: Handler) -> None:
        if topic != "*" and topic not in TOPICS:
            raise ValueError(f"unknown_topic:{topic}")
        self.handlers[topic].append(handler)

    async def dispatch(self, topic: str, payload: dict[str, Any]) -> None:
        for handler in [*self.handlers.get(topic, []), *self.handlers.get("*", [])]:
            task = asyncio.create_task(self._run(handler, topic, payload))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run(self, handler: Handler, topic: str, payload: dict[str, Any]) -> None:
        try:
            await handler(topic, payload)
        except Exception as exc:  # noqa: BLE001 - a broken subscriber never affects the worker
            self.errors += 1
            logger.warning("event handler for %s failed: %s", topic, type(exc).__name__)

    async def publish(self, topic: str, payload: Mapping[str, Any]) -> None:
        if topic not in TOPICS:
            raise ValueError(f"unknown_topic:{topic}")
        cleaned = clean_payload(payload)
        event: dict[str, Any] = {"topic": topic, "at": datetime.now(UTC).isoformat(), "payload": cleaned}
        self.recent.append(event)
        self.published += 1
        await self.dispatch(topic, cleaned)

    async def drain(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def status(self) -> dict[str, Any]:
        return {"backend": self.backend, "healthy": True, "published": self.published, "handler_errors": self.errors,
                "subscribers": {k: len(v) for k, v in self.handlers.items()}, "remote": None}

    async def close(self) -> None:
        await self.drain()


class PostgresBus(InProcessBus):
    backend = "postgres"

    def __init__(self, connection: Any = None, *, notify: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.connection = connection
        self.notify = notify and connection is not None
        self.notify_errors = 0

    async def publish(self, topic: str, payload: Mapping[str, Any]) -> None:
        await super().publish(topic, payload)
        if self.notify:
            try:
                await self.connection.execute("SELECT pg_notify($1, $2)", NOTIFY_CHANNEL,
                                              json.dumps({"topic": topic})[:200])
            except Exception as exc:  # noqa: BLE001 - wake-ups are optional
                self.notify_errors += 1
                logger.info("pg_notify failed: %s", type(exc).__name__)

    async def status(self) -> dict[str, Any]:
        return await super().status() | {"remote": {"pg_notify": self.notify, "channel": NOTIFY_CHANNEL,
                                                    "errors": self.notify_errors}}


class _RemoteBus(InProcessBus):
    """Local dispatch always; remote publish best-effort with a short circuit breaker."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 5.0,
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.transport = transport
        self.timeout = timeout
        self.remote_ok: bool | None = None
        self.remote_errors = 0
        self.last_error: str | None = None
        self._client: httpx.AsyncClient | None = None

    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(transport=self.transport, timeout=self.timeout, follow_redirects=False,
                                             trust_env=False)
        return self._client

    async def publish(self, topic: str, payload: Mapping[str, Any]) -> None:
        await super().publish(topic, payload)
        if self.remote_errors >= 5:  # breaker: remote is down, stay local-only quietly
            return
        try:
            await self.remote_publish(topic, self.recent[-1])
            self.remote_ok, self.remote_errors = True, 0
        except Exception as exc:  # noqa: BLE001 - graceful fallback to local dispatch
            self.remote_ok, self.remote_errors = False, self.remote_errors + 1
            self.last_error = type(exc).__name__
            logger.info("%s publish failed (%s); local dispatch only", self.backend, self.last_error)

    async def remote_publish(self, topic: str, event: dict[str, Any]) -> None:
        raise NotImplementedError

    async def status(self) -> dict[str, Any]:
        return await super().status() | {"healthy": self.remote_ok is not False,
                                         "remote": {"ok": self.remote_ok, "errors": self.remote_errors,
                                                    "last_error": self.last_error}}

    async def close(self) -> None:
        await super().close()
        if self._client is not None:
            await self._client.aclose()


class CloudAmqpBus(_RemoteBus):
    backend = "cloudamqp"

    def __init__(self, url: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        parts = urlsplit(url)
        if parts.scheme not in ("amqps", "https") or not parts.hostname:
            raise ValueError("cloudamqp_url_must_be_amqps")
        self.host = parts.hostname
        self.vhost = unquote(parts.path.lstrip("/")) or "/"
        self.auth = (unquote(parts.username or ""), unquote(parts.password or ""))

    @property
    def api(self) -> str:
        return f"https://{self.host}/api"

    async def remote_publish(self, topic: str, event: dict[str, Any]) -> None:
        vhost = quote(self.vhost, safe="")
        response = await self.client().post(
            f"{self.api}/exchanges/{vhost}/amq.default/publish", auth=self.auth,
            json={"properties": {"content_type": "application/json", "type": topic}, "routing_key": QUEUE,
                  "payload": json.dumps(event), "payload_encoding": "string"})
        response.raise_for_status()

    async def fetch_remote(self, count: int = 10) -> list[dict[str, Any]]:
        vhost = quote(self.vhost, safe="")
        response = await self.client().post(
            f"{self.api}/queues/{vhost}/{quote(QUEUE, safe='')}/get", auth=self.auth,
            json={"count": max(1, min(count, 50)), "ackmode": "ack_requeue_false", "encoding": "auto"})
        response.raise_for_status()
        return [json.loads(m["payload"]) for m in response.json() if isinstance(m, dict) and "payload" in m]


class UpstashRedisBus(_RemoteBus):
    backend = "upstash_redis"

    def __init__(self, url: str, token: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not url.startswith("https://"):
            raise ValueError("upstash_rest_url_must_be_https")
        self.url = url.rstrip("/")
        self.token = token

    def headers(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.token}"}

    async def remote_publish(self, topic: str, event: dict[str, Any]) -> None:
        command = ["XADD", STREAM, "MAXLEN", "~", "1000", "*", "topic", topic, "event", json.dumps(event)]
        response = await self.client().post(self.url, headers=self.headers(), json=command)
        response.raise_for_status()
        if isinstance(response.json(), dict) and response.json().get("error"):
            raise RuntimeError("upstash_error")

    async def fetch_remote(self, count: int = 10) -> list[dict[str, Any]]:
        response = await self.client().post(self.url, headers=self.headers(),
                                            json=["XREVRANGE", STREAM, "+", "-", "COUNT", str(max(1, min(count, 50)))])
        response.raise_for_status()
        output = []
        for entry in response.json().get("result") or []:
            fields = entry[1] if isinstance(entry, list) and len(entry) == 2 else []
            values = dict(zip(fields[::2], fields[1::2], strict=False))
            if "event" in values:
                output.append(json.loads(values["event"]))
        return output


def build_event_bus(env: Mapping[str, str] | None = None, *, connection: Any = None,
                    transport: httpx.AsyncBaseTransport | None = None) -> EventBus:
    """EVENT_BUS_BACKEND=postgres|cloudamqp|upstash_redis; unconfigured remote -> postgres."""
    from backend.app.browser_v2.env_loader import load_env

    values = env if env is not None else load_env()
    choice = (values.get("EVENT_BUS_BACKEND") or "postgres").strip().lower()
    try:
        if choice == "cloudamqp" and (values.get("CLOUDAMQP_URL") or "").strip():
            return CloudAmqpBus(values["CLOUDAMQP_URL"].strip(), transport=transport)
        if choice == "upstash_redis" and (values.get("UPSTASH_REDIS_REST_URL") or "").strip() \
                and (values.get("UPSTASH_REDIS_REST_TOKEN") or "").strip():
            return UpstashRedisBus(values["UPSTASH_REDIS_REST_URL"].strip(),
                                   values["UPSTASH_REDIS_REST_TOKEN"].strip(), transport=transport)
    except ValueError as exc:
        logger.warning("event bus %s misconfigured (%s); using postgres", choice, exc)
    notify = (values.get("EVENT_BUS_PG_NOTIFY") or "true").strip().lower() not in {"0", "false", "no", "off"}
    return PostgresBus(connection, notify=notify)


async def bus_status(bus: EventBus | None, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    from backend.app.browser_v2.env_loader import load_env

    values = env if env is not None else load_env()
    requested = (values.get("EVENT_BUS_BACKEND") or "postgres").strip().lower()
    status = await bus.status() if bus is not None else {"backend": "postgres", "healthy": True, "published": 0,
                                                          "handler_errors": 0, "subscribers": {}, "remote": None}
    return status | {"requested_backend": requested, "fell_back": requested != status["backend"],
                     "topics": list(TOPICS)}
