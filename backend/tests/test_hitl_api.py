"""/api/v1/v2/hitl* and /telegram/status: owner bearer, same resolution service as Telegram, no token leaks."""

import httpx
import pytest

from backend.app.ai_v2.embeddings import DeterministicTestEmbedder
from backend.app.ai_v2.runtime import AIRuntime
from backend.app.ai_v2.semantic_cache import MemoryCacheStore
from backend.app.ai_v2.usage import MemoryUsageStore
from backend.app.api.v1.automation_v2 import get_ai_runtime, get_v2_store
from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore
from backend.app.main import app

BASE = "/api/v1/v2"
TOKEN = "123456789:TEST_FAKE_TOKEN_ONLY_abcdefghijklmnop"
QUESTION = "Are you comfortable working night shifts?"


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Isolate from the owner's private env file (it may hold the real bot token)."""
    private = tmp_path / "test.env"
    private.write_text("")
    monkeypatch.setenv("AUTOMATED_APPLY_ENV_FILE", str(private))
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_OWNER_CHAT_ID", "TELEGRAM_OWNER_USER_ID", "TELEGRAM_V2_DISABLED"):
        monkeypatch.delenv(name, raising=False)
    return private


@pytest.fixture
def ctx(env):
    memory = MemoryStore()
    runtime = AIRuntime.build(MemoryCacheStore(), MemoryUsageStore(), embedder=DeterministicTestEmbedder(),
                              env={}, transport=httpx.MockTransport(lambda r: httpx.Response(500)))

    async def store_override():
        yield memory

    async def ai_override():
        return runtime

    app.dependency_overrides[get_v2_store] = store_override
    app.dependency_overrides[get_ai_runtime] = ai_override
    yield memory, runtime
    app.dependency_overrides.pop(get_v2_store, None)
    app.dependency_overrides.pop(get_ai_runtime, None)


async def waiting(store, i=1, *, options=("Yes", "No"), kind="QUESTION"):
    record = await store.upsert_discovered(JobListing(platform="naukri", external_job_id=f"j{i}",
                                                      url=f"https://example.com/{i}", title="Backend Engineer",
                                                      company="Globex"))
    record = await store.transition(record, S.APPLYING, "apply_started")
    record = await store.transition(record, S.WAITING_FOR_USER, "question_requires_owner")
    hitl_id = await store.create_hitl(record, "naukri", kind, QUESTION,
                                      {"options": list(options), "context": {"resolver_reason": "llm_unconfigured"}})
    return record, hitl_id


async def test_hitl_and_telegram_routes_require_owner_bearer(async_client, phase2_auth, ctx):
    fake_id = "11111111-1111-4111-8111-111111111111"
    for method, path in [("GET", "/telegram/status"), ("GET", "/hitl"), ("POST", f"/hitl/{fake_id}/resolve"),
                         ("POST", f"/hitl/{fake_id}/skip"), ("POST", f"/hitl/{fake_id}/retry"),
                         ("POST", "/portal-rules/naukri/resume-auth")]:
        response = await async_client.request(method, BASE + path, headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401, path


async def test_telegram_status_unconfigured_and_configured_never_leaks_token(async_client, phase2_auth, ctx, env):
    store, _ = ctx
    body = (await async_client.get(f"{BASE}/telegram/status", headers=phase2_auth)).json()
    assert body["configured"] is False and body["polling_state"] == "unconfigured"
    assert "TELEGRAM_BOT_TOKEN" in body["last_error"]
    env.write_text(f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_OWNER_CHAT_ID=987654321\n")
    await store.update_telegram_state(polling_state="conflict", last_error="Another poller")
    await waiting(store)
    response = await async_client.get(f"{BASE}/telegram/status", headers=phase2_auth)
    body = response.json()
    assert body["configured"] is True and body["conflict_detected"] is True and body["open_hitl_count"] == 1
    assert body["owner_chat_id"] == "••••••321"
    assert TOKEN not in response.text and "TEST_FAKE_TOKEN_ONLY" not in response.text


async def test_inbox_lists_open_items_with_ref_options_and_job(async_client, phase2_auth, ctx):
    store, _ = ctx
    _, hitl_id = await waiting(store)
    await store.create_hitl(None, "naukri", "AUTH", "[Naukri] Session expired", {})
    page = (await async_client.get(f"{BASE}/hitl?status=OPEN&platform=naukri", headers=phase2_auth)).json()
    assert page["total"] == 2
    item = next(i for i in page["items"] if i["id"] == hitl_id)
    assert item["ref"] == hitl_id.replace("-", "")[:6] and item["options"] == ["Yes", "No"]
    assert item["company"] == "Globex" and item["title"] == "Backend Engineer"
    assert item["resolver_reason"] == "llm_unconfigured" and item["application_state"] == "WAITING_FOR_USER"
    bad = await async_client.get(f"{BASE}/hitl?platform=Bad-Portal", headers=phase2_auth)
    assert bad.status_code == 422


async def test_resolve_caches_requeues_and_rejects_second_answer(async_client, phase2_auth, ctx):
    store, runtime = ctx
    _record, hitl_id = await waiting(store)
    invalid = await async_client.post(f"{BASE}/hitl/{hitl_id}/resolve", headers=phase2_auth,
                                      json={"answer": "Sometimes"})
    assert invalid.status_code == 422 and "1. Yes\n2. No" in invalid.json()["detail"]
    assert (await store.get_hitl(hitl_id)).status == "OPEN"
    ok = await async_client.post(f"{BASE}/hitl/{hitl_id}/resolve", headers=phase2_auth,
                                 json={"answer": "yes", "cache_answer": True})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["answer"] == "Yes" and body["cached"] and body["requeued"] and body["application_state"] == "SCORED"
    assert body["hitl"]["resolved_via"] == "dashboard"
    hit = await runtime.cache.lookup("screening_qa", QUESTION)
    assert hit.entry.answer_text == "Yes" and hit.entry.source == "user"
    again = await async_client.post(f"{BASE}/hitl/{hitl_id}/resolve", headers=phase2_auth, json={"answer": "No"})
    assert again.status_code == 409
    missing = await async_client.post(f"{BASE}/hitl/not-a-uuid/resolve", headers=phase2_auth, json={"answer": "x"})
    assert missing.status_code == 404


async def test_resolve_without_cache_and_skip(async_client, phase2_auth, ctx):
    store, runtime = ctx
    _record, hitl_id = await waiting(store, 1, options=())
    response = await async_client.post(f"{BASE}/hitl/{hitl_id}/resolve", headers=phase2_auth,
                                       json={"answer": "Only weekends", "cache_answer": False})
    assert response.status_code == 200 and response.json()["cached"] is False
    assert (await runtime.cache.stats())["total_entries"] == 0
    second, skip_id = await waiting(store, 2)
    skipped = await async_client.post(f"{BASE}/hitl/{skip_id}/skip", headers=phase2_auth)
    assert skipped.status_code == 200 and skipped.json()["application_state"] == "FILTERED_OUT"
    assert (await store.get_application(second.id)).reason == "skipped_by_owner_hitl"


async def test_resume_auth_resets_portal_and_closes_auth_requests(async_client, phase2_auth, ctx):
    store, _ = ctx
    await store.record_auth("naukri", "AUTH_REQUIRED")
    auth_id = await store.create_hitl(None, "naukri", "AUTH", "[Naukri] Session expired", {})
    response = await async_client.post(f"{BASE}/portal-rules/naukri/resume-auth", headers=phase2_auth)
    assert response.status_code == 200 and response.json()["resolved_auth_requests"] == 1
    assert (await store.get_rules("naukri")).auth_status == "UNKNOWN"
    assert (await store.get_hitl(auth_id)).status == "ANSWERED"
    unknown = await async_client.post(f"{BASE}/portal-rules/linkedin/resume-auth", headers=phase2_auth)
    assert unknown.status_code == 404
