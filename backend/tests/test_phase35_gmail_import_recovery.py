"""A reviewed lead must be persisted before the HTTP boundary reports success."""

from datetime import timedelta

import pytest
from sqlalchemy.exc import SQLAlchemyError

from backend.app.api.v1.integrations import read_service
from backend.app.core.config import Settings
from backend.app.dashboard.models import OwnerPreference
from backend.app.integrations.gmail.read_service import GmailReadService
from backend.app.main import app
from backend.app.models.connected_account import GmailReadAccount
from backend.app.models.discovery import now
from backend.app.repositories.job import JobRepository


@pytest.mark.parametrize("failure", [SQLAlchemyError, ValueError])
async def test_failed_import_is_http_conflict_and_retry_preserves_evidence(
    async_client, db_session, phase2_auth, monkeypatch, failure
):
    account = GmailReadAccount(
        account_email="fictional-import@example.com",
        google_subject="fictional-import-subject",
        connected_at=now(),
        status="connected",
    )
    db_session.add(account)
    await db_session.flush()
    account_id = account.id
    evidence_id = "a" * 32
    key = "gmail_msg:" + evidence_id
    url = "https://fictional-import.example/jobs/backend"
    db_session.add(OwnerPreference(key=key, value={
        "id": evidence_id,
        "account_id": str(account_id),
        "expires_at": (now() + timedelta(days=1)).isoformat(),
        "links": [url],
    }))
    await db_session.commit()
    service = GmailReadService(db_session, Settings(_env_file=None))
    app.dependency_overrides[read_service] = lambda: service
    path = f"/api/v1/integrations/gmail/accounts/{account_id}/evidence/{evidence_id}/import"
    data = {
        "job_url": url,
        "title": "Fictional Backend Engineer",
        "reviewed_job_evidence": True,
    }

    async def fail_write(*args, **kwargs):
        raise failure("fictional database write failure")

    try:
        with monkeypatch.context() as patch:
            patch.setattr(JobRepository, "save_or_update_job", fail_write)
            response = await async_client.post(path, headers=phase2_auth, json=data)
        assert response.status_code == 409, response.text
        assert response.json() == {"detail": "gmail_lead_import_failed"}
        await db_session.rollback()
        saved = await db_session.get(OwnerPreference, key)
        assert not saved.value.get("imported_job_ids")

        successful = await async_client.post(path, headers=phase2_auth, json=data)
        assert successful.status_code == 200, successful.text
        assert successful.json()["inserted_count"] == 1
        assert successful.json()["failed_count"] == 0
        assert len(successful.json()["job_ids"]) == 1
        repeated = await async_client.post(path, headers=phase2_auth, json=data)
        assert repeated.status_code == 200
        assert repeated.json()["inserted_count"] == 0
        assert repeated.json()["duplicate_count"] == 1
        assert repeated.json()["job_ids"] == successful.json()["job_ids"]
        await db_session.refresh(saved)
        assert saved.value["imported_job_ids"] == successful.json()["job_ids"]
    finally:
        app.dependency_overrides.pop(read_service, None)
