"""Injected fictional Drive/PDF/encryption fixtures; all external IO is forbidden."""

import hashlib
import io
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.fernet import Fernet
from pypdf import PdfWriter

from backend.app.candidate_context.common import ContextError
from backend.app.candidate_context.configuration import ResumeSource
from backend.app.candidate_context.persistence import (
    FernetCipher,
    MemoryBlobStore,
    MemoryRecordStore,
)
from backend.app.candidate_context.resume import (
    MAX_PDF_BYTES,
    DriveMetadata,
    PDFDownload,
    ResumeSyncEngine,
    validate_pdf,
)


def fictional_pdf(width=72):
    writer = PdfWriter()
    writer.add_blank_page(width=width, height=72)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class FictionalDrive:
    def __init__(self):
        self.raw = fictional_pdf()
        self.version = 1
        self.downloads = 0
        self.metadata_calls = 0
        self.failure = None
        self.metadata_override = {}
        self.partial = False
        self.changed_during_download = False

    async def metadata(self, source):
        self.metadata_calls += 1
        if self.failure:
            raise ContextError(self.failure)
        return DriveMetadata(
            file_id=source.file_id,
            account_ref=source.account_ref,
            size=len(self.raw),
            version=self.version,
            revision_id=f"revision-{self.version}",
            sha256=hashlib.sha256(self.raw).hexdigest(),
            **self.metadata_override,
        )

    async def download(self, source, metadata):
        self.downloads += 1
        raw = self.raw[:-10] if self.partial else self.raw
        if self.changed_during_download:
            self.version += 1
            self.raw = fictional_pdf(120)
        return PDFDownload(raw=raw)


@pytest.fixture
def bundle():
    drive, records, blobs = FictionalDrive(), MemoryRecordStore(), MemoryBlobStore()
    now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
    source = ResumeSource(
        canonical_url="https://drive.google.com/file/d/fictional_drive_pdf_001/view",
        file_id="fictional_drive_pdf_001",
        account_ref="fictional-account",
        auto_sync_enabled=True,
    )
    cipher = FernetCipher(Fernet.generate_key())
    return (
        ResumeSyncEngine(drive, records, blobs, cipher, clock=lambda: now[0]),
        drive,
        records,
        blobs,
        source,
        now,
    )


async def approve_latest(engine):
    ledger = await engine.read()
    return await engine.approve(
        ledger.latest_version_id,
        expected_revision=ledger.revision,
        expected_source_generation=ledger.source.generation,
        owner_ref="fictional-owner",
        owner_confirmed=True,
    )


async def test_new_pdf_encrypted_pending_and_duplicate_poll_skips_download(bundle):
    engine, drive, records, blobs, source, _ = bundle
    first = await engine.check(source)
    assert (
        first.outcome == "pending_review" and first.ledger.approved_version_id is None
    )
    assert first.ledger.versions[0].status == "pending_review"
    assert drive.raw.decode("latin1") not in str(
        await records.read("candidate_resume_sync_v1")
    )
    assert all("%PDF-" not in ciphertext for ciphertext in blobs.values.values())
    second = await engine.check(source)
    assert second.outcome == "unchanged" and drive.downloads == 1
    assert len(second.ledger.versions) == 1 and len(second.ledger.events) == 1


async def test_same_link_updated_pdf_preserves_approved_and_only_promotion_invalidates(
    bundle,
):
    engine, drive, _, blobs, source, _ = bundle
    first = await engine.check(source)
    old_id = first.ledger.latest_version_id
    old_bytes = drive.raw
    approved = await approve_latest(engine)
    drive.raw, drive.version = fictional_pdf(90), 2
    second = await engine.check(source)
    assert second.ledger.approved_version_id == old_id
    assert second.ledger.latest_version_id != old_id
    assert second.ledger.fact_generation == approved.fact_generation
    assert engine.cipher.decrypt(await blobs.read(old_id)) == old_bytes
    promoted = await approve_latest(engine)
    assert promoted.fact_generation == approved.fact_generation + 1
    assert promoted.approved_version_id == second.ledger.latest_version_id
    invalidations = [
        e for e in promoted.events if e.kind == "candidate_facts_invalidated"
    ]
    assert len(invalidations) == 2 and invalidations[-1].previous_version_id == old_id


async def test_changed_revision_with_identical_checksum_skips_download(bundle):
    engine, drive, _, _, source, _ = bundle
    await engine.check(source)
    drive.version = 2
    result = await engine.check(source)
    assert result.outcome == "unchanged" and drive.downloads == 1
    assert result.ledger.metadata.version == 2


async def test_changed_url_requires_generation_and_records_provenance(bundle):
    engine, drive, _, _, source, _ = bundle
    await engine.check(source)
    await approve_latest(engine)
    different = ResumeSource(
        canonical_url="https://drive.google.com/file/d/fictional_drive_pdf_002/view",
        file_id="fictional_drive_pdf_002",
        account_ref=source.account_ref,
        generation=2,
    )
    result = await engine.check(different)
    assert result.outcome == "pending_review" and drive.downloads == 2
    assert result.ledger.versions[-1].source.file_id == different.file_id
    assert result.ledger.approved_version_id != result.ledger.latest_version_id
    with pytest.raises(ContextError, match="stale_resume_source_generation"):
        await engine.check(source)


async def test_changed_file_without_generation_rejected(bundle):
    engine, _, _, _, source, _ = bundle
    await engine.check(source)
    changed = ResumeSource(
        canonical_url="https://drive.google.com/file/d/fictional_drive_pdf_002/view",
        file_id="fictional_drive_pdf_002",
        account_ref=source.account_ref,
    )
    with pytest.raises(ContextError, match="requires_new_generation"):
        await engine.check(changed)


@pytest.mark.parametrize(
    "failure",
    [
        "drive_permission_expired",
        "drive_file_unavailable",
        "drive_redirect_rejected",
        "drive_network_failed",
        "drive_rate_limited",
    ],
)
async def test_failures_preserve_approved_and_deduplicate_notifications(
    bundle, failure
):
    engine, drive, _, _, source, _ = bundle
    await engine.check(source)
    previous = await approve_latest(engine)
    drive.failure = failure
    first = await engine.check(source)
    second = await engine.check(source)
    assert first.outcome == second.outcome == "failed"
    assert second.ledger.approved_version_id == previous.approved_version_id
    assert len([e for e in second.ledger.events if e.kind == "resume_sync_failed"]) == 1
    assert second.ledger.last_error == failure
    drive.failure = None
    assert (await engine.check(source)).outcome == "unchanged"


async def test_partial_download_and_metadata_race_are_not_stored(bundle):
    engine, drive, _, blobs, source, _ = bundle
    drive.partial = True
    assert (
        await engine.check(source)
    ).ledger.last_error == "partial_or_changed_download"
    assert not blobs.values
    drive.partial = False
    drive.changed_during_download = True
    assert (await engine.check(source)).outcome == "failed"
    assert not blobs.values


async def test_invalid_pdf_is_rejected_before_encrypted_storage(bundle):
    engine, drive, _, blobs, source, _ = bundle
    drive.raw = b"not a PDF"
    result = await engine.check(source)
    assert result.ledger.last_error == "invalid_pdf" and not blobs.values


async def test_pdf_validation_handles_oversized_truncated_and_active_content():
    from pypdf.generic import DictionaryObject, NameObject, TextStringObject

    with pytest.raises(ContextError, match="pdf_too_large"):
        await validate_pdf(b"%PDF-" + b"x" * MAX_PDF_BYTES)
    with pytest.raises(ContextError, match="invalid_or_unsafe_pdf"):
        await validate_pdf(fictional_pdf()[:-20])
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer._root_object[NameObject("/OpenAction")] = DictionaryObject(
        {
            NameObject("/S"): NameObject("/JavaScript"),
            NameObject("/JS"): TextStringObject("fictional"),
        }
    )
    output = io.BytesIO()
    writer.write(output)
    with pytest.raises(ContextError, match="invalid_or_unsafe_pdf"):
        await validate_pdf(output.getvalue())


async def test_scheduled_checks_are_bounded_and_respect_disable(bundle):
    engine, drive, _, _, source, now = bundle
    await engine.check(source, scheduled=True)
    assert (await engine.check(source, scheduled=True)).outcome == "not_due"
    now[0] += timedelta(hours=6)
    assert (await engine.check(source, scheduled=True)).outcome == "unchanged"
    assert drive.downloads == 1
    disabled = source.model_copy(update={"auto_sync_enabled": False})
    now[0] += timedelta(days=1)
    assert (await engine.check(disabled, scheduled=True)).outcome == "not_due"


async def test_approval_is_version_bound_and_retry_safe(bundle):
    engine, drive, _, _, source, _ = bundle
    first = await engine.check(source)
    with pytest.raises(ContextError, match="explicit_owner_review"):
        await engine.approve(
            first.ledger.latest_version_id,
            expected_revision=first.ledger.revision,
            expected_source_generation=1,
            owner_ref="fictional-owner",
            owner_confirmed=False,
        )
    await engine.check(source)
    with pytest.raises(ContextError, match="changed_reload_review"):
        await engine.approve(
            first.ledger.latest_version_id,
            expected_revision=first.ledger.revision,
            expected_source_generation=1,
            owner_ref="fictional-owner",
            owner_confirmed=True,
        )
    approved = await approve_latest(engine)
    retry = await engine.approve(
        approved.latest_version_id,
        expected_revision=1,
        expected_source_generation=1,
        owner_ref="fictional-owner",
        owner_confirmed=True,
    )
    assert retry == approved
    drive.raw, drive.version = fictional_pdf(110), 2
    await engine.check(source)
    with pytest.raises(ContextError, match="only_latest_resume"):
        await engine.approve(
            approved.latest_version_id,
            expected_revision=(await engine.read()).revision,
            expected_source_generation=1,
            owner_ref="fictional-owner",
            owner_confirmed=True,
        )


async def test_event_acknowledgment_and_restart_preserve_state(bundle):
    engine, drive, records, blobs, source, _ = bundle
    result = await engine.check(source)
    event = result.ledger.events[0]
    restarted = ResumeSyncEngine(
        drive, records, blobs, engine.cipher, clock=engine.clock
    )
    ledger = await restarted.acknowledge_event(event.id)
    assert not ledger.events
    assert await restarted.acknowledge_event(event.id) == ledger
    assert (await restarted.check(source)).outcome == "unchanged"


async def test_old_drive_revision_cannot_replace_latest(bundle):
    engine, drive, _, _, source, _ = bundle
    drive.version = 2
    await engine.check(source)
    drive.version = 1
    assert (await engine.check(source)).ledger.last_error == "stale_drive_revision"


async def test_first_failure_still_observes_periodic_backoff(bundle):
    engine, drive, _, _, source, now = bundle
    drive.failure = "drive_permission_expired"
    assert (await engine.check(source, scheduled=True)).outcome == "failed"
    calls = drive.metadata_calls
    assert (await engine.check(source, scheduled=True)).outcome == "not_due"
    assert drive.metadata_calls == calls
    now[0] += timedelta(hours=6)
    assert (await engine.check(source, scheduled=True)).outcome == "failed"


async def test_changed_but_inaccessible_source_retains_previous_approved_version(
    bundle,
):
    engine, drive, _, _, source, _ = bundle
    await engine.check(source)
    previous = await approve_latest(engine)
    changed = ResumeSource(
        canonical_url="https://drive.google.com/file/d/fictional_drive_pdf_002/view",
        file_id="fictional_drive_pdf_002",
        account_ref=source.account_ref,
        generation=2,
    )
    drive.failure = "drive_file_unavailable"
    failed = await engine.check(changed)
    assert failed.ledger.approved_version_id == previous.approved_version_id
    assert failed.ledger.source.generation == 2
    assert failed.ledger.events[-1].source_generation == 2
    with pytest.raises(ContextError, match="source_changed_reload"):
        await engine.approve(
            previous.approved_version_id,
            expected_revision=previous.revision,
            expected_source_generation=1,
            owner_ref="fictional-owner",
            owner_confirmed=True,
        )
    drive.failure = None
    recovered = await engine.check(changed)
    assert recovered.outcome == "pending_review"
    assert recovered.ledger.versions[-1].source.file_id == changed.file_id
    assert recovered.ledger.latest_version_id != previous.approved_version_id


async def test_corrupted_encrypted_bytes_cannot_be_promoted(bundle):
    engine, _, _, blobs, source, _ = bundle
    first = await engine.check(source)
    version = first.ledger.latest_version_id
    blobs.values[version] = engine.cipher.encrypt(b"corrupted")
    with pytest.raises(ContextError, match="encrypted_resume_integrity_failed"):
        await approve_latest(engine)
    assert (await engine.read()).approved_version_id is None


async def test_concurrent_checks_use_atomic_version_commit(bundle):
    import asyncio

    engine, drive, records, blobs, source, _ = bundle
    other = ResumeSyncEngine(drive, records, blobs, engine.cipher, clock=engine.clock)
    results = await asyncio.gather(
        engine.check(source), other.check(source), return_exceptions=True
    )
    ledger = await engine.read()
    assert len(ledger.versions) == 1 and len(ledger.events) == 1
    assert any(
        getattr(result, "outcome", None) == "pending_review" for result in results
    )
    assert all(
        not isinstance(result, Exception)
        or str(result) == "concurrent_record_change_reload"
        for result in results
    )
