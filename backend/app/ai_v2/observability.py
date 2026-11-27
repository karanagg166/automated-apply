"""LLM observability: every router call becomes one Langfuse trace (hosted, free tier).

One trace per `LLMRouter.generate_json` call (`llm.<task>`), one generation per provider
attempt (model, latency, tokens, failover outcome). Callers attach scores to the trace id
(accepted / confidence / judge verdict), which is what the Langfuse dashboards and evals read.

Contract:
  * Off unless LANGFUSE_PUBLIC_KEY + LANGFUSE_SECRET_KEY are set (and LANGFUSE_TRACING_ENABLED
    is not false). Off means `NullTracer`: zero imports, zero threads, zero network.
  * Tracing can never break the worker: every SDK call is wrapped and failures are logged once.
  * Only already PII-scrubbed prompts are sent (the router scrubs before dispatch), and a
    Langfuse `mask` re-scrubs every payload with the owner's registered identifiers.
  * A private OpenTelemetry TracerProvider is used, so spans from other libraries (FastMCP)
    are never exported to Langfuse and the global provider is left untouched.
  * Export is batched on the SDK's background thread; the asyncio loop is never blocked.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Iterable, Iterator, Mapping
from contextvars import ContextVar
from typing import Any

from backend.app.ai_v2.pii import scrub_pii

logger = logging.getLogger(__name__)

PUBLIC_KEY_ENV = "LANGFUSE_PUBLIC_KEY"
SECRET_KEY_ENV = "LANGFUSE_SECRET_KEY"
BASE_URL_ENVS = ("LANGFUSE_BASE_URL", "LANGFUSE_HOST")
ENABLED_ENV = "LANGFUSE_TRACING_ENABLED"
ENVIRONMENT_ENV = "LANGFUSE_TRACING_ENVIRONMENT"
DEFAULT_BASE_URL = "https://cloud.langfuse.com"
MAX_FIELD_CHARS = 6_000
_FALSE = {"0", "false", "no", "off"}
_TRACERS: dict[tuple[str, str], LangfuseTracer] = {}


_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar("llm_trace_context", default=None)
ATTEMPT_NAME = "generate"  # stable, verb-first, never a model or provider (those are attributes)


@contextlib.contextmanager
def trace_context(**attrs: Any) -> Iterator[None]:
    """Attach request context (metadata, tags, session_id, user_id) to LLM traces started inside.

    Example: `with trace_context(metadata={"portal": "naukri"}, tags=["feature:screening"])`.
    Metadata values are stringified and capped at 200 chars (Langfuse propagation limit)."""
    merged = dict(_CONTEXT.get() or {})
    for key, value in attrs.items():
        if key in ("metadata",) and isinstance(value, Mapping):
            merged["metadata"] = {**(merged.get("metadata") or {}), **value}
        elif key == "tags":
            merged["tags"] = [*(merged.get("tags") or []), *value]
        else:
            merged[key] = value
    token = _CONTEXT.set(merged)
    try:
        yield
    finally:
        _CONTEXT.reset(token)


def _propagation(task: str, ctx: Mapping[str, Any] | None) -> dict[str, Any]:
    ctx = ctx or {}
    meta = {str(k)[:60]: str(v)[:200] for k, v in (ctx.get("metadata") or {}).items() if v not in (None, "")}
    tags = list(dict.fromkeys([f"task:{task}", *(str(t)[:60] for t in ctx.get("tags") or [])]))
    out: dict[str, Any] = {"tags": tags, "trace_name": f"llm.{task}"}
    if meta:
        out["metadata"] = meta
    for key in ("session_id", "user_id"):
        if ctx.get(key):
            out[key] = str(ctx[key])[:200]
    return out


def _scope(attrs: Mapping[str, Any]) -> Any:
    """propagate_attributes(...) when the SDK has it, else a no-op context manager."""
    try:
        from langfuse import propagate_attributes
        return propagate_attributes(**attrs)
    except Exception:  # noqa: BLE001 - observability must never break an LLM call
        return contextlib.nullcontext()


def _review_input(user: str) -> Any:
    """Root input a human reviewer wants: the question (and options/job), not the whole profile."""
    try:
        data = json.loads(user)
    except ValueError:
        return _clip(user)
    if isinstance(data, dict) and "question" in data:
        return {k: data[k] for k in ("question", "options", "job") if data.get(k)}
    return _clip(user)


def _clip(text: str) -> str:
    return text if len(text) <= MAX_FIELD_CHARS else text[:MAX_FIELD_CHARS] + " …[truncated]"


def scrub_payload(data: Any, secrets: Iterable[str] = ()) -> Any:
    """Recursively PII-scrub every string in a JSON-like payload."""
    if isinstance(data, str):
        return scrub_pii(data, secrets)
    if isinstance(data, Mapping):
        return {key: scrub_payload(value, secrets) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [scrub_payload(value, secrets) for value in data]
    return data


class NullCall:
    """No-op call trace (tracing disabled)."""

    trace_id: str | None = None

    def attempt(self, provider: str, model: str, max_output_tokens: int) -> NullCall:
        return self

    def ok(self, text: str, input_tokens: int, output_tokens: int) -> None:
        return None

    def fail(self, outcome: str) -> None:
        return None

    def finish(self, outcome: str, attempts: list[dict[str, Any]], provider: str | None = None) -> None:
        return None


class NullTracer:
    enabled = False

    def register_secrets(self, secrets: Iterable[str]) -> None:
        return None

    def start_call(self, task: str, system: str, user: str) -> Any:
        return NullCall()

    def score(self, trace_id: str | None, name: str, value: float | bool | str, *,
              comment: str | None = None) -> None:
        return None

    def flush(self) -> None:
        return None


class _Attempt:
    def __init__(self, observation: Any, call: Any = None) -> None:
        self._observation = observation
        self._call = call

    def ok(self, text: str, input_tokens: int, output_tokens: int) -> None:
        if self._call is not None:
            self._call.reply = _clip(text)
        self._close(output=_clip(text), usage_details={"input": input_tokens, "output": output_tokens})

    def fail(self, outcome: str) -> None:
        self._close(level="ERROR" if not outcome.startswith("http_429") else "WARNING", status_message=outcome)

    def _close(self, **fields: Any) -> None:
        try:
            self._observation.update(**fields)
            self._observation.end()
        except Exception:  # observability must never break an LLM call
            logger.debug("langfuse_attempt_close_failed", exc_info=True)


class _Call:
    """One router call: a root span plus one generation per provider attempt."""

    def __init__(self, root: Any, system: str, user: str, attrs: Mapping[str, Any] | None = None) -> None:
        self._root = root
        self._attrs = dict(attrs or {})
        self.reply: str | None = None
        self._messages = [{"role": "system", "content": _clip(system)}, {"role": "user", "content": _clip(user)}]
        self.trace_id: str | None = getattr(root, "trace_id", None)
        self._done = False

    def attempt(self, provider: str, model: str, max_output_tokens: int) -> Any:
        try:
            with _scope(self._attrs):
                observation = self._root.start_observation(
                    name=ATTEMPT_NAME, as_type="generation", model=model, input=self._messages,
                    model_parameters={"max_output_tokens": max_output_tokens}, metadata={"provider": provider})
            return _Attempt(observation, self)
        except Exception:
            logger.debug("langfuse_attempt_start_failed", exc_info=True)
            return NullCall()

    def finish(self, outcome: str, attempts: list[dict[str, Any]], provider: str | None = None) -> None:
        if self._done:
            return
        self._done = True
        chain = [f"{a.get('provider')}:{a.get('outcome')}" for a in attempts]
        skipped = {"ok", "unconfigured", "excluded"}  # not a failover: never tried or succeeded
        try:
            self._root.update(
                output=self.reply if self.reply is not None else {"outcome": outcome, "provider": provider},
                metadata={"outcome": outcome, "provider": provider or "", "chain": ",".join(chain),
                          "failovers": sum(1 for a in attempts if a.get("outcome") not in skipped)},
                level="DEFAULT" if outcome == "ok" else "ERROR",
                status_message=None if outcome == "ok" else outcome)
            self._root.end()
        except Exception:
            logger.debug("langfuse_call_finish_failed", exc_info=True)


class LangfuseTracer:
    enabled = True

    def __init__(self, client: Any) -> None:
        self._client = client
        self._secrets: tuple[str, ...] = ()
        self._warned = False

    def register_secrets(self, secrets: Iterable[str]) -> None:
        self._secrets = tuple(s for s in secrets if isinstance(s, str) and s.strip())

    def mask(self, *, data: Any, **_: Any) -> Any:
        """Langfuse mask hook: defence in depth on top of the router's own scrubbing."""
        try:
            return scrub_payload(data, self._secrets)
        except Exception:  # noqa: BLE001 - never export an unscrubbed payload
            return "[MASK_FAILED]"

    def start_call(self, task: str, system: str, user: str) -> Any:
        try:
            attrs = _propagation(task, _CONTEXT.get())
            with _scope(attrs):
                root = self._client.start_observation(
                    name=f"llm.{task}", as_type="span", input=_review_input(user), metadata={"task": task})
            return _Call(root, system, user, attrs)
        except Exception as exc:  # noqa: BLE001
            self._warn("start_call", exc)
            return NullCall()

    def score(self, trace_id: str | None, name: str, value: float | bool | str, *,
              comment: str | None = None) -> None:
        if not trace_id:
            return
        try:
            if isinstance(value, bool):
                self._client.create_score(trace_id=trace_id, name=name, value=1.0 if value else 0.0,
                                          data_type="BOOLEAN", comment=comment)
            elif isinstance(value, str):
                self._client.create_score(trace_id=trace_id, name=name, value=value,
                                          data_type="CATEGORICAL", comment=comment)
            else:
                self._client.create_score(trace_id=trace_id, name=name, value=float(value),
                                          data_type="NUMERIC", comment=comment)
        except Exception as exc:  # noqa: BLE001
            self._warn("score", exc)

    def auth_check(self) -> bool:
        """Blocking credential check against the Langfuse API (CLI only, never the worker loop)."""
        return bool(self._client.auth_check())

    def trace_url(self, trace_id: str | None) -> str | None:
        return self._client.get_trace_url(trace_id=trace_id) if trace_id else None

    def flush(self) -> None:
        try:
            self._client.flush()
        except Exception as exc:  # noqa: BLE001
            self._warn("flush", exc)

    def _warn(self, where: str, exc: Exception) -> None:
        if not self._warned:  # once per process: a Langfuse outage must not flood the worker log
            self._warned = True
            logger.warning("langfuse_%s_failed: %s (tracing continues best-effort)", where, type(exc).__name__)


def tracing_configured(env: Mapping[str, str]) -> bool:
    if (env.get(ENABLED_ENV) or "").strip().lower() in _FALSE:
        return False
    return bool((env.get(PUBLIC_KEY_ENV) or "").strip() and (env.get(SECRET_KEY_ENV) or "").strip())


def tracer_from_env(env: Mapping[str, str]) -> NullTracer | LangfuseTracer:
    """Process-wide tracer for these credentials; `NullTracer` when Langfuse is not configured."""
    if not tracing_configured(env):
        return NullTracer()
    public_key = env[PUBLIC_KEY_ENV].strip()
    base_url = next((env[name].strip() for name in BASE_URL_ENVS if (env.get(name) or "").strip()),
                    DEFAULT_BASE_URL)
    cached = _TRACERS.get((public_key, base_url))
    if cached is not None:
        return cached
    try:
        from langfuse import Langfuse
        from langfuse.span_filter import is_langfuse_span
        from opentelemetry.sdk.trace import TracerProvider

        tracer = LangfuseTracer(None)
        tracer._client = Langfuse(
            public_key=public_key, secret_key=env[SECRET_KEY_ENV].strip(), base_url=base_url,
            environment=(env.get(ENVIRONMENT_ENV) or "production").strip() or "production",
            tracer_provider=TracerProvider(), should_export_span=is_langfuse_span, mask=tracer.mask)
    except Exception:  # missing package or bad config: run untraced
        logger.warning("langfuse_init_failed: tracing disabled", exc_info=True)
        return NullTracer()
    _TRACERS[(public_key, base_url)] = tracer
    logger.info("langfuse tracing enabled base_url=%s", base_url)
    return tracer
