"""Actual worker preparation and encrypted fictional PDFs; no portal/browser calls."""

import hashlib
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.agent.tools import ToolDenied
from backend.app.core.config import Settings
from backend.app.dashboard.models import PrivateResume
from backend.app.execution import recurring, store
from backend.app.execution.naukri_upload import MAX_PDF_BYTES, preflight
from backend.app.execution.worker import prepare
from backend.app.local_agent.profile_confirmation import confirm_profile
from backend.app.schemas.applications import CreatePacket
from backend.app.services.applications.service import ApplicationPacketService
from backend.tests.test_naukri_recurring import imported


@pytest.fixture
async def upload_case(db_session, phase2_profile, application_target):
    old_job, resource = application_target
    old_job.source_platform = "fictional_fixture"
    phase2_profile.preferences = {
        **phase2_profile.preferences, "target_titles": ["Backend Developer"],
        "preferred_locations": ["India"],
    }
    raw = b"%PDF-1.4\nFictional worker preflight only\n%%EOF"
    key = Fernet.generate_key()
    private = PrivateResume(
        label="Fictional PDF", resource_id=resource.id, confirmed=True,
        ciphertext=Fernet(key).encrypt(raw), sha256=hashlib.sha256(raw).hexdigest(),
    )
    db_session.add(private)
    await db_session.flush()
    resource.source_type = "private_upload"
    resource.url = "private-resume:" + str(private.id)
    await confirm_profile(db_session, phase2_profile, phase2_profile.version)
    job_id = await imported(db_session)
    await db_session.commit()
    service = ApplicationPacketService(db_session)
    packet = await service.create(job_id, CreatePacket(idempotency_key="fictional-upload-preflight"))
    await db_session.commit()
    packet = await service.read(packet.id)
    return SimpleNamespace(
        resource=resource, private=private, raw=raw, key=key, job_id=job_id,
        packet=packet, settings=Settings(_env_file=None, RESUME_ENCRYPTION_KEY=key.decode()),
    )


async def test_exact_private_pdf_is_verified_without_browser_admission(db_session, upload_case):
    case = upload_case
    result = await preflight(db_session, case.packet, case.settings)
    assert result["state"] == "PDF_VERIFIED_LOCAL"
    assert result["byte_count"] == len(case.raw)
    assert result["sha256"] == case.private.sha256
    assert result["resource_version"] == case.packet.snapshot.resume.selected.resource_version
    assert result["browser_action_admitted"] is False
    assert "%PDF" not in json.dumps(result) and "ciphertext" not in result


@pytest.mark.parametrize("change, reason", [
    ("packet_stale", "packet_context_stale"),
    ("foreign_profile", "confirmed_primary_resume_required"),
    ("resume_revision", "resume_revision_changed"),
    ("policy_revision", "policy_resume_binding_changed"),
    ("missing_key", "resume_decryption_key_unavailable"),
    ("ciphertext", "canonical_pdf_unavailable_or_invalid"),
    ("checksum", "canonical_pdf_unavailable_or_invalid"),
    ("private_unconfirmed", "canonical_pdf_unavailable_or_invalid"),
    ("oversize", "pdf_exceeds_conservative_naukri_limit"),
    ("not_pdf", "canonical_pdf_unavailable_or_invalid"),
])
async def test_unattended_resume_preflight_refuses_changed_or_invalid_input(db_session, upload_case, change, reason):
    case = upload_case
    settings, packet, policy = case.settings, case.packet, None
    if change == "packet_stale":
        packet.readiness.stale = True
    elif change == "foreign_profile":
        packet.candidate_profile_id = uuid4()
    elif change == "resume_revision":
        packet.snapshot.resume.selected.resource_version = "0" * 64
    elif change == "policy_revision":
        policy = SimpleNamespace(resume_resource_id=case.resource.id, resume_version="0" * 64)
    elif change == "missing_key":
        settings = settings.model_copy(update={"RESUME_ENCRYPTION_KEY": None})
    elif change == "ciphertext":
        case.private.ciphertext = b"fictional invalid encryption"
    elif change == "checksum":
        case.private.sha256 = "0" * 64
    elif change == "private_unconfirmed":
        case.private.confirmed = False
    elif change in {"oversize", "not_pdf"}:
        raw = b"%PDF-" + b"x" * (MAX_PDF_BYTES - 4) if change == "oversize" else b"not a PDF"
        case.private.ciphertext = Fernet(case.key).encrypt(raw)
        case.private.sha256 = hashlib.sha256(raw).hexdigest()
    await db_session.flush()
    result = await preflight(db_session, packet, settings, policy)
    assert result["state"] == "NEEDS_INPUT" and result["reason"] == reason
    assert result["browser_action_admitted"] is False
    assert result["sha256"] is None


async def test_verified_url_is_not_downloaded_or_mislabeled_as_uploaded_pdf(db_session, upload_case):
    case = upload_case
    case.resource.source_type = "manual"
    case.resource.url = "https://example.org/fictional-approved-resume.pdf"
    await db_session.commit()
    service = ApplicationPacketService(db_session)
    # Rebuild the packet normally; this is a current owner-approved link, not a
    # stale snapshot. Its bytes still cannot be silently fetched for submission.
    from backend.app.models.application_packet import ApplicationPacket

    saved = await db_session.get(ApplicationPacket, case.packet.id)
    _, _, snapshot = await service.builder.context(case.job_id)
    saved.snapshot = snapshot.model_dump(mode="json")
    await db_session.commit()
    packet = await service.read(case.packet.id)
    result = await preflight(db_session, packet, case.settings)
    assert result["state"] == "NEEDS_INPUT"
    assert result["reason"] == "canonical_private_pdf_required"


async def test_worker_commits_pdf_preflight_across_fresh_sessions(db_session, upload_case, monkeypatch):
    from backend.app.core import config

    case = upload_case
    monkeypatch.setattr(config, "get_settings", lambda: case.settings)
    intent = (await store.start(db_session, [case.job_id]))[0]
    identity = await store.claim(db_session)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    async with factory() as worker, worker.begin():
        await prepare(worker, identity)
    async with factory() as verifier:
        execution = (await store.load(verifier, intent["id"])).value
        assert execution["packet_id"] == str(case.packet.id)
        assert execution["upload_preflight"]["state"] == "PDF_VERIFIED_LOCAL"
        assert execution["upload_preflight"]["sha256"] == case.private.sha256
        assert execution["upload_preflight"]["browser_action_admitted"] is False
        assert "%PDF" not in json.dumps(execution)
        view = await recurring.status(verifier)
        assert view["counts"]["resume_preflights_verified"] == 1
        assert view["counts"]["installed_worker_recorded"] == 0
        assert view["policy"] is None  # Preflight does not invent a standing policy.
        assert UUID(execution["packet_id"]) == case.packet.id


async def test_owner_pause_fences_worker_before_pdf_preflight(db_session, upload_case):
    case = upload_case
    intent = (await store.start(db_session, [case.job_id]))[0]
    identity = await store.claim(db_session)
    await db_session.commit()
    await store.control(db_session, intent["id"], "pause", intent["revision"])
    await db_session.commit()
    with pytest.raises(ToolDenied, match="execution_lease_lost"):
        await prepare(db_session, identity)
    assert "upload_preflight" not in (await store.load(db_session, intent["id"])).value


async def test_conservative_decimal_size_boundary_does_not_grant_upload(db_session, upload_case):
    case = upload_case
    raw = b"%PDF-" + b"x" * (MAX_PDF_BYTES - 5)
    case.private.ciphertext = Fernet(case.key).encrypt(raw)
    case.private.sha256 = hashlib.sha256(raw).hexdigest()
    await db_session.flush()
    result = await preflight(db_session, case.packet, case.settings)
    assert result["state"] == "PDF_VERIFIED_LOCAL"
    assert result["byte_count"] == MAX_PDF_BYTES
    assert result["browser_action_admitted"] is False


async def test_removed_primary_requires_owner_selection(db_session, upload_case):
    case = upload_case
    case.resource.is_primary = False
    await db_session.flush()
    result = await preflight(db_session, case.packet, case.settings)
    assert result["reason"] == "confirmed_primary_resume_required"
    assert result["browser_action_admitted"] is False
