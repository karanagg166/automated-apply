"""Source locking and private status reads; callers own the transaction."""

from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select

from backend.app.dashboard.models import OwnerPreference
from backend.app.dashboard.resumes import cipher
from backend.app.resume_sync.models import (
    DriveResumeVersion,
    ResumeDriveSource,
    ResumeProfileReview,
)
from backend.app.resume_sync.schemas import ResumeVersionRead, SyncStatus
from backend.app.resume_sync.source import canonical_source
from backend.app.services.discovery_budget import insert_for


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def default_source(settings, supplied_url=None):
    value = supplied_url or settings.CANDIDATE_RESUME_DRIVE_URL
    if not value:
        raise HTTPException(422, "Configure or explicitly choose a Google Drive resume source")
    try:
        file_id, url = canonical_source(str(value), None if supplied_url else settings.CANDIDATE_RESUME_DRIVE_FILE_ID)
    except ValueError:
        raise HTTPException(422, "Invalid or mismatched Google Drive resume source") from None
    return dict(key="primary", file_id=file_id, canonical_url=url, generation=1,
                sync_enabled=settings.RESUME_DRIVE_SYNC_ENABLED,
                interval_hours=settings.RESUME_DRIVE_SYNC_INTERVAL_HOURS,
                status="not_checked")


async def lock_source(session, settings, supplied_url=None):
    # INSERT also serializes SQLite writers. PostgreSQL holds a row lock through download
    # and commit; concurrent checks cannot create two versions of the same bytes.
    existing = await session.get(ResumeDriveSource, "primary")
    defaults = default_source(settings, supplied_url) if existing is None else dict(
        key="primary", file_id=existing.file_id, canonical_url=existing.canonical_url)
    await session.execute(insert_for(session)(ResumeDriveSource).values(**defaults).on_conflict_do_nothing(index_elements=["key"]))
    return await session.scalar(select(ResumeDriveSource).where(ResumeDriveSource.key == "primary").with_for_update().execution_options(populate_existing=True))


def check_generation(source, generation):
    if source.generation != generation:
        raise HTTPException(409, "Resume source settings changed; reload before retrying")


async def save_source(session, settings, data):
    source = await lock_source(session, settings, data.canonical_url)
    check_generation(source, data.expected_generation)
    file_id, url = canonical_source(data.canonical_url)
    if source.file_id != file_id:
        source.file_id, source.canonical_url = file_id, url
        source.latest_version_id = None
        source.status, source.last_error = "not_checked", None
        source.last_checked_at, source.last_changed_at = None, None
        source.file_name, source.last_downloaded_at = None, None
        source.source_modified_at, source.source_etag, source.drive_revision = None, None, None
    source.sync_enabled, source.interval_hours = data.sync_enabled, data.interval_hours
    source.generation += 1
    await session.flush()
    return await status(session, settings)


async def version_read(session, version):
    if version is None:
        return None
    review = await session.scalar(select(ResumeProfileReview).where(ResumeProfileReview.version_id == version.id))
    if review is None:
        raise HTTPException(503, "Resume review is incomplete; retry the interrupted sync")
    fields = {key: getattr(version, key) for key in ResumeVersionRead.model_fields if hasattr(version, key)}
    return ResumeVersionRead(**fields, review_status=review.status,
                             review_cycle=review.review_cycle,
                             candidate_profile_version=review.base_profile_version,
                             approved_profile_version=review.approved_profile_version)


async def status(session, settings):
    source = await session.get(ResumeDriveSource, "primary")
    latest = await session.get(DriveResumeVersion, source.latest_version_id) if source and source.latest_version_id else None
    active = await session.get(DriveResumeVersion, source.active_version_id) if source and source.active_version_id else None
    history = (await session.scalars(select(DriveResumeVersion).order_by(DriveResumeVersion.downloaded_at.desc()).limit(50))).all()
    heartbeat = await session.get(OwnerPreference, "resume_drive_scheduler")
    active_scheduler = False
    if heartbeat and heartbeat.value.get("expires_at"):
        active_scheduler = utc(datetime.fromisoformat(heartbeat.value["expires_at"])) > datetime.now(timezone.utc)
    configured = default_source(settings) if source is None and settings.CANDIDATE_RESUME_DRIVE_URL else {}
    latest_read, active_read = await version_read(session, latest), await version_read(session, active)
    return SyncStatus(
        canonical_url=source.canonical_url if source else configured.get("canonical_url"),
        file_id=source.file_id if source else configured.get("file_id"),
        file_name=source.file_name if source else None,
        last_downloaded_at=source.last_downloaded_at if source else None,
        source_modified_at=source.source_modified_at if source else None,
        source_etag=source.source_etag if source else None,
        drive_revision=source.drive_revision if source else None,
        generation=source.generation if source else 1,
        sync_enabled=source.sync_enabled if source else settings.RESUME_DRIVE_SYNC_ENABLED,
        interval_hours=source.interval_hours if source else settings.RESUME_DRIVE_SYNC_INTERVAL_HOURS,
        connected=bool(latest and source.status not in {"not_checked", "failed"}),
        status=source.status if source else "not_checked",
        last_error=source.last_error if source else None,
        last_checked_at=source.last_checked_at if source else None,
        last_changed_at=source.last_changed_at if source else None,
        latest=latest_read, active=active_read,
        history=[await version_read(session, item) for item in history],
        pending_changes=bool(latest_read and (not active or active.id != latest.id)),
        scheduler_active=active_scheduler,
        scheduler_message=("Resume check worker heartbeat is current. Checks require owner opt-in."
                           if active_scheduler else "Automatic periodic checking is inactive. Deploy and run the resume check worker; the enabled flag alone does not run a job."),
    )


def require_cipher():
    try:
        return cipher()
    except ValueError:
        raise HTTPException(503, "The configured resume encryption key is invalid") from None
