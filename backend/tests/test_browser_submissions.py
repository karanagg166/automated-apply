"""Real browser dispatch to a fictional employer; no real application endpoints."""

import hashlib
import json
import time
from datetime import timedelta
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport

from backend.app.browser.owner_approval import approval_header
from backend.app.browser.runner import browser, origin
from backend.app.browser.submission_models import (
    BrowserExecutionBase,
    BrowserSubmissionGrant,
)
from backend.app.core.config import get_settings
from backend.app.dashboard.models import PrivateResume
from backend.app.db.session import get_db_session
from backend.app.main import app
from backend.app.models.application_answer import CandidateResource
from backend.tests.browser_employers import employer_site


@pytest_asyncio.fixture(autouse=True)
async def execution_tables(db_session):
    async with db_session.bind.begin() as connection:
        await connection.run_sync(BrowserExecutionBase.metadata.create_all)
    yield
    await db_session.rollback()
    async with db_session.bind.begin() as connection:
        await connection.run_sync(BrowserExecutionBase.metadata.drop_all)


@pytest_asyncio.fixture
async def submission_api(
    db_session, phase2_profile, phase2_auth, monkeypatch, tmp_path
):
    with employer_site() as (base, writes):
        for name, value in {
            "BROWSER_ASSISTANT_ENABLED": "true",
            "BROWSER_MOCK_SUBMISSION_ENABLED": "true",
            "BROWSER_OWNER_APPROVAL_KEY": "fictional-owner-approval-separate-from-cli-token",  # pragma: allowlist secret — fixture only
            "BROWSER_ALLOWED_ORIGINS": '["' + origin(base) + '"]',
            "BROWSER_PROFILE_ROOT": str(tmp_path / "profiles"),
            "BROWSER_CHANNEL": "chromium",
            "BROWSER_HEADLESS": "true",
            "RESUME_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        }.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()
        resume_id = uuid4()
        resource = CandidateResource(
            candidate_profile_id=phase2_profile.id,
            resource_type="resume",
            label="Approved fixture PDF",
            url="private-resume:" + str(resume_id),
            source_type="private_upload",
            user_confirmed=True,
            is_primary=True,
        )
        db_session.add(resource)
        await db_session.flush()
        raw = b"%PDF-1.4\nfictional-content"
        db_session.add(
            PrivateResume(
                id=resume_id,
                resource_id=resource.id,
                label="Approved fixture PDF",
                confirmed=True,
                ciphertext=Fernet(
                    get_settings().RESUME_ENCRYPTION_KEY.get_secret_value().encode()
                ).encrypt(raw),
                sha256=hashlib.sha256(raw).hexdigest(),
            )
        )
        await db_session.commit()

        async def dependency():
            try:
                yield db_session
                await db_session.commit()
            except BaseException:
                await db_session.rollback()
                raise

        app.dependency_overrides[get_db_session] = dependency

        # MockTransport bridges only independent receipt GETs to this loopback server. No live provider HTTP.
        async def receipt_http(request):
            assert str(request.url).startswith(base + "/mock/receipts/")
            attempt_id = request.url.path.rsplit("/", 1)[1]
            receipt = writes.receipts.get(attempt_id)
            if writes.mode == "missing":
                receipt = None
            elif receipt and writes.mode == "wrong":
                receipt = {**receipt, "payload_digest": "0" * 64}
            return httpx.Response(200 if receipt else 404, json=receipt or {})

        original_client = httpx.AsyncClient

        def local_receipt_client(*args, **kwargs):
            return original_client(
                *args, transport=httpx.MockTransport(receipt_http), **kwargs
            )

        monkeypatch.setattr(
            "backend.app.browser.adapters.httpx.AsyncClient", local_receipt_client
        )
        async with original_client(
            transport=ASGITransport(app=app),
            base_url="http://test",
            headers=phase2_auth,
        ) as client:
            yield client, base, writes, db_session
        for key in list(browser.sessions):
            await browser.close(key)
        browser.locks.clear()
        app.dependency_overrides.pop(get_db_session, None)
        get_settings.cache_clear()


async def ready(bundle):
    client, base, _, _ = bundle
    response = await client.post(
        "/api/v1/browser-applications",
        json={
            "application_url": base + "/mock/apply",
            "company_name": "Example Circuit",
            "job_title": "Backend Engineer",
            "idempotency_key": "mock-packet-001",
        },
    )
    assert response.status_code == 200, response.text
    packet = response.json()
    route = "/api/v1/browser-applications/" + packet["id"]
    response = await client.post(
        route + "/open",
        json={
            "expected_revision": packet["revision"],
            "approve_dedicated_profile": True,
            "confirm_destination_permission": True,
        },
    )
    assert response.status_code == 200, response.text
    response = await client.post(
        route + "/actions",
        json={"expected_revision": packet["revision"], "action": "analyze"},
    )
    assert response.status_code == 200, response.text
    packet = response.json()["packet"]
    response = await client.post(
        route + "/actions",
        json={
            "expected_revision": packet["revision"],
            "action": "fill",
            "confirm_page_context": True,
            "confirm_reviewed_values": True,
        },
    )
    assert response.status_code == 200, response.text
    page = browser.sessions[packet["id"]].page
    await page.locator(
        "[type=checkbox]"
    ).check()  # Explicit fictional owner consent, never agent inference.
    return route, packet


async def grant(bundle, route, packet):
    client = bundle[0]
    response = await client.post(
        route + "/submission-preview",
        json={"expected_revision": packet["revision"], "confirm_page_context": True},
    )
    assert response.status_code == 200, response.text
    preview = response.json()
    body = {
        "expected_revision": packet["revision"],
        "preview_digest": preview["preview_digest"],
        "confirm_exact_application": True,
        "reviewed_consent_ids": [
            c["consent_id"] for c in preview["consents"] if c["checked"]
        ],
    }
    raw = json.dumps(body).encode()
    proof = approval_header(
        get_settings().BROWSER_OWNER_APPROVAL_KEY.get_secret_value(),
        route + "/authorize-submission",
        raw,
        nonce=uuid4().hex,
        timestamp=int(time.time()),
    )
    response = await client.post(
        route + "/authorize-submission",
        content=raw,
        headers={"Content-Type": "application/json", "X-Browser-Owner-Approval": proof},
    )
    assert response.status_code == 200, response.text
    return response.json(), preview


def payload(packet, authorization):
    return {
        "expected_revision": packet["revision"],
        "grant_id": authorization["grant_id"],
        "grant_token": authorization["grant_token"],
        "idempotency_key": "mock-submit-001",
    }


@pytest.mark.asyncio
async def test_exact_grant_dispatch_independent_receipt_and_idempotency(submission_api):
    client, _, writes, _ = submission_api
    route, packet = await ready(submission_api)
    authorization, preview = await grant(submission_api, route, packet)
    assert "grant_token" not in str(preview)
    response = await client.post(route + "/submit", json=payload(packet, authorization))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["state"] == "verified"
    assert result["receipt"]["receipt_reference"].startswith("MOCK-")
    assert writes == ["/mock/applications"]
    replay = await client.post(route + "/submit", json=payload(packet, authorization))
    assert replay.json()["attempt_id"] == result["attempt_id"]
    assert writes == ["/mock/applications"]
    state = (await client.get(route)).json()
    assert state["packet"]["lifecycle_state"] == "provider_confirmed_submitted"
    assert state["packet"]["tracking_state"] == "applied_verified"
    assert state["execution"]["adapter"] == "local_mock_v1"
    assert state["real_employer_submission_enabled"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["missing", "wrong"])
async def test_unknown_outcome_recovers_without_clicking_again(submission_api, mode):
    client, _, writes, _ = submission_api
    route, packet = await ready(submission_api)
    authorization, _ = await grant(submission_api, route, packet)
    writes.mode = mode
    response = await client.post(route + "/submit", json=payload(packet, authorization))
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "unknown"
    assert (await client.get(route)).json()["packet"][
        "lifecycle_state"
    ] == "submission_unknown"
    await browser.close(packet["id"])
    assert "do not resubmit" in (await client.get(route)).json()["recovery"]
    other = payload(packet, authorization)
    other["idempotency_key"] = "another-submit-key"
    assert (await client.post(route + "/submit", json=other)).status_code == 409
    writes.mode = "valid"
    recovered = await client.post(route + "/recover-submission")
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["state"] == "verified"
    assert writes == ["/mock/applications"]


@pytest.mark.asyncio
async def test_missing_consent_or_changed_values_never_dispatch(submission_api):
    client, _, writes, _ = submission_api
    route, packet = await ready(submission_api)
    page = browser.sessions[packet["id"]].page
    await page.evaluate(
        """() => {const e=document.createElement('input');e.name='unreviewed_file';e.type='file';e.hidden=true;document.forms[0].appendChild(e)}"""
    )
    hidden_upload = await client.post(
        route + "/submission-preview",
        json={"expected_revision": packet["revision"], "confirm_page_context": True},
    )
    assert hidden_upload.status_code == 409
    await page.locator("[name=unreviewed_file]").evaluate("(e)=>e.remove()")
    await page.locator("[type=checkbox]").uncheck()
    response = await client.post(
        route + "/submission-preview",
        json={"expected_revision": packet["revision"], "confirm_page_context": True},
    )
    assert response.status_code == 409
    await page.locator("[type=checkbox]").check()
    authorization, _ = await grant(submission_api, route, packet)
    await page.locator("[name=email]").fill("someone-else@example.com")
    assert (
        await client.post(route + "/submit", json=payload(packet, authorization))
    ).status_code == 409
    assert writes == []


@pytest.mark.asyncio
async def test_expired_or_revoked_or_wrong_owner_grant_never_dispatch(submission_api):
    client, _, writes, session = submission_api
    route, packet = await ready(submission_api)
    authorization, _ = await grant(submission_api, route, packet)
    record = await session.get(BrowserSubmissionGrant, UUID(authorization["grant_id"]))
    record.expires_at = record.created_at - timedelta(seconds=1)
    await session.commit()
    assert (
        await client.post(route + "/submit", json=payload(packet, authorization))
    ).status_code == 403
    authorization, _ = await grant(submission_api, route, packet)
    wrong = payload(packet, authorization)
    wrong["grant_token"] = "not-the-owner-grant"
    assert (await client.post(route + "/submit", json=wrong)).status_code == 403
    response = await client.post(
        route + "/actions",
        json={"expected_revision": packet["revision"], "action": "cancel"},
    )
    assert response.status_code == 200
    assert (
        await client.post(route + "/submit", json=payload(packet, authorization))
    ).status_code == 403
    assert writes == []


@pytest.mark.asyncio
async def test_process_interruption_after_reservation_never_replays(
    submission_api, monkeypatch
):
    import asyncio

    from backend.app.browser.submissions import now, reconcile_expired

    client, _, writes, session = submission_api
    route, packet = await ready(submission_api)
    authorization, _ = await grant(submission_api, route, packet)

    async def interrupted(*args):
        raise asyncio.CancelledError()

    monkeypatch.setattr(browser.sessions[packet["id"]], "submit_mock", interrupted)
    from backend.app.browser.submission_contracts import SubmitApproved
    from backend.app.browser.submissions import submit

    with pytest.raises(asyncio.CancelledError):
        await submit(
            session,
            UUID(packet["id"]),
            SubmitApproved.model_validate(payload(packet, authorization)),
        )
    await browser.close(packet["id"])
    assert writes == []
    assert await reconcile_expired(session, as_of=now() + timedelta(seconds=60)) == 1
    state = (await client.get(route)).json()
    assert state["packet"]["lifecycle_state"] == "submission_unknown"
    assert state["execution"]["diagnostic"] == "dispatch_lease_expired_no_replay"
    response = await client.post(route + "/submit", json=payload(packet, authorization))
    assert response.status_code == 200
    assert response.json()["state"] == "unknown"
    assert writes == []


@pytest.mark.asyncio
async def test_consent_review_and_private_token_exposure_are_separate_gates(
    submission_api,
):
    client, _, writes, _ = submission_api
    route, packet = await ready(submission_api)
    preview = (
        await client.post(
            route + "/submission-preview",
            json={
                "expected_revision": packet["revision"],
                "confirm_page_context": True,
            },
        )
    ).json()
    wrong_consent_body = {
        "expected_revision": packet["revision"],
        "preview_digest": preview["preview_digest"],
        "confirm_exact_application": True,
        "reviewed_consent_ids": [],
    }
    raw_body = json.dumps(wrong_consent_body).encode()
    owner_proof = approval_header(
        get_settings().BROWSER_OWNER_APPROVAL_KEY.get_secret_value(),
        route + "/authorize-submission",
        raw_body,
        nonce=uuid4().hex,
        timestamp=int(time.time()),
    )
    missing = await client.post(
        route + "/authorize-submission",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Browser-Owner-Approval": owner_proof,
        },
    )
    assert missing.status_code == 422
    authorization, _ = await grant(submission_api, route, packet)
    state = await client.get(route)
    assert authorization["grant_token"] not in state.text
    expired_owner = await client.post(
        route + "/submit",
        headers={"Authorization": "Bearer expired"},
        json=payload(packet, authorization),
    )
    assert expired_owner.status_code == 401
    assert writes == []


@pytest.mark.asyncio
async def test_owner_proof_cannot_be_replayed_or_applied_to_a_different_body(
    submission_api,
):
    client = submission_api[0]
    route, packet = await ready(submission_api)
    preview = (
        await client.post(
            route + "/submission-preview",
            json={
                "expected_revision": packet["revision"],
                "confirm_page_context": True,
            },
        )
    ).json()
    body = {
        "expected_revision": packet["revision"],
        "preview_digest": preview["preview_digest"],
        "confirm_exact_application": True,
        "reviewed_consent_ids": [
            c["consent_id"] for c in preview["consents"] if c["checked"]
        ],
    }
    raw = json.dumps(body).encode()
    proof = approval_header(
        get_settings().BROWSER_OWNER_APPROVAL_KEY.get_secret_value(),
        route + "/authorize-submission",
        raw,
        nonce=uuid4().hex,
        timestamp=int(time.time()),
    )
    headers = {"Content-Type": "application/json", "X-Browser-Owner-Approval": proof}
    swapped = json.dumps({**body, "reviewed_consent_ids": []}).encode()
    assert (
        await client.post(
            route + "/authorize-submission", content=swapped, headers=headers
        )
    ).status_code == 403
    response = await client.post(
        route + "/authorize-submission", content=raw, headers=headers
    )
    assert response.status_code == 200, response.text
    assert (
        await client.post(route + "/authorize-submission", content=raw, headers=headers)
    ).status_code == 403


@pytest.mark.asyncio
async def test_outgoing_body_changes_after_owner_review_are_blocked(submission_api):
    client, _, writes, _ = submission_api
    route, packet = await ready(submission_api)
    authorization, _ = await grant(submission_api, route, packet)
    await browser.sessions[packet["id"]].page.evaluate("""() => document.forms[0].addEventListener('submit', () => {
        document.querySelector('[name=email]').value = 'unapproved@example.com';
    })""")
    response = await client.post(route + "/submit", json=payload(packet, authorization))
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "unknown"
    assert writes == []
