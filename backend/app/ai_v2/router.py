"""Free external LLM fallback router with quota tracking and circuit breakers.

`generate_json(task, ...)` walks the task's provider chain:
  unconfigured -> skip; circuit/cooldown open -> skip; local RPM/RPD/TPD cap -> skip;
  HTTP 429 -> cooldown (Retry-After or 60 s) and fail over;
  5xx / timeout / network / invalid JSON -> exponential cooldown (10 s, 20 s), and a
  300 s circuit after 3 consecutive failures; 401/403 -> 1 h circuit;
  first valid, schema-checked JSON wins.
Every prompt is HTML-stripped, truncated and PII-scrubbed here, before dispatch.
If nothing answers, `AllLLMProvidersExhaustedError` is raised and callers fall
back to deterministic-only / WAITING_FOR_USER.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Generic, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from backend.app.ai_v2.pii import scrub_pii
from backend.app.ai_v2.providers import (
    PROVIDER_REGISTRY,
    TASK_CHAINS,
    ProviderConfig,
    ProviderResponseError,
    ProviderSpec,
    build_request,
    extract_json_object,
    parse_response,
    resolve_provider,
    validate_registry,
)
from backend.app.ai_v2.usage import MemoryUsageStore, UsageStore

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

MAX_USER_PROMPT_CHARS = 8_000
MAX_SYSTEM_PROMPT_CHARS = 4_000
DEFAULT_TIMEOUT_SEC = 20.0
RATE_LIMIT_COOLDOWN_SEC = 60
MAX_RETRY_AFTER_SEC = 3_600
FAILURE_BACKOFF_BASE_SEC = 5
CIRCUIT_FAILURES = 3
CIRCUIT_OPEN_SEC = 300
AUTH_FAILURE_OPEN_SEC = 3_600
_HTML_TAG = re.compile(r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>|<[a-zA-Z/!][^>]*>", re.DOTALL | re.IGNORECASE)


class AllLLMProvidersExhaustedError(RuntimeError):
    def __init__(self, task: str, attempts: list[dict[str, Any]]) -> None:
        super().__init__(f"all_llm_providers_exhausted:{task}")
        self.task = task
        self.attempts = attempts


@dataclass(frozen=True)
class LLMResult(Generic[T]):
    value: T
    provider: str
    model: str
    latency_ms: float
    input_tokens: int
    output_tokens: int
    attempts: list[dict[str, Any]] = field(default_factory=list)


def sanitize_prompt(text: str, limit: int) -> str:
    """Never send raw HTML or unbounded dumps."""
    cleaned = _HTML_TAG.sub(" ", text or "")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned if len(cleaned) <= limit else cleaned[:limit].rstrip() + " …[truncated]"


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def load_env(env_file: str | os.PathLike[str] | None = None) -> dict[str, str]:
    """Private env file (if present) overlaid by the process environment."""
    from backend.app.browser_v2.config import env_file as resolve_env_file

    values: dict[str, str] = {}
    path = resolve_env_file(env_file)
    if path is not None:
        from dotenv import dotenv_values

        values.update({k: v for k, v in dotenv_values(path).items() if isinstance(v, str)})
    values.update(os.environ)
    return values


class LLMRouter:
    def __init__(self, *, env: Mapping[str, str] | None = None, usage: UsageStore | None = None,
                 registry: Mapping[str, ProviderSpec] | None = None,
                 chains: Mapping[str, tuple[str, ...]] | None = None,
                 transport: httpx.AsyncBaseTransport | None = None,
                 clock: Callable[[], datetime] | None = None,
                 timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> None:
        self.registry = dict(registry or PROVIDER_REGISTRY)
        validate_registry(self.registry)
        self.chains = dict(chains or TASK_CHAINS)
        self.env = dict(env if env is not None else load_env())
        self.usage = usage or MemoryUsageStore()
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(UTC))
        self.timeout_sec = timeout_sec
        self.failures: dict[str, int] = {}
        self._secrets: tuple[str, ...] = ()
        self.providers: dict[str, ProviderConfig] = {
            name: resolve_provider(spec, self.env) for name, spec in self.registry.items()}

    # --- configuration --------------------------------------------------------------
    def register_secrets(self, secrets: Iterable[str]) -> None:
        """Owner identifiers (phone, email, name, links) scrubbed from every prompt."""
        self._secrets = tuple(s for s in secrets if isinstance(s, str) and s.strip())

    def chain(self, task: str) -> tuple[str, ...]:
        if task not in self.chains:
            raise ValueError(f"unknown_llm_task:{task}")
        return tuple(name for name in self.chains[task] if name in self.providers)

    @property
    def any_configured(self) -> bool:
        return any(config.configured for config in self.providers.values())

    def configured_chain(self, task: str) -> list[str]:
        return [name for name in self.chain(task) if self.providers[name].configured]

    # --- status ---------------------------------------------------------------------
    async def status(self) -> list[dict[str, Any]]:
        now = self.clock()
        output = []
        for name, config in self.providers.items():
            spec = config.spec
            snapshot = await self.usage.snapshot(name, config.model, now)
            if not config.configured:
                state = "unconfigured"
            elif snapshot.circuit_open_until and snapshot.circuit_open_until > now:
                error = snapshot.last_error or ""
                state = "circuit_open" if error.startswith("circuit_open") or error.endswith("_auth") \
                    else "cooldown"
            elif self._cap_reason(spec, snapshot, 0):
                state = "cooldown"
            else:
                state = "healthy"
            output.append({
                "provider": name, "label": spec.label, "status": state, "model": config.model,
                "problem": config.problem, "api_style": spec.api_style,
                "requests_today": snapshot.day_requests, "requests_this_minute": snapshot.minute_requests,
                "tokens_today": snapshot.day_tokens, "rpm_limit": spec.rpm, "rpd_limit": spec.rpd,
                "tpd_limit": spec.tpd, "circuit_open_until": snapshot.circuit_open_until,
                "last_error": snapshot.last_error, "consecutive_failures": self.failures.get(name, 0),
                "key_envs": list(spec.key_envs) + list(spec.required_envs)})
        return output

    @staticmethod
    def _cap_reason(spec: ProviderSpec, snapshot: Any, planned_tokens: int) -> str | None:
        if snapshot.minute_requests >= spec.rpm:
            return "local_cap_rpm"
        if snapshot.day_requests >= spec.rpd:
            return "local_cap_rpd"
        if spec.tpd is not None and snapshot.day_tokens + planned_tokens > spec.tpd:
            return "local_cap_tpd"
        return None

    # --- generation -----------------------------------------------------------------
    async def generate_json(self, task: str, system_prompt: str, user_prompt: str,
                            response_model: type[T], *, extra_secrets: Iterable[str] = (),
                            max_output_tokens: int = 400) -> LLMResult[T]:
        secrets = (*self._secrets, *extra_secrets)
        system = scrub_pii(sanitize_prompt(system_prompt, MAX_SYSTEM_PROMPT_CHARS), secrets)
        user = scrub_pii(sanitize_prompt(user_prompt, MAX_USER_PROMPT_CHARS), secrets)
        planned = estimate_tokens(system + user) + max_output_tokens
        attempts: list[dict[str, Any]] = []
        async with httpx.AsyncClient(transport=self.transport, timeout=self.timeout_sec,
                                     follow_redirects=False) as client:
            for name in self.chain(task):
                config = self.providers[name]
                if not config.configured:
                    attempts.append({"provider": name, "outcome": "unconfigured"})
                    continue
                now = self.clock()
                snapshot = await self.usage.snapshot(name, config.model, now)
                if snapshot.circuit_open_until and snapshot.circuit_open_until > now:
                    attempts.append({"provider": name, "outcome": "circuit_open"})
                    continue
                cap = self._cap_reason(config.spec, snapshot, planned)
                if cap:
                    attempts.append({"provider": name, "outcome": cap})
                    continue
                result = await self._attempt(client, config, system, user, response_model, max_output_tokens,
                                             attempts)
                if result is not None:
                    value, latency, tokens_in, tokens_out = result
                    logger.info("llm_router task=%s provider=%s model=%s latency_ms=%.0f in=%d out=%d chain=%s",
                                task, name, config.model, latency, tokens_in, tokens_out,
                                ",".join(f"{a['provider']}:{a['outcome']}" for a in attempts))
                    return LLMResult(value, name, config.model, latency, tokens_in, tokens_out, attempts)
        logger.warning("llm_router task=%s exhausted chain=%s", task,
                       ",".join(f"{a['provider']}:{a['outcome']}" for a in attempts))
        raise AllLLMProvidersExhaustedError(task, attempts)

    async def _attempt(self, client: httpx.AsyncClient, config: ProviderConfig, system: str, user: str,
                       response_model: type[T], max_output_tokens: int, attempts: list[dict[str, Any]]
                       ) -> tuple[T, float, int, int] | None:
        name, model = config.name, config.model
        request = build_request(config, system, user, max_output_tokens=max_output_tokens)
        started = time.perf_counter()
        await self.usage.record(name, model, self.clock(), requests=1)
        try:
            response = await client.post(request.url, headers=request.headers, json=request.body)
        except httpx.TimeoutException:
            await self._failure(config, "timeout", attempts)
            return None
        except httpx.HTTPError as exc:
            await self._failure(config, "network_" + type(exc).__name__, attempts)
            return None
        latency = (time.perf_counter() - started) * 1000
        if response.status_code == 429:
            await self._rate_limited(config, response, attempts)
            return None
        if response.status_code in (401, 403):
            await self._open(config, AUTH_FAILURE_OPEN_SEC, f"http_{response.status_code}_auth", attempts)
            return None
        if response.status_code >= 400:
            await self._failure(config, f"http_{response.status_code}", attempts)
            return None
        try:
            wire = parse_response(config, response.json())
            value = response_model.model_validate(extract_json_object(wire.text))
        except (ValueError, ProviderResponseError, ValidationError) as exc:
            await self._failure(config, "invalid_json:" + type(exc).__name__, attempts)
            return None
        tokens_in = wire.input_tokens if wire.input_tokens is not None else estimate_tokens(system + user)
        tokens_out = wire.output_tokens if wire.output_tokens is not None else estimate_tokens(wire.text)
        await self.usage.record(name, model, self.clock(), input_tokens=tokens_in, output_tokens=tokens_out)
        if self.failures.pop(name, 0):
            await self.usage.set_circuit(name, model, self.clock(), None, None)
        attempts.append({"provider": name, "outcome": "ok", "latency_ms": round(latency)})
        return value, latency, tokens_in, tokens_out

    async def _open(self, config: ProviderConfig, seconds: float, error: str,
                    attempts: list[dict[str, Any]]) -> None:
        now = self.clock()
        await self.usage.set_circuit(config.name, config.model, now, now + timedelta(seconds=seconds), error)
        attempts.append({"provider": config.name, "outcome": error, "cooldown_sec": round(seconds)})

    async def _rate_limited(self, config: ProviderConfig, response: httpx.Response,
                            attempts: list[dict[str, Any]]) -> None:
        retry_after = response.headers.get("retry-after", "")
        try:
            seconds = min(max(float(retry_after), 1.0), MAX_RETRY_AFTER_SEC)
        except ValueError:
            seconds = RATE_LIMIT_COOLDOWN_SEC
        await self._open(config, seconds, "http_429", attempts)

    async def _failure(self, config: ProviderConfig, error: str, attempts: list[dict[str, Any]]) -> None:
        count = self.failures.get(config.name, 0) + 1
        self.failures[config.name] = count
        if count >= CIRCUIT_FAILURES:  # breaker: skip this provider for 5 minutes
            await self._open(config, CIRCUIT_OPEN_SEC, f"circuit_open:{error}", attempts)
        else:  # exponential backoff cooldown: 10 s, 20 s
            await self._open(config, FAILURE_BACKOFF_BASE_SEC * 2 ** count, error, attempts)
