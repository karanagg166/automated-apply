"""Multi-key failover: several keys per free provider, each its own rate-limit/circuit slot."""

from __future__ import annotations

import json

import httpx

from backend.app.ai_v2.providers import (
    PROVIDER_REGISTRY,
    TASK_CHAINS,
    expand_key_slots,
    key_slot_envs,
)
from backend.app.ai_v2.router import LLMRouter
from backend.tests.test_ai_v2_router import GOOD, Answer, ok_body

K1, K2, K3 = "TEST_FAKE_TOKEN_ONLY_1", "TEST_FAKE_TOKEN_ONLY_2", "TEST_FAKE_TOKEN_ONLY_3"


def key_of(request: httpx.Request) -> str:
    return request.headers.get("x-goog-api-key") or request.headers.get("authorization", "").removeprefix("Bearer ")


def router(env, script):
    """script: key -> list of statuses returned on successive calls (default 200)."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = key_of(request)
        seen.append(key)
        queue = script.get(key, [])
        status = queue.pop(0) if queue else 200
        if status != 200:
            return httpx.Response(status, headers={"retry-after": "60"}, json={"error": "x"})
        provider = "gemini" if "generativelanguage" in str(request.url) else "openai"
        return httpx.Response(200, json=ok_body(provider))

    return LLMRouter(env=env, transport=httpx.MockTransport(handler)), seen


def test_numbered_keys_become_distinct_slots_and_duplicates_are_dropped():
    env = {"GEMINI_API_KEY": K1, "GEMINI_API_KEY_2": K2, "GEMINI_API_KEY_3": K1, "GEMINI_API_KEY_4": K3}
    assert key_slot_envs(PROVIDER_REGISTRY["gemini"], env) == ["GEMINI_API_KEY", "GEMINI_API_KEY_2",
                                                               "GEMINI_API_KEY_4"]
    registry, chains = expand_key_slots(PROVIDER_REGISTRY, TASK_CHAINS, env)
    assert [n for n in registry if n.startswith("gemini")] == ["gemini", "gemini_2", "gemini_3"]
    assert registry["gemini_3"].key_envs == ("GEMINI_API_KEY_4",) and "[key 3]" in registry["gemini_3"].label
    for chain in chains.values():  # a provider's keys are tried consecutively, before the next provider
        i = chain.index("gemini")
        assert chain[i:i + 3] == ("gemini", "gemini_2", "gemini_3")


def test_single_key_keeps_the_original_registry_and_chains():
    registry, chains = expand_key_slots(PROVIDER_REGISTRY, TASK_CHAINS, {"GROQ_API_KEY": K1})
    assert set(registry) == set(PROVIDER_REGISTRY) and chains == dict(TASK_CHAINS)


async def test_rate_limited_key_fails_over_to_next_key_of_same_provider():
    r, seen = router({"GEMINI_API_KEY": K1, "GEMINI_API_KEY_2": K2}, {K1: [429]})
    result = await r.generate_json("jd_scoring", "s", "u", Answer)
    assert result.provider == "gemini_2" and result.value.model_dump() == GOOD
    assert seen == [K1, K2]
    assert [a["outcome"] for a in result.attempts[:2]] == ["http_429", "ok"]
    # Key 1 is cooling down (Retry-After 60 s): the next call goes straight to key 2.
    again = await r.generate_json("jd_scoring", "s", "u", Answer)
    assert again.provider == "gemini_2" and seen == [K1, K2, K2]


async def test_revoked_key_opens_only_its_own_circuit():
    r, seen = router({"GROQ_API_KEY": K1, "GROQ_API_KEY_2": K2, "GROQ_API_KEY_3": K3}, {K1: [401], K2: [503]})
    result = await r.generate_json("screening_qa", "s", "u", Answer)
    assert result.provider == "groq_3" and seen == [K1, K2, K3]
    states = {p["provider"]: p["status"] for p in await r.status()}
    assert states["groq"] == "circuit_open" and states["groq_2"] == "cooldown" and states["groq_3"] == "healthy"


async def test_all_keys_of_one_provider_exhausted_moves_to_next_provider():
    env = {"GEMINI_API_KEY": K1, "GEMINI_API_KEY_2": K2, "COHERE_API_KEY": K3, "COHERE_API_KEY_2": "TEST_FAKE_4"}
    r, seen = router(env, {K1: [429], K2: [429], K3: [429]})
    result = await r.generate_json("email_draft", "s", "u", Answer)
    assert result.provider == "cohere_2" and seen == [K1, K2, K3, "TEST_FAKE_4"]


async def test_status_lists_every_slot_without_leaking_keys():
    r, _ = router({"GEMINI_API_KEY": K1, "GEMINI_API_KEY_2": K2, "COHERE_API_KEY": K3}, {})
    status = await r.status()
    rows = {p["provider"]: p for p in status}
    assert rows["gemini_2"]["key_envs"] == ["GEMINI_API_KEY_2"] and rows["cohere"]["status"] == "healthy"
    dumped = json.dumps(status, default=str)
    assert all(k not in dumped for k in (K1, K2, K3))
