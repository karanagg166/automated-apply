"""Authenticated local preview/create/edit/review lifecycle; provider IDs never invented."""

import pytest


@pytest.mark.asyncio
async def test_outreach_api_lifecycle(async_client, phase2_auth, outreach_target):
    contact, _, job, _ = outreach_target
    data = {"contact_id": str(contact.id), "job_id": str(job.id), "use_llm": False}
    path = "/api/v1/outreach/drafts"
    assert (await async_client.post(path + "/preview", json=data)).status_code == 401
    preview = await async_client.post(path + "/preview", headers=phase2_auth, json=data)
    assert preview.status_code == 200 and preview.json()["status"] == "draft_ready"
    assert (await async_client.get(path, headers=phase2_auth)).json()["total"] == 0
    created = await async_client.post(path, headers=phase2_auth, json=data)
    assert created.status_code == 200, created.text
    draft = created.json()
    draft_path = path + "/" + draft["id"]
    assert (await async_client.get(draft_path, headers=phase2_auth)).status_code == 200
    assert (
        await async_client.get(draft_path + "/eligibility", headers=phase2_auth)
    ).json()["eligible_for_approval"]
    approved = await async_client.post(
        draft_path + "/approve",
        headers=phase2_auth,
        json={"expected_revision": draft["draft_revision"]},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["eligibility"]["approval_current"]
    assert approved.json()["gmail_message_id"] is None
    stale = await async_client.patch(
        draft_path, headers=phase2_auth, json={"expected_revision": 1, "body": "stale"}
    )
    assert stale.status_code == 409
    assert (
        await async_client.get(path + "?limit=0", headers=phase2_auth)
    ).status_code == 422
    assert (
        await async_client.post("/api/v1/outreach/send", headers=phase2_auth)
    ).status_code == 404


@pytest.mark.asyncio
async def test_no_caller_supplied_approval_or_provider_ids(
    async_client, phase2_auth, outreach_target
):
    for field in (
        "gmail_message_id",
        "gmail_draft_id",
        "approval_status",
        "created_via",
    ):
        result = await async_client.post(
            "/api/v1/outreach/drafts",
            headers=phase2_auth,
            json={"contact_id": str(outreach_target[0].id), field: "forged"},
        )
        assert result.status_code == 422
        assert "forged" not in result.text


@pytest.mark.asyncio
async def test_saved_read_api_service_consistency(
    async_client, phase2_auth, outreach_target, db_session
):
    from backend.app.services.saved_data import SavedDataService

    contact, company, job, _ = outreach_target
    expected = await SavedDataService(db_session).job(job.id)
    actual = await async_client.get(f"/api/v1/jobs/{job.id}", headers=phase2_auth)
    assert actual.status_code == 200
    assert {
        k: v for k, v in actual.json().items() if k not in {"created_at", "updated_at"}
    } == {k: v for k, v in expected.items() if k not in {"created_at", "updated_at"}}
    match = await async_client.get(f"/api/v1/jobs/{job.id}/match", headers=phase2_auth)
    assert match.status_code == 200
    contacts = await async_client.get(
        f"/api/v1/companies/{company.id}/recommended-contacts", headers=phase2_auth
    )
    assert contacts.status_code == 200 and contacts.json()[0]["id"] == str(contact.id)
