import uuid

import pytest
from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.models.company import Company
from backend.app.models.contact import Contact
from backend.app.models.contact_enrichment import ContactEvidence
from backend.app.models.discovery import now
from backend.app.models.job import Job
from backend.app.services.contact_enrichment.ranking import rank_contact
from backend.app.services.contact_enrichment.verification import (
    candidate_confidence_percent,
)
from backend.tests.contact_enrichment_fakes import URL


@pytest.fixture
async def records(db_session):
    company = Company(
        name="Fictional Startup",
        domain="fictional.example.com",
        metadata_={"employee_count": 12},
    )
    db_session.add(company)
    await db_session.flush()
    contact = Contact(
        company_id=company.id,
        full_name="Alex Fictional",
        role_title="CTO",
        linkedin_url=URL,
        last_checked_at=now(),
        email="alex@fictional.example.com",
        email_status="provider_reported",
        metadata_={"evidence_strength": "strong"},
    )
    job = Job(
        company_id=company.id,
        title="Software Engineer",
        job_url="https://fictional.example.com/job/1",
        source_platform="manual",
    )
    db_session.add_all([contact, job])
    await db_session.commit()
    return company, contact, job


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/api/v1/contact-enrichment/providers"),
        ("POST", "/api/v1/companies/{id}/contacts/preview"),
        ("POST", "/api/v1/companies/{id}/contacts/enrich"),
        ("GET", "/api/v1/contact-enrichment/runs/{id}"),
        ("GET", "/api/v1/companies/{id}/contacts"),
        ("GET", "/api/v1/contacts/{id}"),
        ("PATCH", "/api/v1/contacts/{id}"),
        ("GET", "/api/v1/jobs/{id}/recommended-contacts"),
    ],
)
@pytest.mark.parametrize("token", [None, "wrong"])
async def test_all_endpoints_require_bearer(
    async_client, phase2_auth, method, path, token
):
    response = await async_client.request(
        method,
        path.format(id=uuid.uuid4()),
        headers={} if token is None else {"Authorization": "Bearer " + token},
        json={},
    )
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


async def test_fail_closed_when_unconfigured(async_client, monkeypatch):
    monkeypatch.setenv("JOB_AGENT_API_TOKEN", "")
    get_settings.cache_clear()
    response = await async_client.get("/api/v1/contact-enrichment/providers")
    assert response.status_code == 503
    get_settings.cache_clear()


async def test_provider_status_never_exposes_credentials(async_client, phase2_auth):
    response = await async_client.get(
        "/api/v1/contact-enrichment/providers", headers=phase2_auth
    )
    assert response.status_code == 200
    for provider in response.json()["providers"]:
        assert provider["configuration_status"] == "not_configured"
        assert provider["live_verification"] == "not_checked"
        assert provider["budget"]["provider_balance"] is None
    assert "API_KEY" not in response.text


async def test_preview_enrich_run_list_detail_recommendation(
    async_client, phase2_auth, records
):
    company, contact, job = records
    base = f"/api/v1/companies/{company.id}/contacts"
    response = await async_client.post(
        base + "/preview", headers=phase2_auth, json={"allow_paid": False}
    )
    assert response.status_code == 200 and response.json()["billable_calls"] == 0
    response = await async_client.post(
        base + "/enrich",
        headers=phase2_auth,
        json={"idempotency_key": "api-fictional-1"},
    )
    assert response.status_code == 200
    run = response.json()
    assert run["state"] == "completed" and run["counts"]["outbound_messages_sent"] == 0
    response = await async_client.get(
        "/api/v1/contact-enrichment/runs/" + run["id"], headers=phase2_auth
    )
    assert response.status_code == 200 and response.json()["id"] == run["id"]
    response = await async_client.get(
        base,
        headers=phase2_auth,
        params={"has_linkedin": True, "email_status": "provider_reported", "limit": 1},
    )
    assert response.status_code == 200 and response.json()["total"] == 1
    response = await async_client.get(
        f"/api/v1/contacts/{contact.id}", headers=phase2_auth
    )
    assert (
        response.status_code == 200
        and response.json()["manual_linkedin_available"] is True
    )
    assert response.json()["email_send_ready"] is False
    response = await async_client.get(
        f"/api/v1/jobs/{job.id}/recommended-contacts", headers=phase2_auth
    )
    assert (
        response.status_code == 200
        and response.json()["contacts"][0]["priority"] == "high"
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"max_people": 26},
        {"providers": ["unknown"]},
        {"providers": ["apollo", "apollo"]},
        {"target_roles": ["x" * 256]},
        {"target_roles": ["cto"] * 21},
        {"url": "http://169.254.169.254/latest"},
        {"idempotency_key": "https://evil.com"},
    ],
)
async def test_invalid_and_ssrf_payloads(async_client, phase2_auth, records, payload):
    company, _, _ = records
    response = await async_client.post(
        f"/api/v1/companies/{company.id}/contacts/enrich",
        headers=phase2_auth,
        json=payload,
    )
    assert response.status_code == 422


async def test_oversized_payload(async_client, phase2_auth, records):
    company, _, _ = records
    response = await async_client.post(
        f"/api/v1/companies/{company.id}/contacts/enrich",
        headers=phase2_auth,
        content="x" * 1048577,
    )
    assert response.status_code == 413


async def test_company_not_found_and_idempotency_conflict(
    async_client, phase2_auth, records
):
    response = await async_client.post(
        f"/api/v1/companies/{uuid.uuid4()}/contacts/enrich",
        headers=phase2_auth,
        json={},
    )
    assert response.status_code == 404
    company, _, _ = records
    path = f"/api/v1/companies/{company.id}/contacts/enrich"
    assert (
        await async_client.post(
            path, headers=phase2_auth, json={"idempotency_key": "conflict"}
        )
    ).status_code == 200
    response = await async_client.post(
        path, headers=phase2_auth, json={"idempotency_key": "conflict", "max_people": 2}
    )
    assert response.status_code == 409


async def test_suppression_correction_persisted_and_excluded_from_recommendations(
    async_client, phase2_auth, records, db_session
):
    company, contact, job = records
    response = await async_client.patch(
        f"/api/v1/contacts/{contact.id}",
        headers=phase2_auth,
        json={
            "full_name": "Alex Corrected",
            "do_not_contact": True,
            "suppression_reason": "Opt out",
            "human_review_notes": "Do not contact",
        },
    )
    assert response.status_code == 200 and response.json()["priority"] == "suppressed"
    assert response.json()["manual_linkedin_available"] is False
    response = await async_client.get(
        f"/api/v1/jobs/{job.id}/recommended-contacts", headers=phase2_auth
    )
    assert response.json()["contacts"] == []
    response = await async_client.get(
        f"/api/v1/companies/{company.id}/contacts",
        headers=phase2_auth,
        params={"suppressed": True},
    )
    assert response.json()["total"] == 1
    await db_session.refresh(contact)
    assert contact.human_corrected and contact.do_not_contact
    evidence = await db_session.scalar(
        select(ContactEvidence).where(ContactEvidence.contact_id == contact.id)
    )
    assert evidence.provenance["previous_values"]["full_name"] == "Alex Fictional"


@pytest.mark.parametrize("status", ["verified", "garbage"])
async def test_cannot_arbitrarily_verify_email(
    async_client, phase2_auth, records, status
):
    _, contact, _ = records
    response = await async_client.patch(
        f"/api/v1/contacts/{contact.id}",
        headers=phase2_auth,
        json={"email_status": status},
    )
    assert response.status_code == 422


async def test_supported_verification_record_required(
    async_client, phase2_auth, records, db_session
):
    from datetime import timedelta

    company, contact, _ = records
    evidence = ContactEvidence(
        company_id=company.id,
        contact_id=contact.id,
        source="manual",
        evidence_type="mailbox_verification",
        strength="strong",
        expires_at=now() + timedelta(days=10),
        user_confirmed=True,
        provenance={
            "email": contact.email,
            "result": "deliverable",
            "method": "owner_confirmation",
        },
    )
    db_session.add(evidence)
    await db_session.commit()
    response = await async_client.patch(
        f"/api/v1/contacts/{contact.id}",
        headers=phase2_auth,
        json={"email_status": "verified", "verification_evidence_id": str(evidence.id)},
    )
    assert response.status_code == 200
    assert (
        response.json()["email_status"] == "verified"
        and response.json()["email_send_ready"] is True
    )


@pytest.mark.parametrize("size", [12, 1000, None])
async def test_ranking_company_context_and_mailbox_semantics(records, size):
    company, contact, job = records
    company.metadata_ = {"employee_count": size}
    cto = rank_contact(contact, company, job)
    contact.role_title = "Technical Recruiter"
    recruiter = rank_contact(contact, company, job)
    assert not cto["email_send_ready"] and cto["manual_linkedin_available"]
    if size == 1000:
        assert recruiter["ordering_score"] > cto["ordering_score"]
    contact.role_title = "University Recruiter"
    job.title = "Software Engineering Intern"
    assert (
        "Campus recruiting role fits internship hiring"
        in rank_contact(contact, company, job)["reasons"]
    )


def test_confidence_boundary_conversion():
    assert candidate_confidence_percent(0.4) == 40
    with pytest.raises(ValueError):
        candidate_confidence_percent(40)
