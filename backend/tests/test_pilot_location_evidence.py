"""Remote is not evidence of eligibility in the pilot's requested geography."""

import httpx
import pytest

from backend.app.operations.location_evidence import regional_access


@pytest.mark.parametrize("location,result", [
    ("Bengaluru, India", "listing_location_supported"),
    ("Hyderabad onsite", "listing_location_supported"),
    ("Remote worldwide", "listing_location_supported"),
    ("Remote (US only, US time zones; no visa sponsorship)", "restricted_location"),
    ("Remote (UT or ID residents only)", "restricted_location"),
    ("Remote", "requires_review"),
    ("Europe", "requires_review"),
    ("Global except India", "requires_review"),
    ("Indiana, USA", "requires_review"),
    ("Worldwide: US / Canada / Europe / UK / LATAM", "requires_review"),
    ("India only", "requires_review"),
    (None, "requires_review"),
])
def test_requested_geography_requires_listing_evidence(location, result):
    assert regional_access(location, ["India", "Bengaluru", "Hyderabad"]) == result


async def test_pilot_keeps_us_only_remote_jobs_out_of_relevant_count(db_session, monkeypatch):
    from backend.app.core.config import Settings
    from backend.app.db.session import get_session_factory
    from backend.app.operations.pilot import PilotRequest, run_pilot
    from backend.app.services.job_sources.direct_api import GreenhouseAdapter
    from backend.app.services.job_sources.factory import JobSourceFactory

    records = [{
        "id": number, "title": "Backend Engineer",
        "absolute_url": f"https://job-boards.greenhouse.io/fictional/jobs/{number}",
        "location": {"name": location}, "content": "Reported opening",
    } for number, location in enumerate([
        "Remote (US only, US time zones; no visa sponsorship)", "Bengaluru onsite",
    ], 1)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"jobs": records}))) as client:
        monkeypatch.setattr(JobSourceFactory, "get_adapter", lambda *a, **kw: GreenhouseAdapter(board_token="fictional", company_name="Fictional", http_client=client))
        report = await run_pilot(db_session, get_session_factory(), Settings(_env_file=None), PilotRequest(source="greenhouse", idempotency_key="regional-eligibility-test"))
    assert report["actual_jobs"] == 2
    assert report["relevant_jobs"] == 1
    assert report["companies"][0]["jobs"][0]["location"] == "Bengaluru onsite"
    assert report["location_review_jobs"][0]["regional_access"] == "restricted_location"
    assert report["candidate_matched_jobs"] == 0
