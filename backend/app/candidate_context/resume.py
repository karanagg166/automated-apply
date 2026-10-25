"""Injected, review-gated Drive resume synchronization. No automatic account access."""

import asyncio
import hashlib
import sys
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, field_validator

from backend.app.candidate_context.common import (
    ContextError,
    Contract,
    aware,
    canonical_hash,
    utc_now,
)
from backend.app.candidate_context.configuration import FILE_ID, ResumeSource
from backend.app.candidate_context.persistence import BlobStore, Cipher, RecordStore

MAX_PDF_BYTES = 5 * 1024 * 1024
LEDGER_KEY = "candidate_resume_sync_v1"


class DriveMetadata(Contract):
    file_id: str = Field(pattern=rf"^{FILE_ID}$")
    account_ref: str = Field(min_length=1, max_length=120)
    mime_type: Literal["application/pdf"] = "application/pdf"
    size: int = Field(ge=1, le=MAX_PDF_BYTES)
    version: int | None = Field(default=None, ge=1)
    revision_id: str | None = Field(default=None, min_length=1, max_length=200)
    etag: str | None = Field(default=None, min_length=1, max_length=500)
    modified_at: datetime | None = None
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    can_download: Literal[True] = True

    @field_validator("modified_at")
    @classmethod
    def aware_time(cls, value):
        return aware(value) if value else None

    @property
    def reliable(self) -> bool:
        return (
            self.version is not None
            or self.revision_id is not None
            or self.sha256 is not None
        )


class PDFDownload(Contract):
    # repr excludes raw PDF bytes to prevent accidental diagnostics leaking content.
    raw: bytes = Field(repr=False)
    mime_type: Literal["application/pdf"] = "application/pdf"
    complete: Literal[True] = True


class DriveClient(Protocol):
    async def metadata(self, source: ResumeSource) -> DriveMetadata: ...
    async def download(
        self, source: ResumeSource, metadata: DriveMetadata
    ) -> PDFDownload: ...


class ResumeEvent(Contract):
    id: str = Field(pattern=r"^[a-f0-9]{64}$")
    kind: Literal[
        "resume_update_detected",
        "resume_approved",
        "candidate_facts_invalidated",
        "resume_sync_failed",
    ]
    version_id: str | None = None
    previous_version_id: str | None = None
    code: str | None = None
    source_generation: int | None = None
    created_at: datetime


class ResumeVersion(Contract):
    id: str
    blob_id: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source: ResumeSource
    metadata: DriveMetadata
    downloaded_at: datetime
    status: Literal["pending_review", "approved"] = "pending_review"
    approved_at: datetime | None = None
    approved_by: str | None = Field(default=None, max_length=120)


class ResumeLedger(Contract):
    revision: int = Field(default=0, ge=0)
    source: ResumeSource | None = None
    metadata: DriveMetadata | None = None
    last_checked_at: datetime | None = None
    last_downloaded_at: datetime | None = None
    latest_version_id: str | None = None
    approved_version_id: str | None = None
    versions: tuple[ResumeVersion, ...] = Field(default=(), max_length=500)
    events: tuple[ResumeEvent, ...] = Field(default=(), max_length=200)
    # Invalidation generation changes only on approved source promotion.
    fact_generation: int = Field(default=0, ge=0)
    last_error: str | None = Field(default=None, max_length=80)


class SyncResult(Contract):
    outcome: Literal["not_due", "unchanged", "pending_review", "failed"]
    ledger: ResumeLedger


async def validate_pdf(raw: bytes) -> None:
    if len(raw) > MAX_PDF_BYTES:
        raise ContextError("pdf_too_large")
    if not raw.startswith(b"%PDF-"):
        raise ContextError("invalid_pdf")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).with_name("pdf_worker.py")),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env={"PATH": "/usr/bin:/bin"},
    )
    try:
        output, _ = await asyncio.wait_for(process.communicate(raw), 10)
        if process.returncode != 0 or output != b"valid":
            raise ContextError("invalid_or_unsafe_pdf")
    except TimeoutError:
        raise ContextError("pdf_validation_timeout") from None
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()


def source_identity(source: ResumeSource) -> tuple[str, str, int]:
    return source.account_ref, source.file_id, source.generation


def same_content_metadata(before: DriveMetadata, after: DriveMetadata) -> bool:
    # Names/permissions can change independently of bytes, but identity never can.
    if (before.file_id, before.account_ref, before.size) != (
        after.file_id,
        after.account_ref,
        after.size,
    ):
        return False
    if before.sha256 and after.sha256:
        return before.sha256 == after.sha256
    values = ("version", "revision_id", "etag", "modified_at")
    return any(getattr(after, key) is not None for key in values) and all(
        getattr(before, key) == getattr(after, key) for key in values
    )


class ResumeSyncEngine:
    """Caller owns transaction, scheduling, owner auth and event delivery.

    Atomic CAS rejects concurrent updates. Events enter the same durable record as
    versions; consumers acknowledge delivery separately with a stable event ID.
    No notification is sent from this module.
    """

    def __init__(
        self,
        drive: DriveClient,
        records: RecordStore,
        blobs: BlobStore,
        cipher: Cipher,
        *,
        clock: Callable[[], datetime] = utc_now,
        validator: Callable[[bytes], Awaitable[None]] = validate_pdf,
    ):
        self.drive, self.records, self.blobs, self.cipher = (
            drive,
            records,
            blobs,
            cipher,
        )
        self.clock, self.validator = clock, validator

    async def read(self) -> ResumeLedger:
        value = await self.records.read(LEDGER_KEY)
        return ResumeLedger.model_validate(value) if value else ResumeLedger()

    async def _save(self, previous: ResumeLedger, **changes) -> ResumeLedger:
        value = ResumeLedger.model_validate(
            {**previous.model_dump(), **changes, "revision": previous.revision + 1}
        )
        await self.records.compare_and_swap(
            LEDGER_KEY, previous.revision, value.model_dump(mode="json")
        )
        return value

    def _event(
        self,
        kind,
        version_id=None,
        previous_version_id=None,
        code=None,
        source_generation=None,
    ):
        now = aware(self.clock())
        identity = {
            "kind": kind,
            "version_id": version_id,
            "previous_version_id": previous_version_id,
            "code": code,
            "source_generation": source_generation,
        }
        return ResumeEvent(id=canonical_hash(identity), created_at=now, **identity)

    @staticmethod
    def _events(ledger: ResumeLedger, *events: ResumeEvent) -> tuple[ResumeEvent, ...]:
        existing = {event.id: event for event in ledger.events}
        for event in events:
            existing.setdefault(event.id, event)
        if len(existing) > 200:
            raise ContextError("resume_event_outbox_full")
        return tuple(existing.values())

    async def check(
        self, source: ResumeSource, *, scheduled: bool = False
    ) -> SyncResult:
        ledger, now = await self.read(), aware(self.clock())
        latest_version = next(
            (v for v in ledger.versions if v.id == ledger.latest_version_id), None
        )
        latest_matches_source = latest_version is not None and source_identity(
            latest_version.source
        ) == source_identity(source)
        same_source = ledger.source is not None and source_identity(
            ledger.source
        ) == source_identity(source)
        if ledger.source and source.generation < ledger.source.generation:
            raise ContextError("stale_resume_source_generation")
        if (
            ledger.source
            and source.generation == ledger.source.generation
            and not same_source
        ):
            raise ContextError("source_change_requires_new_generation")
        if scheduled and (
            not source.auto_sync_enabled
            or (
                same_source
                and ledger.last_checked_at
                and now
                < ledger.last_checked_at + timedelta(minutes=source.interval_minutes)
            )
        ):
            return SyncResult(outcome="not_due", ledger=ledger)
        try:
            metadata = await self.drive.metadata(source)
            self._bound_metadata(source, metadata)
            if (
                same_source
                and ledger.metadata
                and ledger.metadata.file_id == metadata.file_id
                and ledger.metadata.version
                and metadata.version
            ):
                if metadata.version < ledger.metadata.version:
                    raise ContextError("stale_drive_revision")
            revalidate = (
                ledger.last_downloaded_at is None
                or now - ledger.last_downloaded_at >= timedelta(hours=24)
            )
            if (
                same_source
                and latest_matches_source
                and ledger.metadata
                and same_content_metadata(ledger.metadata, metadata)
                and (metadata.reliable or not revalidate)
            ):
                updated = await self._save(
                    ledger,
                    metadata=metadata,
                    source=source,
                    last_checked_at=now,
                    last_error=None,
                )
                return SyncResult(outcome="unchanged", ledger=updated)
            downloaded = await self.drive.download(source, metadata)
            raw = downloaded.raw
            if len(raw) > MAX_PDF_BYTES:
                raise ContextError("pdf_too_large")
            if len(raw) != metadata.size:
                raise ContextError("partial_or_changed_download")
            digest = hashlib.sha256(raw).hexdigest()
            if metadata.sha256 and metadata.sha256 != digest:
                raise ContextError("resume_checksum_mismatch")
            await self.validator(raw)
            # A file changing during download is retried on a later bounded check.
            after = await self.drive.metadata(source)
            self._bound_metadata(source, after)
            if not same_content_metadata(metadata, after) and metadata != after:
                raise ContextError("drive_changed_during_download")
            if after.sha256 and after.sha256 != digest:
                raise ContextError("resume_checksum_mismatch")
            if same_source:
                current = next(
                    (v for v in ledger.versions if v.id == ledger.latest_version_id),
                    None,
                )
                if current and latest_matches_source and current.sha256 == digest:
                    updated = await self._save(
                        ledger,
                        source=source,
                        metadata=after,
                        last_checked_at=now,
                        last_downloaded_at=now,
                        last_error=None,
                    )
                    return SyncResult(outcome="unchanged", ledger=updated)
            if len(ledger.versions) >= 500:
                raise ContextError("resume_history_capacity_requires_owner_archive")
            version_id = str(
                uuid5(
                    NAMESPACE_URL,
                    canonical_hash(
                        {
                            "source": source_identity(source),
                            "sha256": digest,
                            "previous": ledger.latest_version_id,
                        }
                    ),
                )
            )
            # Idempotent immutable blob write. A failed CAS leaves only an unreferenced
            # encrypted blob; SQL callers roll the entire transaction back.
            await self.blobs.put(version_id, self.cipher.encrypt(raw), digest)
            version = ResumeVersion(
                id=version_id,
                blob_id=version_id,
                sha256=digest,
                source=source,
                metadata=after,
                downloaded_at=now,
            )
            event = self._event(
                "resume_update_detected", version_id, ledger.approved_version_id
            )
            updated = await self._save(
                ledger,
                source=source,
                metadata=after,
                last_checked_at=now,
                last_downloaded_at=now,
                latest_version_id=version_id,
                versions=(*ledger.versions, version),
                events=self._events(ledger, event),
                last_error=None,
            )
            return SyncResult(outcome="pending_review", ledger=updated)
        except ContextError as exc:
            if str(exc) in {
                "concurrent_record_change_reload",
                "resume_event_outbox_full",
            }:
                raise
            allowed = {
                "drive_permission_expired",
                "drive_file_unavailable",
                "drive_source_not_authorized",
                "drive_account_mismatch",
                "drive_redirect_rejected",
                "drive_network_failed",
                "drive_response_invalid",
                "drive_response_too_large",
                "drive_rate_limited",
                "pdf_too_large",
                "invalid_pdf",
                "invalid_or_unsafe_pdf",
                "pdf_validation_timeout",
                "partial_or_changed_download",
                "resume_checksum_mismatch",
                "drive_changed_during_download",
                "stale_drive_revision",
                "resume_history_capacity_requires_owner_archive",
            }
            code = str(exc) if str(exc) in allowed else "resume_sync_failed"
            event = self._event(
                "resume_sync_failed",
                ledger.latest_version_id,
                code=code,
                source_generation=source.generation,
            )
            updated = await self._save(
                ledger,
                source=source,
                last_checked_at=now,
                events=self._events(ledger, event),
                last_error=code,
            )
            return SyncResult(outcome="failed", ledger=updated)

    @staticmethod
    def _bound_metadata(source: ResumeSource, metadata: DriveMetadata) -> None:
        if metadata.account_ref != source.account_ref:
            raise ContextError("drive_account_mismatch")
        if metadata.file_id != source.file_id:
            raise ContextError("drive_source_not_authorized")

    async def approve(
        self,
        version_id: str,
        *,
        expected_revision: int,
        expected_source_generation: int,
        owner_ref: str,
        owner_confirmed: bool,
    ) -> ResumeLedger:
        if not owner_confirmed or not owner_ref or len(owner_ref) > 120:
            raise ContextError("explicit_owner_review_required")
        ledger = await self.read()
        if not ledger.source or ledger.source.generation != expected_source_generation:
            raise ContextError("resume_source_changed_reload_review")
        if (
            ledger.approved_version_id == version_id
            and ledger.latest_version_id == version_id
        ):
            return ledger  # Safe lost-response retry, no duplicate invalidation.
        if ledger.revision != expected_revision:
            raise ContextError("resume_changed_reload_review")
        version = next((v for v in ledger.versions if v.id == version_id), None)
        if not version or ledger.latest_version_id != version_id:
            raise ContextError("only_latest_resume_can_be_approved")
        # Verify the encrypted blob still exists and matches the reviewed digest.
        raw = self.cipher.decrypt(await self.blobs.read(version.blob_id))
        if hashlib.sha256(raw).hexdigest() != version.sha256:
            raise ContextError("encrypted_resume_integrity_failed")
        approved = version.model_copy(
            update={
                "status": "approved",
                "approved_at": aware(self.clock()),
                "approved_by": owner_ref,
            }
        )
        events = [
            self._event("resume_approved", version_id, ledger.approved_version_id)
        ]
        if ledger.approved_version_id != version_id:
            events.append(
                self._event(
                    "candidate_facts_invalidated",
                    version_id,
                    ledger.approved_version_id,
                )
            )
        return await self._save(
            ledger,
            approved_version_id=version_id,
            versions=tuple(
                approved if v.id == version_id else v for v in ledger.versions
            ),
            fact_generation=ledger.fact_generation + 1,
            events=self._events(ledger, *events),
        )

    async def acknowledge_event(self, event_id: str) -> ResumeLedger:
        ledger = await self.read()
        events = tuple(event for event in ledger.events if event.id != event_id)
        if len(events) == len(ledger.events):
            return ledger
        return await self._save(ledger, events=events)
