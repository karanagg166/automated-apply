"""/api/v1/v2/ai/status and /api/v1/v2/semantic-cache (owner bearer, curation, no key leaks)."""

import json

import httpx
import pytest

from backend.app.ai_v2.embeddings import DeterministicTestEmbedder
from backend.app.ai_v2.runtime import AIRuntime
from backend.app.ai_v2.semantic_cache import MemoryCacheStore
from backend.app.ai_v2.usage import MemoryUsageStore
from backend.app.api.v1.automation_v2 import get_ai_runtime, get_v2_store
from backend.app.browser_v2.store import MemoryStore
from backend.app.main import app

BASE = "/api/v1/v2"
FAKE = "TEST_FAKE_TOKEN_ONLY"


@pytest.fixture
def ai():
    runtime = AIRuntime.build(MemoryCacheStore(), MemoryUsageStore(), embedder=DeterministicTestEmbedder(),
                              env={"GROQ_API_KEY": FAKE},
                              transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    memory = MemoryStore()

    async def store_override():
        yield memory

    async def ai_override():
        return runtime

    app.dependency_overrides[get_v2_store] = store_override
    app.dependency_overrides[get_ai_runtime] = ai_override
    yield runtime
    app.dependency_overrides.pop(get_v2_store, None)
    app.dependency_overrides.pop(get_ai_runtime, None)


async def test_ai_routes_require_owner_bearer(async_client, phase2_auth, ai):
    for method, path in [("GET", "/ai/status"), ("GET", "/semantic-cache"), ("POST", "/semantic-cache"),
                         ("DELETE", "/semantic-cache/22222222-2222-4222-8222-222222222222")]:
        response = await async_client.request(method, BASE + path, headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401, path


async def test_ai_status_reports_every_provider_without_leaking_keys(async_client, phase2_auth, ai):
    response = await async_client.get(f"{BASE}/ai/status", headers=phase2_auth)
    assert response.status_code == 200, response.text
    body = response.json()
    states = {p["provider"]: p["status"] for p in body["providers"]}
    assert states["groq"] == "healthy" and states["gemini"] == "unconfigured" and len(states) == 6
    groq = next(p for p in body["providers"] if p["provider"] == "groq")
    assert groq["rpd_limit"] == 900 and groq["requests_today"] == 0 and groq["key_envs"] == ["GROQ_API_KEY"]
    assert body["chains"]["screening_qa"][0] == "groq" and body["chains"]["jd_scoring"][0] == "gemini"
    assert body["semantic_cache"] | {} == {
        "backend": "memory", "total_entries": 0, "total_hits": 0, "threshold": 0.88,
        "embedding_model": "deterministic-test-embedder", "embedding_dimensions": 384, "embedding_ready": True}
    assert body["local_generative_llm"] == "disabled"
    assert FAKE not in json.dumps(body)


async def test_ai_status_shows_circuit_after_failures(async_client, phase2_auth, ai):
    from pydantic import BaseModel

    from backend.app.ai_v2.router import AllLLMProvidersExhaustedError

    class Reply(BaseModel):
        ok: bool

    with pytest.raises(AllLLMProvidersExhaustedError):
        await ai.router.generate_json("screening_qa", "s", "u", Reply)
    body = (await async_client.get(f"{BASE}/ai/status", headers=phase2_auth)).json()
    groq = next(p for p in body["providers"] if p["provider"] == "groq")
    assert groq["status"] == "cooldown" and groq["last_error"] == "http_500"  # first failure: 10 s backoff
    assert groq["requests_today"] == 1 and groq["circuit_open_until"]


async def test_semantic_cache_create_list_search_and_delete(async_client, phase2_auth, ai):
    created = await async_client.post(f"{BASE}/semantic-cache", headers=phase2_auth, json={
        "question_text": "  Are you willing to work night shifts?  ", "answer_text": "No"})
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["source"] == "user" and entry["kind"] == "screening_qa" and entry["hits"] == 0
    assert entry["question_text"] == "Are you willing to work night shifts?"
    await ai.cache.put("screening_qa", "Do you have a valid passport?", "Yes", "profile")
    await ai.cache.lookup("screening_qa", "are you willing to work night shifts")
    listed = (await async_client.get(f"{BASE}/semantic-cache?kind=screening_qa", headers=phase2_auth)).json()
    assert listed["total"] == 2 and listed["limit"] == 50
    searched = (await async_client.get(f"{BASE}/semantic-cache?q=night", headers=phase2_auth)).json()
    assert searched["total"] == 1 and searched["items"][0]["hits"] == 1
    page = (await async_client.get(f"{BASE}/semantic-cache?limit=1&offset=1", headers=phase2_auth)).json()
    assert len(page["items"]) == 1 and page["total"] == 2
    status = (await async_client.get(f"{BASE}/ai/status", headers=phase2_auth)).json()["semantic_cache"]
    assert status["total_entries"] == 2 and status["total_hits"] == 1
    deleted = await async_client.delete(f"{BASE}/semantic-cache/{entry['id']}", headers=phase2_auth)
    assert deleted.status_code == 204 and deleted.content == b""
    again = await async_client.delete(f"{BASE}/semantic-cache/{entry['id']}", headers=phase2_auth)
    assert again.status_code == 404
    assert (await async_client.delete(f"{BASE}/semantic-cache/not-a-uuid", headers=phase2_auth)).status_code == 404
    assert await ai.cache.lookup("screening_qa", "Are you willing to work night shifts?") is None


async def test_user_answer_overrides_llm_answer(async_client, phase2_auth, ai):
    await ai.cache.put("screening_qa", "Notice period?", "60 days", "llm")
    response = await async_client.post(f"{BASE}/semantic-cache", headers=phase2_auth, json={
        "question_text": "Notice period?", "answer_text": "30 days"})
    assert response.status_code == 201 and response.json()["source"] == "user"
    assert (await ai.cache.lookup("screening_qa", "notice period")).entry.answer_text == "30 days"


@pytest.mark.parametrize("payload", [
    {"question_text": "ok", "answer_text": "x"},
    {"question_text": "Valid question?", "answer_text": "   "},
    {"question_text": "Valid question?", "answer_text": "x", "kind": "Bad Kind"},
    {"question_text": "Valid question?", "answer_text": "x", "source": "llm"},
    {"question_text": "q" * 1001, "answer_text": "x"},
    {"question_text": "???", "answer_text": "x"},
])
async def test_semantic_cache_validation(async_client, phase2_auth, ai, payload):
    response = await async_client.post(f"{BASE}/semantic-cache", headers=phase2_auth, json=payload)
    assert response.status_code == 422, response.text
