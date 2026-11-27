"""v2 "Applied" dashboard API: per-portal summary, application detail (safe receipt projection)
and the `q` search on the application list."""

from datetime import UTC, date, datetime, timedelta

import pytest

from backend.app.api.v1.automation_v2 import get_v2_store
from backend.app.api.v1.v2.routers.application_views import (
    build_summary,
    safe_text,
    safe_url,
    summary_window,
)
from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.rules import DEFAULT_RULES
from backend.app.browser_v2.state import ApplicationState as S
from backend.app.browser_v2.store import MemoryStore
from backend.app.main import app

BASE = "/api/v1/v2"


@pytest.fixture
def store():
    memory = MemoryStore(rules=dict(DEFAULT_RULES))

    async def override():
        yield memory

    app.dependency_overrides[get_v2_store] = override
    yield memory
    app.dependency_overrides.pop(get_v2_store, None)


async def add(store, platform, i, target=None, *, company="Acme", title="Python Developer",
              receipt=None, payload=None, applied_at=None):
    record = await store.upsert_discovered(JobListing(
        platform=platform, external_job_id=str(i), url=f"https://example.com/{platform}/{i}",
        title=title, company=company))
    if target is None:
        return record
    if target not in (S.FILTERED_OUT,):
        record = await store.transition(record, S.APPLYING, "apply_started", count_attempt=True)
    record = await store.transition(record, target, "confirmed" if target == S.APPLIED else "test",
                                    receipt=receipt, payload=payload)
    if applied_at is not None:
        store.records[(platform, str(i))].applied_at = applied_at
    return record


async def test_new_routes_require_owner_bearer(async_client, phase2_auth, store):
    for path in ("/applications/summary", "/applications/00000000-0000-0000-0000-000000000000"):
        response = await async_client.get(BASE + path, headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401, path


async def test_summary_counts_per_portal_and_daily_series(async_client, phase2_auth, store):
    now = datetime.now(UTC)
    await add(store, "naukri", 1, S.APPLIED, applied_at=now)
    await add(store, "naukri", 2, S.APPLIED, applied_at=now - timedelta(days=3))
    await add(store, "naukri", 3, S.APPLIED, applied_at=now - timedelta(days=20))
    await add(store, "naukri", 4, S.SUBMISSION_UNKNOWN)
    await add(store, "naukri", 5, S.WAITING_FOR_USER)
    await add(store, "naukri", 6)  # DISCOVERED
    await add(store, "instahyre", 7, S.APPLIED, applied_at=now)
    await add(store, "instahyre", 8, S.FAILED)
    await add(store, "instahyre", 9, S.FILTERED_OUT)

    response = await async_client.get(f"{BASE}/applications/summary", headers=phase2_auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["timezone"] == "Asia/Kolkata" and body["days"] == 14
    by = {p["platform"]: p for p in body["portals"]}
    naukri, insta = by["naukri"], by["instahyre"]
    assert (naukri["applied_total"], naukri["applied_today"], naukri["applied_7d"]) == (3, 1, 2)
    assert naukri["submission_unknown"] == 1 and naukri["waiting_for_user"] == 1 and naukri["queued"] == 1
    assert naukri["total"] == 6 and naukri["states"]["APPLIED"] == 3
    assert (insta["applied_total"], insta["failed"], insta["filtered_out"]) == (1, 1, 1)
    # Every configured portal is listed (zero counts too); most applied first.
    assert by["lever"]["applied_total"] == 0 and body["portals"][0]["platform"] == "naukri"
    totals = body["totals"]
    assert totals["platform"] == "all" and totals["applied_total"] == 4 and totals["applied_today"] == 2
    assert totals["applied_7d"] == 3 and totals["total"] == 9
    daily = body["daily"]
    assert len(daily) == 14 and daily[-1]["applied"] == 2
    assert daily[-1]["by_platform"] == {"instahyre": 1, "naukri": 1}
    assert sum(d["applied"] for d in daily) == 3  # the 20-day-old one is outside the window
    assert [d["date"] for d in daily] == sorted(d["date"] for d in daily)

    short = (await async_client.get(f"{BASE}/applications/summary", params={"days": 1},
                                    headers=phase2_auth)).json()
    assert len(short["daily"]) == 1 and short["totals"]["applied_7d"] == 3  # 7-day KPI is independent
    for days in (0, 91, "x"):
        bad = await async_client.get(f"{BASE}/applications/summary", params={"days": days}, headers=phase2_auth)
        assert bad.status_code == 422


def test_summary_uses_ist_calendar_days():
    now = datetime(2026, 11, 27, 6, 0, tzinfo=UTC)  # 11:30 IST
    today, since = summary_window(14, now)
    assert today == date(2026, 11, 27) and since == datetime(2026, 11, 13, 18, 30, tzinfo=UTC)
    # 2026-11-26T19:00Z is 00:30 IST on the 27th: "today" in India although it is the 26th in UTC.
    summary = build_summary({"naukri": {"APPLIED": 2}},
                            [("naukri", date(2026, 11, 27), 1), ("naukri", date(2026, 11, 20), 1)],
                            ["naukri", "lever"], days=14, now=now)
    naukri = next(p for p in summary.portals if p.platform == "naukri")
    assert naukri.applied_today == 1 and naukri.applied_7d == 1  # the 20th is 7 local days back
    assert summary.daily[0].date == date(2026, 11, 14) and summary.daily[-1].date == today


async def test_detail_projects_receipt_without_paths_or_tokens(async_client, phase2_auth, store):
    receipt = {"source": "header_applied_after_submit", "ats": "greenhouse",
               "url": "https://boards.example.com/jobs/1?token=SECRET#frag",
               "screenshot": "/Users/someone/Library/automated-apply/receipts/naukri/1-receipt.png",
               "verified_at": "2026-11-27T05:00:00+00:00", "resume": "/Users/someone/cv/Resume_2026.pdf",
               "answers": [{"question": "Notice period?", "answer": "30 days", "source": "profile"},
                           {"question": "Resume", "answer": "/Users/someone/cv/Resume_2026.pdf",
                            "source": "resume_picker"},
                           {"question": "Why us?", "answer": "Love the product", "source": "bad source!"},
                           "garbage"],
               "internal": {"cookie": "abc"}}
    record = await add(store, "naukri", 1, S.APPLIED, receipt=receipt,
                       payload={"answers": [], "clicked_apply": True, "screenshot": receipt["screenshot"]})
    response = await async_client.get(f"{BASE}/applications/{record.id}", headers=phase2_auth)
    assert response.status_code == 200, response.text
    assert "/Users/" not in response.text and "SECRET" not in response.text and "cookie" not in response.text
    body = response.json()
    assert body["state"] == "APPLIED" and body["company_name"] == "Acme" and body["applied_at"]
    r = body["receipt"]
    assert r["verified"] is True and r["source"] == "header_applied_after_submit" and r["ats"] == "greenhouse"
    assert r["confirmation_url"] == "https://boards.example.com/jobs/1"
    assert r["has_screenshot"] is True and r["clicked_apply"] is True and r["resume"] == "Resume_2026.pdf"
    assert r["answers_source"] == "receipt"
    assert r["answers"] == [
        {"question": "Notice period?", "answer": "30 days", "source": "profile"},
        {"question": "Resume", "answer": "Resume_2026.pdf", "source": "resume_picker"},
        {"question": "Why us?", "answer": "Love the product", "source": None}]
    assert [e["to_state"] for e in body["timeline"]] == ["APPLYING", "APPLIED"]
    assert set(body["timeline"][0]) == {"from_state", "to_state", "event_type", "created_at"}


async def test_detail_falls_back_to_event_answers_and_404s(async_client, phase2_auth, store):
    record = await add(store, "naukri", 2, S.SUBMISSION_UNKNOWN, payload={
        "answers": [{"question": "CTC?", "answer": "9 LPA", "source": "screening_facts"}],
        "clicked_apply": True, "screenshot": None})
    body = (await async_client.get(f"{BASE}/applications/{record.id}", headers=phase2_auth)).json()
    r = body["receipt"]
    assert r["verified"] is False and r["source"] is None and r["has_screenshot"] is False
    assert r["answers_source"] == "event" and r["answers"][0]["answer"] == "9 LPA"
    discovered = await add(store, "naukri", 3)
    empty = (await async_client.get(f"{BASE}/applications/{discovered.id}", headers=phase2_auth)).json()
    assert empty["receipt"]["answers"] == [] and empty["receipt"]["clicked_apply"] is None
    assert empty["timeline"] == []
    for missing in ("00000000-0000-0000-0000-000000000000", "not-an-id"):
        assert (await async_client.get(f"{BASE}/applications/{missing}", headers=phase2_auth)).status_code == 404


async def test_list_search_matches_company_or_title(async_client, phase2_auth, store):
    await add(store, "naukri", 1, company="Razorpay", title="Backend Engineer")
    await add(store, "naukri", 2, company="Zepto", title="Python Developer")
    await add(store, "lever", 3, company="100% Remote Co", title="SDE")

    async def search(**params):
        response = await async_client.get(f"{BASE}/applications", params=params, headers=phase2_auth)
        assert response.status_code == 200, response.text
        return sorted(item["company_name"] for item in response.json()["items"])

    assert await search(q="razor") == ["Razorpay"]
    assert await search(q="PYTHON") == ["Zepto"]
    assert await search(q="  ") == ["100% Remote Co", "Razorpay", "Zepto"]  # blank = no filter
    assert await search(q="engineer", platform="lever") == []
    assert await search(q="100%") == ["100% Remote Co"]
    too_long = await async_client.get(f"{BASE}/applications", params={"q": "x" * 101}, headers=phase2_auth)
    assert too_long.status_code == 422


def test_safe_helpers():
    assert safe_text("see C:\\Users\\me\\cv.pdf and ~/x/y.txt") == "see cv.pdf and y.txt"
    assert safe_text({"a": 1}) is None and safe_text("   ") is None
    assert safe_url("javascript:alert(1)") is None and safe_url("https://u:p@host.io/a?b=1") == "https://host.io/a"
