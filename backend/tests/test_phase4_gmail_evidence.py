"""Selected fictional message evidence remains tentative and account attributed."""

import base64
from datetime import timedelta

import pytest

from backend.app.core.config import Settings
from backend.app.dashboard.models import OwnerPreference
from backend.app.integrations.gmail.read_client import content_evidence
from backend.app.integrations.gmail.read_service import GmailReadService, LeadImport
from backend.app.models.connected_account import GmailReadAccount
from backend.app.models.discovery import now


@pytest.mark.parametrize("text,signal", [
    ("An interview invitation for your application", "possible_interview"),
    ("Unfortunately we are not moving forward", "possible_rejection"),
    ("We received your application", "possible_acknowledgment"),
    ("Job alert: Python opening", "possible_job_lead"),
    ("Our recruiter would like to discuss an opportunity", "possible_recruiter_response"),
    ("Please provide your available interview times", "possible_follow_up_request"),
    ("Your application status is under review", "possible_status_update"),
])
def test_body_signals_are_never_employer_status_confirmation(text, signal):
    result = content_evidence({"mimeType": "text/plain", "body": {
        "data": base64.urlsafe_b64encode(text.encode()).decode(),
    }})
    assert signal in result["signals"]
    assert result["signal_basis"] == "selected_message_body_keywords"
    assert result["status_confirmed"] is result["submission_confirmed"] is False
    assert text not in str(result)


def test_subject_and_hidden_html_never_establish_status_or_outreach():
    result = content_evidence({"mimeType": "text/html", "headers": [
        {"name": "Subject", "value": "Interview invitation: application accepted"},
    ], "body": {"data": base64.urlsafe_b64encode(b'<script>application status under review</script><p>Hello</p>').decode()}})
    assert result["signals"] == []
    assert result["status_confirmed"] is False


async def test_multi_link_message_tracks_only_imported_url_and_preserves_account(db_session):
    account = GmailReadAccount(account_email="fixture@example.com", google_subject="fixture-subject", status="connected", connected_at=now())
    second = GmailReadAccount(account_email="second@example.com", google_subject="second-subject", status="connected", connected_at=now())
    db_session.add_all([account, second])
    await db_session.flush()
    account_id, second_id = account.id, second.id
    first_url, other_url = "https://fictional.example/jobs/one", "https://fictional.example/jobs/two"
    key = "gmail_msg:" + "b" * 32
    row = OwnerPreference(key=key, value={
        "id": "b" * 32, "account_id": str(account_id), "expires_at": (now() + timedelta(days=1)).isoformat(),
        "links": [first_url, other_url], "message_id": "fixture-message", "thread_id": "fixture-thread",
    })
    db_session.add(row)
    await db_session.commit()
    service = GmailReadService(db_session, Settings(_env_file=None))
    data = LeadImport(job_url=first_url, title="Fictional Engineer", reviewed_job_evidence=True)
    result = await service.import_lead(account_id, "b" * 32, data)
    assert result.inserted_count == 1
    leads = {item["url"]: item for item in await service.leads(account_id)}
    assert leads[first_url]["import_state"] == "imported"
    assert leads[first_url]["imported_job_ids"] == result.job_ids
    assert leads[other_url]["import_state"] == "not_imported"
    assert not leads[other_url]["imported_job_ids"]
    assert not await service.leads(second_id)
    replay = await service.import_lead(account_id, "b" * 32, data)
    assert replay.duplicate_count == 1 and replay.job_ids == result.job_ids
    # Resolving one URL must not erase an unrelated historical import's ambiguity.
    row.value = {**row.value, "imported_job_ids": result.job_ids + ["historical-unmapped-job"]}
    await db_session.commit()
    leads = {item["url"]: item for item in await service.leads(account_id)}
    assert leads[first_url]["import_state"] == "imported"
    assert leads[other_url]["import_state"] == "legacy_message_import_unknown"
    # Historical message-wide flags cannot identify which URL was imported.
    row.value = {**row.value, "imported_leads": {}}
    await db_session.commit()
    assert {v["import_state"] for v in await service.leads(account_id)} == {"legacy_message_import_unknown"}
