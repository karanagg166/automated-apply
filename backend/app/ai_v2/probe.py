"""Per-provider live health probe for `cli ai-test` (zero PII, ~20 tokens per provider).

Each configured free provider is called individually (no failover) with a fixed
1-sentence JSON prompt; the report carries only provider/model/status/latency/json_valid.
Response bodies and keys are never returned or logged.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from backend.app.ai_v2.providers import (
    ProviderConfig,
    ProviderResponseError,
    build_request,
    extract_json_object,
    parse_response,
)

PROBE_SYSTEM = "Reply with one JSON object only."
PROBE_USER = 'Return exactly {"ok": true}.'
PROBE_MAX_OUTPUT_TOKENS = 20
OPENROUTER_CATALOG_URL = "https://openrouter.ai/api/v1/models"


class ProbeReply(BaseModel):
    ok: bool


def classify_status(code: int) -> str:
    if code < 400:
        return "OK"
    if code in (401, 403, 404, 429):
        return str(code)
    return "5xx" if code >= 500 else f"http_{code}"


async def probe_provider(config: ProviderConfig, client: httpx.AsyncClient) -> dict[str, Any]:
    row: dict[str, Any] = {"provider": config.name, "model": config.model, "status": "unconfigured",
                           "latency_ms": None, "json_valid": False}
    if not config.configured:
        return row | {"problem": config.problem}
    request = build_request(config, PROBE_SYSTEM, PROBE_USER, max_output_tokens=PROBE_MAX_OUTPUT_TOKENS,
                            temperature=0.0)
    started = time.perf_counter()
    try:
        response = await client.post(request.url, headers=request.headers, json=request.body)
    except httpx.TimeoutException:
        return row | {"status": "timeout", "latency_ms": round((time.perf_counter() - started) * 1000)}
    except httpx.HTTPError as exc:
        return row | {"status": "error", "error": "network_" + type(exc).__name__}
    row["latency_ms"] = round((time.perf_counter() - started) * 1000)
    row["status"] = classify_status(response.status_code)
    if response.status_code >= 400:
        return row
    try:
        wire = parse_response(config, response.json())
        ProbeReply.model_validate(extract_json_object(wire.text))
    except (ValueError, ProviderResponseError, ValidationError) as exc:
        return row | {"error": "invalid_json:" + type(exc).__name__}
    return row | {"json_valid": True}


async def openrouter_free_catalog(client: httpx.AsyncClient) -> set[str] | None:
    """Public (keyless) OpenRouter catalog: the live set of `:free` model ids, or None if unreachable."""
    try:
        response = await client.get(OPENROUTER_CATALOG_URL)
        response.raise_for_status()
        data = response.json().get("data") or []
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    return {str(item.get("id")) for item in data if isinstance(item, dict)
            and str(item.get("id", "")).endswith(":free")}


async def probe_all(providers: dict[str, ProviderConfig], *, only: Iterable[str] = (),
                    transport: httpx.AsyncBaseTransport | None = None,
                    timeout_sec: float = 20.0) -> dict[str, Any]:
    wanted = set(only)
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient(transport=transport, timeout=timeout_sec, follow_redirects=False) as client:
        for name, config in providers.items():  # sequential: one request in flight at a time
            if wanted and name not in wanted:
                continue
            rows.append(await probe_provider(config, client))
        catalog = await openrouter_free_catalog(client)
    openrouter = providers.get("openrouter")
    catalog_check: dict[str, Any] = {"reachable": catalog is not None}
    if catalog is not None and openrouter is not None:
        catalog_check |= {"model": openrouter.model, "model_listed": openrouter.model in catalog,
                          "free_models_listed": len(catalog)}
    ok = sum(1 for row in rows if row["status"] == "OK" and row["json_valid"])
    configured = sum(1 for row in rows if row["status"] != "unconfigured")
    return {"providers": rows, "configured": configured, "passed": ok, "total": len(rows),
            "openrouter_catalog": catalog_check}
