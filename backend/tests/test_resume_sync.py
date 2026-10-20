"""Fictional in-memory PDFs only. No real Drive, model or candidate fixture."""

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from backend.app.core.config import Settings, get_settings
from backend.app.dashboard.models import Notification, OwnerPreference, PrivateResume
from backend.app.models.application_answer import (
    ApplicationAnswerDraft,
    CandidateResource,
)
from backend.app.repositories.candidate_profile import CandidateProfileRepository
from backend.app.resume_sync.download import DownloadedPDF
from backend.app.resume_sync.download_worker import DownloadError
from backend.app.resume_sync.models import (
    DriveResumeVersion,
    ResumeDriveSource,
    ResumeProfileReview,
)
from backend.app.resume_sync.review import approve_version, review_changes
from backend.app.resume_sync.schemas import ApproveResume, SourceSettings
from backend.app.resume_sync.service import ResumeSyncService
from backend.app.resume_sync.source import canonical_source
from backend.app.resume_sync.store import save_source, status
from backend.app.schemas.candidate_profile import (
    CandidateProfileCreate,
)
from backend.tests.test_phase7_dashboard import pdf_bytes

FILE_ID = "fictional_drive_resume_001"
URL = f"https://drive.google.com/file/d/{FILE_ID}/view?usp=drivesdk"


@pytest.fixture
def resume_settings(monkeypatch):
    monkeypatch.setenv("CANDIDATE_RESUME_DRIVE_URL", URL)
    monkeypatch.setenv("CANDIDATE_RESUME_DRIVE_FILE_ID", FILE_ID)
    monkeypatch.setenv("RESUME_ENCRYPTION_KEY", Fernet.generate_key().decode())
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


class FakeDrive:
    def __init__(self):
        self.raw = pdf_bytes("Alex Sample Python Docker")
        self.calls = 0
        self.error = None
        self.metadata = datetime(2026, 1, 1, tzinfo=timezone.utc)

    async def __call__(self, file_id):
        assert file_id in {FILE_ID, "fictional_drive_resume_002"}
        self.calls += 1
        if self.error:
            raise DownloadError(self.error)
        return DownloadedPDF(self.raw, "fictional_resume.pdf", self.metadata, '"version-1"')


@pytest_asyncio.fixture
async def resume_bundle(db_session, resume_settings):
    db_session.add(OwnerPreference(key="notifications", value={"quiet_start": 0, "quiet_end": 0}))
    await db_session.commit()
    drive = FakeDrive()
    return ResumeSyncService(db_session, resume_settings, drive), drive, resume_settings


async def approval(session, settings, version_id, **overrides):
    review = await review_changes(session, settings, version_id)
    values = dict(owner_confirmed=True, primary=True, expected_generation=review.expected_generation,
                  expected_profile_version=review.expected_profile_version,
                  profile=review.proposed_profile or CandidateProfileCreate(full_name="Alex Sample", email="alex@example.org"))
    values.update(overrides)
    return await approve_version(session, settings, version_id, ApproveResume(**values))


async def test_initial_sync_is_encrypted_pending_and_not_verified(resume_bundle, db_session, phase2_profile):
    service, drive, settings = resume_bundle
    result = await service.sync(1)
    await db_session.commit()
    state = result["state"]
    assert state.connected and state.latest.review_status == "pending"
    assert state.active is None and state.pending_changes
    assert state.latest.file_id == FILE_ID and state.latest.canonical_url == URL
    assert state.latest.sha256 == hashlib.sha256(drive.raw).hexdigest()
    stored = await db_session.get(PrivateResume, state.latest.private_resume_id)
    assert not stored.confirmed and stored.resource_id is None and stored.ciphertext != drive.raw
    encryption = Fernet(settings.RESUME_ENCRYPTION_KEY.get_secret_value().encode())
    assert encryption.decrypt(stored.ciphertext) == drive.raw
    review = await db_session.scalar(select(ResumeProfileReview))
    assert b"Alex" not in review.review_ciphertext
    assert (await CandidateProfileRepository(db_session).get_primary_profile()).version == 1
    assert phase2_profile.verified_skills == ["Python", "FastAPI"]
    assert await db_session.scalar(select(func.count()).select_from(Notification)) == 1


async def test_unchanged_checks_metadata_checksum_without_reprocessing(resume_bundle, db_session):
    service, drive, _ = resume_bundle
    first = await service.sync(1)
    await db_session.commit()
    async def must_not_extract(_):
        pytest.fail("Unchanged PDF must not be reprocessed")
    service.extractor = must_not_extract
    drive.metadata += timedelta(days=1)
    second = await service.sync(1)
    await db_session.commit()
    assert second["outcome"] == "unchanged" and drive.calls == 2
    assert first["state"].latest.id == second["state"].latest.id
    assert second["state"].last_checked_at >= first["state"].last_checked_at
    assert await db_session.scalar(select(func.count()).select_from(PrivateResume)) == 1
    assert await db_session.scalar(select(func.count()).select_from(DriveResumeVersion)) == 1


async def test_changed_pdf_preserves_active_version_and_requires_review(resume_bundle, db_session, phase2_profile):
    service, drive, settings = resume_bundle
    first = (await service.sync(1))["state"]
    old = first.latest
    accepted = await approval(db_session, settings, old.id)
    await db_session.commit()
    old_bytes = drive.raw
    drive.raw = pdf_bytes("Alex Sample Python Redis")
    second = (await service.sync(1))["state"]
    await db_session.commit()
    assert second.latest.id != old.id and second.active.id == old.id
    assert second.pending_changes and len(second.history) == 2
    assert second.latest.review_status == "pending"
    assert (await CandidateProfileRepository(db_session).get_primary_profile()).version == accepted.latest.approved_profile_version
    review = await review_changes(db_session, settings, second.latest.id)
    assert "Docker" in review.proposed_profile.verified_skills  # Omitted confirmed skill retained.
    assert "FastAPI" in review.proposed_profile.verified_skills
    skills = next(item for item in review.differences if item.category == "skills")
    assert "Redis" in skills.added and "Docker" in skills.removed
    assert Fernet(settings.RESUME_ENCRYPTION_KEY.get_secret_value().encode()).decrypt((await db_session.get(PrivateResume, old.private_resume_id)).ciphertext) == old_bytes


@pytest.mark.parametrize("error", ["access_denied_or_revoked", "file_missing_or_access_revoked", "not_a_pdf_or_permission_required", "pdf_too_large", "download_timeout"])
async def test_failure_status_no_version_and_safe_retry(resume_bundle, db_session, error):
    service, drive, settings = resume_bundle
    drive.error = error
    result = await service.sync(1)
    await db_session.commit()
    assert result["outcome"] == "failed" and not result["state"].connected
    assert result["state"].last_error == error and result["state"].last_checked_at
    assert await db_session.scalar(select(func.count()).select_from(DriveResumeVersion)) == 0
    drive.error = None
    assert (await service.sync(1))["state"].connected


@pytest.mark.parametrize("raw", [b"<html>sign in</html>", b"%PDF-1.7\nmalformed", b"%PDF-" + b"x" * (5 * 1024 * 1024)],
                         ids=["html-response", "malformed-pdf", "oversized-pdf"])
async def test_malformed_or_oversized_pdf_is_not_persisted(resume_bundle, db_session, raw):
    service, drive, _ = resume_bundle
    drive.raw = raw
    result = await service.sync(1)
    await db_session.commit()
    assert result["state"].last_error == "malformed_or_unsafe_pdf"
    assert not result["state"].connected
    assert await db_session.scalar(select(func.count()).select_from(PrivateResume)) == 0


async def test_approval_updates_version_resource_and_stale_packets_without_mutating_history(resume_bundle, db_session, application_target, packet_service, phase2_profile):
    from backend.app.api.v1.application_answers import draft_read
    from backend.app.services.applications.base import ApplicationConflict
    from backend.app.services.applications.review import ApplicationReview
    from backend.tests.phase5a_fakes import approve, create

    service, _, settings = resume_bundle
    job, original_resource = application_target
    packet = await approve(packet_service, await create(packet_service, job))
    snapshot = packet.snapshot.model_dump(mode="json")
    draft = ApplicationAnswerDraft(candidate_profile_id=phase2_profile.id, question="Skills?", answer="Python", question_category="short_text", writing_style="professional", candidate_profile_version=phase2_profile.version)
    db_session.add(draft)
    await db_session.commit()
    pending = (await service.sync(1))["state"]
    accepted = await approval(db_session, settings, pending.latest.id)
    await db_session.commit()
    profile = await CandidateProfileRepository(db_session).get_primary_profile()
    assert profile.version == 2 and "Docker" in profile.verified_skills and "FastAPI" in profile.verified_skills
    assert accepted.active.id == pending.latest.id and not accepted.pending_changes
    assert accepted.latest.approved_profile_version == 2
    old_packet = await packet_service.read(packet.id)
    assert old_packet.readiness.stale and old_packet.snapshot.model_dump(mode="json") == snapshot
    assert old_packet.revision == packet.revision and old_packet.approved_revision == packet.approved_revision
    assert draft_read(draft, profile).stale
    with pytest.raises(ApplicationConflict, match="stale"):
        await ApplicationReview(packet_service).handoff(packet.id)
    await db_session.refresh(original_resource)
    assert not original_resource.is_primary and original_resource.user_confirmed
    again = await approval(db_session, settings, pending.latest.id)
    assert again.active.id == accepted.active.id
    assert (await CandidateProfileRepository(db_session).get_primary_profile()).version == 2


async def test_approval_only_resume_change_advances_profile_version(resume_bundle, db_session, phase2_profile):
    service, _, settings = resume_bundle
    state = (await service.sync(1))["state"]
    current = CandidateProfileCreate.model_validate(phase2_profile)
    await approval(db_session, settings, state.latest.id, profile=current)
    await db_session.commit()
    assert (await CandidateProfileRepository(db_session).get_primary_profile()).version == 2


async def test_first_profile_is_created_only_after_owner_approval(resume_bundle, db_session):
    service, _, settings = resume_bundle
    pending = (await service.sync(1))["state"]
    assert await CandidateProfileRepository(db_session).get_primary_profile() is None
    accepted = await approval(db_session, settings, pending.latest.id)
    await db_session.commit()
    profile = await CandidateProfileRepository(db_session).get_primary_profile()
    assert profile.version == 1 and profile.full_name == "Alex Sample"
    assert accepted.active.id == pending.latest.id and accepted.latest.approved_profile_version == 1
    primary = await db_session.scalar(select(CandidateResource).where(CandidateResource.is_primary.is_(True)))
    assert primary.candidate_profile_id == profile.id and primary.user_confirmed


async def test_stale_profile_or_source_and_unreviewed_skill_removal_rejected(resume_bundle, db_session, phase2_profile):
    service, _, settings = resume_bundle
    state = (await service.sync(1))["state"]
    with pytest.raises(HTTPException) as stale:
        await approval(db_session, settings, state.latest.id, expected_profile_version=99)
    assert stale.value.status_code == 409
    with pytest.raises(HTTPException) as stale:
        await approval(db_session, settings, state.latest.id, expected_generation=99)
    assert stale.value.status_code == 409
    current = CandidateProfileCreate.model_validate(phase2_profile)
    current.verified_skills = ["Python"]
    with pytest.raises(HTTPException) as removal:
        await approval(db_session, settings, state.latest.id, profile=current)
    assert removal.value.status_code == 422
    accepted = await approval(db_session, settings, state.latest.id, profile=current, allow_skill_removals=True)
    assert accepted.active.id == state.latest.id


async def test_change_source_needs_fetch_preserves_active_and_rejects_old_review(resume_bundle, db_session, phase2_profile):
    service, drive, settings = resume_bundle
    first = (await service.sync(1))["state"]
    await approval(db_session, settings, first.latest.id)
    new_url = URL.replace(FILE_ID, "fictional_drive_resume_002")
    changed = await save_source(db_session, settings, SourceSettings(canonical_url=new_url, expected_generation=1))
    await db_session.commit()
    assert not changed.connected and changed.latest is None and changed.active.id == first.latest.id
    with pytest.raises(HTTPException) as exc:
        await approval(db_session, settings, first.latest.id)
    assert exc.value.status_code == 409
    reconnected = (await service.sync(2))["state"]
    assert reconnected.file_id == "fictional_drive_resume_002"
    assert reconnected.latest.id == first.latest.id  # New source, identical bytes: no duplicate version.
    assert len(reconnected.history) == 1 and reconnected.file_name == "fictional_resume.pdf"


async def test_interrupted_sync_rolls_back_and_recovers(resume_bundle, db_session):
    service, drive, settings = resume_bundle
    async def interrupted(_):
        raise asyncio.CancelledError
    service.downloader = interrupted
    with pytest.raises(asyncio.CancelledError):
        await service.sync(1)
    await db_session.rollback()
    service.downloader = drive
    recovered = await service.sync(1)
    await db_session.commit()
    assert recovered["state"].latest and len(recovered["state"].history) == 1


async def test_partial_persistence_rolls_back_on_interruption(resume_bundle, db_session, monkeypatch):
    service, _, _ = resume_bundle
    async def interrupted(_):
        raise asyncio.CancelledError
    monkeypatch.setattr(service, "notify", interrupted)
    with pytest.raises(asyncio.CancelledError):
        await service.sync(1)
    await db_session.rollback()
    for model in (PrivateResume, DriveResumeVersion, ResumeProfileReview):
        assert await db_session.scalar(select(func.count()).select_from(model)) == 0


async def test_scheduler_disabled_even_if_env_enabled(resume_bundle, db_session, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from backend.app.resume_sync.scheduler import tick

    service, drive, settings = resume_bundle
    state = await status(db_session, settings)
    assert not state.scheduler_active
    assert "inactive" in state.scheduler_message
    await save_source(db_session, settings, SourceSettings(canonical_url=URL, expected_generation=1, sync_enabled=False))
    await db_session.commit()
    assert await tick(async_sessionmaker(db_session.bind), settings) == "disabled"
    assert drive.calls == 0


async def test_scheduled_checks_respect_opt_in_and_due_time(resume_bundle, db_session):
    service, drive, settings = resume_bundle
    await save_source(db_session, settings, SourceSettings(canonical_url=URL, expected_generation=1, sync_enabled=True))
    await db_session.commit()
    assert (await service.sync(scheduled=True))["outcome"] == "pending_review"
    assert (await service.sync(scheduled=True))["outcome"] == "disabled_or_not_due" and drive.calls == 1
    source = await db_session.get(ResumeDriveSource, "primary")
    source.last_checked_at = datetime.now(timezone.utc) - timedelta(hours=25)
    await db_session.commit()
    assert (await service.sync(scheduled=True))["outcome"] == "unchanged" and drive.calls == 2


async def test_no_credential_leakage(resume_bundle, db_session, caplog):
    service, drive, _ = resume_bundle
    drive.error = "https://secret-token@untrusted.example/private"
    result = await service.sync(1)
    assert "secret-token" not in str(result) + caplog.text
    assert result["state"].last_error == "bounded_network_check_failed"


async def test_notifications_respect_pause_and_defer_pending_review(resume_bundle, db_session):
    from backend.app.dashboard.notifications import synchronize

    service, _, _ = resume_bundle
    prefs = await db_session.get(OwnerPreference, "notifications")
    prefs.value = {"paused": True, "quiet_start": 0, "quiet_end": 0, "daily_digest": False}
    await db_session.commit()
    state = (await service.sync(1))["state"]
    await db_session.commit()
    assert state.pending_changes
    assert await db_session.scalar(select(func.count()).select_from(Notification)) == 0
    prefs.value = {"quiet_start": 0, "quiet_end": 0, "daily_digest": False}
    await db_session.commit()
    assert (await synchronize(db_session))["created"] == 1
    assert (await synchronize(db_session))["created"] == 0


async def test_scheduler_status_requires_live_heartbeat(resume_bundle, db_session):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from backend.app.resume_sync.scheduler import tick

    _, drive, settings = resume_bundle
    assert not (await status(db_session, settings)).scheduler_active
    await db_session.commit()
    assert await tick(async_sessionmaker(db_session.bind), settings, heartbeat=True) == "disabled"
    assert drive.calls == 0
    db_session.expire_all()
    assert (await status(db_session, settings)).scheduler_active
    heartbeat = await db_session.get(OwnerPreference, "resume_drive_scheduler")
    heartbeat.value = {"expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
    await db_session.commit()
    assert not (await status(db_session, settings)).scheduler_active


async def test_review_includes_current_verified_facts_and_candidate_evidence(resume_bundle, db_session, phase2_profile):
    from backend.app.models.application_answer import CandidateEvidence

    service, _, settings = resume_bundle
    phase2_profile.verified_roles = [{"company": "Confirmed Employer", "role": "Engineer", "start_date": "2024-01-01", "end_date": None, "highlight": "Built tested APIs"}]
    db_session.add(CandidateEvidence(candidate_profile_id=phase2_profile.id, evidence_type="achievement", title="Confirmed award", content="Won a fictional engineering award", user_confirmed=True))
    await db_session.commit()
    state = (await service.sync(1))["state"]
    review = await review_changes(db_session, settings, state.latest.id)
    dates = next(diff for diff in review.differences if diff.category == "employment_dates")
    awards = next(diff for diff in review.differences if diff.category == "achievements")
    assert "2024-01-01" in dates.current_verified[0]
    assert "Confirmed award" in awards.current_verified[0]


async def test_reverting_seen_bytes_reopens_review_without_duplicate_storage(resume_bundle, db_session, phase2_profile):
    service, drive, settings = resume_bundle
    first_bytes = drive.raw
    first = (await service.sync(1))["state"]
    await approval(db_session, settings, first.latest.id)
    drive.raw = pdf_bytes("Alex Sample Python Redis")
    second = (await service.sync(1))["state"]
    await approval(db_session, settings, second.latest.id)
    await db_session.commit()
    drive.raw = first_bytes
    reverted = (await service.sync(1))["state"]
    await db_session.commit()
    assert reverted.latest.id == first.latest.id and len(reverted.history) == 2
    assert reverted.active.id == second.latest.id
    assert reverted.latest.review_status == "pending" and reverted.latest.review_cycle == 2
    assert await db_session.scalar(select(func.count()).select_from(PrivateResume)) == 2
    assert await db_session.scalar(select(func.count()).select_from(Notification)) == 3
    review = await review_changes(db_session, settings, first.latest.id)
    skill_diff = next(diff for diff in review.differences if diff.category == "skills")
    assert "Redis" in skill_diff.removed and "Docker" in skill_diff.added
    accepted = await approval(db_session, settings, first.latest.id)
    assert accepted.active.id == first.latest.id and accepted.latest.approved_profile_version == 4


@pytest.mark.parametrize("url", ["http://drive.google.com/file/d/fictional_drive_resume_001/view", "https://drive.google.com.evil.example/file/d/fictional_drive_resume_001/view", "https://user:secret@drive.google.com/file/d/fictional_drive_resume_001/view", "https://127.0.0.1/file/d/fictional_drive_resume_001/view", URL + "&access_token=secret", URL + "#private", "https://url-shortner-jet-rho.vercel.app/r2wL9UE", URL.replace(FILE_ID, "../secret")])  # pragma: allowlist secret — fictional invalid credentials must be rejected
def test_invalid_google_drive_source(url):
    with pytest.raises(ValueError):
        canonical_source(url)


def test_file_id_must_match_and_review_cannot_be_disabled():
    with pytest.raises(ValueError):
        canonical_source(URL, "different-file-id")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, RESUME_DRIVE_SYNC_REQUIRES_REVIEW=False)


async def test_api_auth_validation_and_no_bypass(async_client, phase2_auth, resume_settings, monkeypatch):
    from backend.app.resume_sync import service as module
    monkeypatch.setattr(module, "fetch_pdf", FakeDrive())
    root = "/api/v1/dashboard/resume-sync"
    assert (await async_client.get(root)).status_code == 401
    before = await async_client.get(root, headers=phase2_auth)
    assert not before.json()["connected"] and "no-store" in before.headers["cache-control"]
    assert (await async_client.put(root + "/source", headers=phase2_auth, json={"canonical_url": "https://evil.example/resume.pdf", "expected_generation": 1})).status_code == 422
    synced = await async_client.post(root + "/sync", headers=phase2_auth, json={"expected_generation": 1})
    assert synced.status_code == 200, synced.text
    item = synced.json()["state"]["latest"]
    bypass = await async_client.post(f"/api/v1/dashboard/resumes/{item['private_resume_id']}/confirm", headers=phase2_auth, json={"owner_confirmed": True, "primary": True})
    assert bypass.status_code == 409
    changes = await async_client.get(root + f"/versions/{item['id']}/review", headers=phase2_auth)
    assert changes.status_code == 200
    invalid = await async_client.post(root + f"/versions/{item['id']}/approve", headers=phase2_auth, json={"owner_confirmed": False})
    assert invalid.status_code == 422
