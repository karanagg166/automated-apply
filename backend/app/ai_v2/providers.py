"""Config-driven registry of FREE external LLM providers (no SDKs, plain httpx).

Adding a provider = one `ProviderSpec` entry here + its env var. Nothing else.
Caps are conservative local limits below each free tier; the provider's own
429 responses are still honoured. Local generative endpoints (Ollama,
llama.cpp, LM Studio, vLLM, localhost, private IPs) are rejected outright.
"""

from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

ApiStyle = Literal["openai", "gemini", "cloudflare"]


class LocalLLMForbiddenError(ValueError):
    """AGENTS.md §1.2: v2 must never route to a local generative LLM."""


class PaidModelRefusedError(ValueError):
    """A configured model that is not a free-tier model (e.g. OpenRouter without `:free`)."""


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    label: str
    api_style: ApiStyle
    base_url: str  # may contain {account_id} and {model}
    default_model: str
    key_envs: tuple[str, ...]  # first non-empty wins
    model_env: str
    rpm: int
    rpd: int
    tpd: int | None
    required_envs: tuple[str, ...] = ()  # e.g. Cloudflare account id
    json_mode: bool = True
    free_model_suffix: str | None = None  # OpenRouter: only ":free" models allowed


@dataclass(frozen=True)
class ProviderConfig:
    spec: ProviderSpec
    api_key: str = ""
    model: str = ""
    extra: Mapping[str, str] | None = None
    problem: str | None = None  # why it is unusable (None = configured)

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def configured(self) -> bool:
        return self.problem is None


PROVIDER_REGISTRY: dict[str, ProviderSpec] = {
    spec.name: spec for spec in (
        ProviderSpec("groq", "Groq", "openai", "https://api.groq.com/openai/v1/chat/completions",
                     "llama-3.3-70b-versatile", ("GROQ_API_KEY",), "GROQ_MODEL",
                     rpm=25, rpd=900, tpd=90_000),
        ProviderSpec("gemini", "Google AI Studio (Gemini)", "gemini",
                     "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                     "gemini-2.5-flash", ("GEMINI_API_KEY", "GOOGLE_API_KEY"), "GEMINI_MODEL",
                     rpm=8, rpd=200, tpd=1_000_000),
        ProviderSpec("mistral", "Mistral (Experiment tier)", "openai", "https://api.mistral.ai/v1/chat/completions",
                     "mistral-small-latest", ("MISTRAL_API_KEY",), "MISTRAL_MODEL",
                     rpm=30, rpd=1_000, tpd=1_000_000),
        ProviderSpec("openrouter", "OpenRouter (:free models)", "openai",
                     "https://openrouter.ai/api/v1/chat/completions",
                     "meta-llama/llama-3.3-70b-instruct:free", ("OPENROUTER_API_KEY",), "OPENROUTER_MODEL",
                     rpm=15, rpd=45, tpd=None, json_mode=False, free_model_suffix=":free"),
        ProviderSpec("cloudflare", "Cloudflare Workers AI", "cloudflare",
                     "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}",
                     "@cf/meta/llama-3.3-70b-instruct-fp8-fast", ("CLOUDFLARE_API_TOKEN",), "CLOUDFLARE_MODEL",
                     rpm=20, rpd=250, tpd=None, required_envs=("CLOUDFLARE_ACCOUNT_ID",), json_mode=False),
        ProviderSpec("github_models", "GitHub Models", "openai", "https://models.github.ai/inference/chat/completions",
                     "openai/gpt-4.1-mini", ("GITHUB_MODELS_TOKEN", "GITHUB_TOKEN"), "GITHUB_MODELS_MODEL",
                     rpm=10, rpd=140, tpd=None),
        # Phase 6A: Cerebras free tier (1M tokens/day); conservative local caps below it.
        ProviderSpec("cerebras", "Cerebras (free tier)", "openai", "https://api.cerebras.ai/v1/chat/completions",
                     "llama-3.3-70b", ("CEREBRAS_API_KEY",), "CEREBRAS_MODEL",
                     rpm=25, rpd=12_000, tpd=900_000),
    )
}

# Phase 6A: an owner-deployed OpenAI-compatible endpoint (e.g. a fine-tuned open model on
# Modal). Enabled by 3 env vars, zero code changes; HTTPS + public host only (never
# localhost / LAN / private IPs / local runtimes). Placement: CUSTOM_CLOUD_LLM_PRIORITY.
CUSTOM_CLOUD_NAME = "custom_cloud_llm"
CUSTOM_CLOUD_ENVS = ("CUSTOM_CLOUD_LLM_BASE_URL", "CUSTOM_CLOUD_LLM_API_KEY", "CUSTOM_CLOUD_LLM_MODEL")


def custom_cloud_spec(env: Mapping[str, str]) -> ProviderSpec | None:
    """The custom slot's spec, or None when CUSTOM_CLOUD_LLM_BASE_URL is unset.

    Raises LocalLLMForbiddenError for a non-HTTPS / local / private endpoint or model.
    """
    base = (env.get("CUSTOM_CLOUD_LLM_BASE_URL") or "").strip()
    if not base:
        return None
    url = base.rstrip("/")
    if not url.endswith("/chat/completions"):
        url += "/chat/completions"
    model = (env.get("CUSTOM_CLOUD_LLM_MODEL") or "").strip() or "custom-model"
    spec = ProviderSpec(CUSTOM_CLOUD_NAME, "Custom cloud LLM (owner-deployed)", "openai", url, model,
                        ("CUSTOM_CLOUD_LLM_API_KEY",), "CUSTOM_CLOUD_LLM_MODEL", rpm=30, rpd=5_000, tpd=None,
                        json_mode=(env.get("CUSTOM_CLOUD_LLM_JSON_MODE") or "true").strip().lower()
                        not in {"0", "false", "no", "off"})
    assert_remote_free_endpoint(spec)
    return spec


def custom_cloud_priority(env: Mapping[str, str]) -> str:
    value = (env.get("CUSTOM_CLOUD_LLM_PRIORITY") or "fallback").strip().lower()
    return "first" if value == "first" else "fallback"

# Failover order per task (AGENTS.md §4.3). Unknown names are ignored.
TASK_CHAINS: dict[str, tuple[str, ...]] = {
    "screening_qa": ("groq", "cerebras", "gemini", "mistral", "openrouter", "cloudflare", "github_models"),
    "jd_scoring": ("gemini", "groq", "cerebras", "mistral", "openrouter", "cloudflare", "github_models"),
    "email_draft": ("gemini", "groq", "cerebras", "mistral", "openrouter", "cloudflare", "github_models"),
    # Phase 6A: short portal intro / cover notes and the control agent's intent parser.
    "cover_note": ("gemini", "groq", "cerebras", "mistral", "openrouter", "cloudflare", "github_models"),
    "agent_intent": ("groq", "cerebras", "gemini", "mistral", "openrouter", "cloudflare", "github_models"),
}

LOCAL_GENERATIVE_MARKERS = re.compile(
    r"ollama|llama[._-]?cpp|llamafile|lm[._-]?studio|localai|vllm|text-generation-webui|koboldcpp|gpt4all|"
    r"jan\.ai|mlx[._-]?lm|exllama", re.IGNORECASE)
LOCAL_HOSTS = frozenset({"localhost", "0.0.0.0", "127.0.0.1", "::1", "host.docker.internal"})


def assert_remote_free_endpoint(spec: ProviderSpec) -> None:
    """Refuse local/self-hosted generative endpoints and plain-HTTP transports."""
    url = spec.base_url.replace("{account_id}", "acct").replace("{model}", "model")
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if LOCAL_GENERATIVE_MARKERS.search(f"{spec.name} {spec.label} {url} {spec.default_model}"):
        raise LocalLLMForbiddenError(f"local_generative_llm_forbidden:{spec.name}")
    if parts.scheme != "https" or not host or host in LOCAL_HOSTS or host.endswith((".local", ".localhost",
                                                                                    ".internal", ".lan")):
        raise LocalLLMForbiddenError(f"non_remote_endpoint_forbidden:{spec.name}")
    if re.fullmatch(r"[0-9.]+", host):
        try:
            ipaddress.ip_address(host)
        except ValueError:  # "127.1"-style shorthand is a loopback address in disguise
            raise LocalLLMForbiddenError(f"ambiguous_numeric_host_forbidden:{spec.name}") from None
    if host.endswith((".home.arpa", ".home", ".corp", ".intranet", ".private")):
        raise LocalLLMForbiddenError(f"non_remote_endpoint_forbidden:{spec.name}")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved:
        raise LocalLLMForbiddenError(f"private_ip_endpoint_forbidden:{spec.name}")


def validate_registry(registry: Mapping[str, ProviderSpec]) -> None:
    for name, spec in registry.items():
        if name != spec.name:
            raise ValueError(f"registry_key_mismatch:{name}")
        assert_remote_free_endpoint(spec)


def resolve_provider(spec: ProviderSpec, env: Mapping[str, str]) -> ProviderConfig:
    """Read the key/model from env; never raises for a missing key (status `unconfigured`)."""
    assert_remote_free_endpoint(spec)
    key = next((env[k].strip() for k in spec.key_envs if (env.get(k) or "").strip()), "")
    model = (env.get(spec.model_env) or "").strip() or spec.default_model
    if LOCAL_GENERATIVE_MARKERS.search(model):
        raise LocalLLMForbiddenError(f"local_generative_model_forbidden:{spec.name}")
    if not key:
        return ProviderConfig(spec, model=model, problem="missing " + " or ".join(spec.key_envs))
    missing = [k for k in spec.required_envs if not (env.get(k) or "").strip()]
    if missing:
        return ProviderConfig(spec, model=model, problem="missing " + ", ".join(missing))
    if spec.free_model_suffix and not model.endswith(spec.free_model_suffix):
        return ProviderConfig(spec, model=model,
                              problem=f"paid model refused: {spec.model_env} must end with {spec.free_model_suffix}")
    extra = {k: env[k].strip() for k in spec.required_envs}
    return ProviderConfig(spec, api_key=key, model=model, extra=extra)


# --- wire formats -------------------------------------------------------------------
@dataclass(frozen=True)
class WireRequest:
    url: str
    headers: dict[str, str]
    body: dict[str, Any]


@dataclass(frozen=True)
class WireResponse:
    text: str
    input_tokens: int | None
    output_tokens: int | None


class ProviderResponseError(ValueError):
    pass


def build_request(config: ProviderConfig, system_prompt: str, user_prompt: str, *,
                  max_output_tokens: int, temperature: float = 0.1) -> WireRequest:
    spec = config.spec
    url = spec.base_url.replace("{model}", config.model).replace(
        "{account_id}", (config.extra or {}).get("CLOUDFLARE_ACCOUNT_ID", ""))
    if spec.api_style == "gemini":
        return WireRequest(url, {"x-goog-api-key": config.api_key, "content-type": "application/json"}, {
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_output_tokens,
                                 "responseMimeType": "application/json"}})
    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    headers = {"authorization": f"Bearer {config.api_key}", "content-type": "application/json"}
    if spec.api_style == "cloudflare":
        return WireRequest(url, headers, {"messages": messages, "max_tokens": max_output_tokens,
                                          "temperature": temperature})
    body: dict[str, Any] = {"model": config.model, "messages": messages, "temperature": temperature,
                            "max_tokens": max_output_tokens}
    if spec.json_mode:
        body["response_format"] = {"type": "json_object"}
    return WireRequest(url, headers, body)


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def parse_response(config: ProviderConfig, payload: Any) -> WireResponse:
    if not isinstance(payload, dict):
        raise ProviderResponseError("non_object_response")
    style = config.spec.api_style
    try:
        if style == "gemini":
            parts = payload["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            usage = payload.get("usageMetadata") or {}
            return WireResponse(text, _int(usage.get("promptTokenCount")), _int(usage.get("candidatesTokenCount")))
        if style == "cloudflare":
            if payload.get("success") is False:
                raise ProviderResponseError("cloudflare_success_false")
            result = payload["result"]
            response = result.get("response")
            text = response if isinstance(response, str) else json.dumps(response)
            usage = result.get("usage") or {}
            return WireResponse(text, _int(usage.get("prompt_tokens")), _int(usage.get("completion_tokens")))
        text = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage") or {}
        return WireResponse(text if isinstance(text, str) else json.dumps(text), _int(usage.get("prompt_tokens")),
                            _int(usage.get("completion_tokens")))
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise ProviderResponseError(f"unexpected_shape:{type(exc).__name__}") from None


def extract_json_object(text: str) -> Any:
    """Parse the first JSON object in a model reply (tolerates ```json fences / prose)."""
    candidate = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        if start < 0:
            raise ProviderResponseError("no_json_object") from None
        decoder = json.JSONDecoder()
        try:
            value, _ = decoder.raw_decode(candidate[start:])
        except json.JSONDecodeError:
            raise ProviderResponseError("invalid_json") from None
        return value
