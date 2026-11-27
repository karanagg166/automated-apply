"""Phase 4 semantic-cache admin API: stats, inspect, quarantine/unquarantine, purge, explain, status
filter, owner bearer on every route and 422 for questions the cache refuses."""

import pytest

from backend.app.ai_v2.semantic_cache import QuestionContext
from backend.tests.test_ai_v2_api import BASE, ai  # noqa: F401 - fixture

ENTRY = "22222222-2222-4222-8222-222222222222"


async def test_admin_routes_require_owner_bearer(async_client, phase2_auth, ai):  # noqa: F811
    for method, path in [("GET", "/semantic-cache/stats"), ("GET", f"/semantic-cache/{ENTRY}"),
                         ("POST", f"/semantic-cache/{ENTRY}/quarantine"),
                         ("POST", f"/semantic-cache/{ENTRY}/unquarantine"),
                         ("POST", "/semantic-cache/purge"), ("POST", "/semantic-cache/explain")]:
        response = await async_client.request(method, BASE + path, headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401, path


async def test_inspect_quarantine_purge_and_stats(async_client, phase2_auth, ai):  # noqa: F811
    put = await ai.cache.put("screening_qa", "Are you willing to work night shifts?", "No", "user",
                             context=QuestionContext(field_kind="radio", options=("Yes", "No")))
    entry_id = put.entry.id
    detail = (await async_client.get(f"{BASE}/semantic-cache/{entry_id}", headers=phase2_auth)).json()
    assert detail["status"] == "active" and detail["trust"] == "human_verified"
    assert detail["field_type"] == "boolean" and detail["scope"] == "global" and len(detail["cache_key"]) == 64
    assert (await async_client.get(f"{BASE}/semantic-cache/not-a-uuid", headers=phase2_auth)).status_code == 404

    quarantined = await async_client.post(f"{BASE}/semantic-cache/{entry_id}/quarantine", headers=phase2_auth,
                                          json={"reason": "wrong answer"})
    assert quarantined.status_code == 200 and quarantined.json()["status"] == "quarantined"
    listed = (await async_client.get(f"{BASE}/semantic-cache?status=quarantined", headers=phase2_auth)).json()
    assert listed["total"] == 1
    assert await ai.cache.lookup("screening_qa", "Are you willing to work night shifts?") is None
    restored = await async_client.post(f"{BASE}/semantic-cache/{entry_id}/unquarantine", headers=phase2_auth)
    assert restored.json()["status"] == "active"

    await async_client.post(f"{BASE}/semantic-cache/{entry_id}/quarantine", headers=phase2_auth, json={})
    stats = (await async_client.get(f"{BASE}/semantic-cache/stats", headers=phase2_auth)).json()
    assert stats["status_counts"]["quarantined"] == 1 and "decisions" in stats and "thresholds" in stats
    purged = await async_client.post(f"{BASE}/semantic-cache/purge", headers=phase2_auth,
                                     json={"status": "quarantined"})
    assert purged.json() == {"deleted": 1}
    refused = await async_client.post(f"{BASE}/semantic-cache/purge", headers=phase2_auth, json={"status": "active"})
    assert refused.status_code == 422  # active rows are never bulk-purged


async def test_explain_is_a_dry_run(async_client, phase2_auth, ai):  # noqa: F811
    await ai.cache.put("screening_qa", "How many years of experience do you have with Java?", "1", "user")
    body = {"question": "How many years of experience do you have with JavaScript?", "field_kind": "number"}
    explained = (await async_client.post(f"{BASE}/semantic-cache/explain", headers=phase2_auth, json=body)).json()
    assert explained["intent_bucket"] == "tech_experience" and explained["hit"] is None
    assert explained["entities"] == {"tech": ["javascript"]}
    same = {"question": "How many years of experience do you have with Java?"}
    hit = (await async_client.post(f"{BASE}/semantic-cache/explain", headers=phase2_auth, json=same)).json()["hit"]
    assert hit["match"] == "exact" and hit["answer"] == "1"
    rows, _ = await ai.cache.store.list_entries(None, None, 10, 0)
    assert rows[0].hits == 0  # explain never counts a hit


@pytest.mark.parametrize("question", ["Please write a cover letter for us", "Why do you want to work here?",
                                      "Will you require visa sponsorship?"])
async def test_create_refuses_non_cacheable_questions(async_client, phase2_auth, ai, question):  # noqa: F811
    response = await async_client.post(f"{BASE}/semantic-cache", headers=phase2_auth,
                                       json={"question_text": question, "answer_text": "x"})
    assert response.status_code == 422 and "not cacheable" in response.json()["detail"]
