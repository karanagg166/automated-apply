"""Phase 9D API: GET /profile-sync/status and POST /profile-sync/request (enqueue only)."""

from __future__ import annotations

import pytest

from backend.app.api.v1.automation_v2 import get_v2_store
from backend.app.api.v1.v2.routers.profile import get_profile_sync_requester
from backend.app.browser_v2.profile_sync.runs import runs_for
from backend.app.browser_v2.store import MemoryStore
from backend.app.main import app

BASE = "/api/v1/v2"


@pytest.fixture
def store():
    memory = MemoryStore(profile={"preferences": {"profile_sync": {"naukri": {"live": True}}}})

    async def override():
        yield memory

    app.dependency_overrides[get_v2_store] = override
    yield memory
    app.dependency_overrides.pop(get_v2_store, None)


class FakeRequester:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], bool, str]] = []

    async def request_sync(self, portals, *, dry_run, trigger):
        self.calls.append((list(portals), dry_run, trigger))
        return f"Queued profile sync for {', '.join(portals)}"


async def test_status_lists_portals_flags_and_last_run(async_client, phase2_auth, store):
    runs = runs_for(store)
    run_id = await runs.start("naukri", "cli", True)
    await runs.finish(run_id, "skipped", {"profile_summary": {"status": "skipped_not_calibrated",
                                                              "proposed": {"sha256": "0" * 64, "length": 3}}})
    response = await async_client.get(f"{BASE}/profile-sync/status", headers=phase2_auth)
    assert response.status_code == 200, response.text
    body = response.json()
    portals = {p["platform"]: p for p in body["portals"]}
    assert set(portals) == {"naukri", "instahyre", "internshala", "wellfound", "work_at_a_startup"}
    assert portals["naukri"]["live"] is True and portals["wellfound"]["live"] is False
    assert all(p["calibrated"] is False for p in portals.values())
    assert portals["naukri"]["last_run"]["status"] == "skipped"
    assert portals["naukri"]["last_run"]["fields"] == {"profile_summary": "skipped_not_calibrated"}
    assert "sha256" not in response.text and portals["wellfound"]["last_run"] is None


async def test_request_without_a_worker_scheduler_is_409_worker_only(async_client, phase2_auth, store):
    response = await async_client.post(f"{BASE}/profile-sync/request", headers=phase2_auth,
                                       json={"portals": ["naukri"], "dry_run": True})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "worker_only"


async def test_request_enqueues_via_the_injected_requester(async_client, phase2_auth, store):
    requester = FakeRequester()
    app.dependency_overrides[get_profile_sync_requester] = lambda: requester
    try:
        response = await async_client.post(f"{BASE}/profile-sync/request", headers=phase2_auth,
                                           json={"portals": ["naukri", "wellfound"]})
        assert response.status_code == 202, response.text
        assert response.json()["queued"] is True and response.json()["dry_run"] is True
        assert requester.calls == [(["naukri", "wellfound"], True, "dashboard")]
        bad = await async_client.post(f"{BASE}/profile-sync/request", headers=phase2_auth,
                                      json={"portals": ["greenhouse"]})
        assert bad.status_code == 422
        empty = await async_client.post(f"{BASE}/profile-sync/request", headers=phase2_auth, json={"portals": []})
        assert empty.status_code == 422 and len(requester.calls) == 1
    finally:
        app.dependency_overrides.pop(get_profile_sync_requester, None)


async def test_profile_sync_routes_require_the_owner_token(async_client, phase2_auth, store):
    for method, path in [("GET", "/profile-sync/status"), ("POST", "/profile-sync/request")]:
        response = await async_client.request(method, BASE + path, headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401, path
