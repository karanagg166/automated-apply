"""Atomic byte-version detection and pending reviews. Never writes verified facts."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from sqlalchemy import select

from backend.app.core.config import get_settings
from backend.app.dashboard.models import (
    Notification,
    NotificationDelivery,
    PrivateResume,
)
from backend.app.repositories.candidate_profile import CandidateProfileRepository
from backend.app.resume_sync.download import ERRORS, fetch_pdf
from backend.app.resume_sync.download_worker import DownloadError
from backend.app.resume_sync.facts import differences, extract_facts
from backend.app.resume_sync.models import DriveResumeVersion, ResumeProfileReview
from backend.app.resume_sync.store import (
    check_generation,
    lock_source,
    require_cipher,
    status,
    utc,
)
from backend.app.schemas.candidate_profile import CandidateProfileCreate
from backend.app.services.discovery_budget import insert_for


def read_review(review, encryption):
    try:
        return json.loads(encryption.decrypt(review.review_ciphertext))
    except (InvalidToken, ValueError):
        raise HTTPException(503, "Private resume review cannot be decrypted; restore the original encryption key") from None


class ResumeSyncService:
    def __init__(self, session, settings=None, downloader=None, extractor=None):
        from backend.app.dashboard.resumes import extract_pdf

        self.session = session
        self.settings = settings or get_settings()
        self.downloader = downloader or fetch_pdf
        self.extractor = extractor or extract_pdf

    async def sync(self, expected_generation=None, *, scheduled=False):
        encryption = require_cipher()
        source = await lock_source(self.session, self.settings)
        if expected_generation is not None:
            check_generation(source, expected_generation)
        now = datetime.now(timezone.utc)
        if scheduled and (not source.sync_enabled or (source.last_checked_at and utc(source.last_checked_at) + timedelta(hours=source.interval_hours) > now)):
            return {"outcome": "disabled_or_not_due", "state": await status(self.session, self.settings)}
        source.last_checked_at = now
        try:
            downloaded = await self.downloader(source.file_id)
            digest = hashlib.sha256(downloaded.raw).hexdigest()
            version = await self.session.scalar(select(DriveResumeVersion).where(
                DriveResumeVersion.sha256 == digest))
            if version is not None:
                previous_id = source.latest_version_id or source.active_version_id
                changed = (source.latest_version_id or source.active_version_id) != version.id
                source.latest_version_id = version.id
                if changed:
                    source.last_changed_at = now
                elif source.last_changed_at is None:
                    source.last_changed_at = version.downloaded_at
                self.download_metadata(source, downloaded, now)
                source.status, source.last_error = "unchanged", None
                if changed and source.active_version_id != version.id:
                    await self.reopen_review(version, previous_id, encryption)
                    source.status = "pending_review"
                await self.session.flush()
                return {"outcome": "pending_review" if source.status == "pending_review" else "unchanged", "state": await status(self.session, self.settings)}
            extracted = await self.extractor(downloaded.raw)
        except DownloadError as exc:
            source.status, source.last_error = "failed", str(exc) if str(exc) in ERRORS else "bounded_network_check_failed"
            await self.session.flush()
            return {"outcome": "failed", "state": await status(self.session, self.settings)}
        except HTTPException as exc:
            if exc.status_code != 422:
                raise
            source.status, source.last_error = "failed", "malformed_or_unsafe_pdf"
            await self.session.flush()
            return {"outcome": "failed", "state": await status(self.session, self.settings)}
        facts = extract_facts(extracted["text"])
        self.download_metadata(source, downloaded, now)
        facts["sections"]["professional_links"] = sorted(set(facts["sections"]["professional_links"] + extracted.get("links", [])))[:100]
        previous = None
        previous_id = source.latest_version_id or source.active_version_id
        if previous_id:
            old_review = await self.session.scalar(select(ResumeProfileReview).where(ResumeProfileReview.version_id == previous_id))
            if old_review:
                previous = read_review(old_review, encryption)["facts"]
        profile = await CandidateProfileRepository(self.session).get_primary_profile()
        snapshot = CandidateProfileCreate.model_validate(profile).model_dump(mode="json") if profile else None
        private = PrivateResume(label=downloaded.file_name, ciphertext=encryption.encrypt(downloaded.raw), sha256=digest)
        self.session.add(private)
        await self.session.flush()
        version = DriveResumeVersion(
            file_id=source.file_id, canonical_url=source.canonical_url,
            file_name=downloaded.file_name, source_modified_at=downloaded.modified_at,
            source_etag=downloaded.etag, drive_revision=downloaded.drive_revision,
            sha256=digest, downloaded_at=now, private_resume_id=private.id,
        )
        self.session.add(version)
        await self.session.flush()
        payload = {"facts": facts, "previous_facts": previous, "profile_at_detection": snapshot,
                   "differences": differences(previous, facts, profile.verified_skills if profile else [], snapshot)}
        self.session.add(ResumeProfileReview(
            version_id=version.id, base_profile_version=profile.version if profile else None,
            review_ciphertext=encryption.encrypt(json.dumps(payload).encode()),
        ))
        source.latest_version_id, source.last_changed_at = version.id, now
        source.status, source.last_error = "pending_review", None
        await self.notify(version.id)
        await self.session.flush()
        return {"outcome": "pending_review", "state": await status(self.session, self.settings)}

    @staticmethod
    def download_metadata(source, downloaded, now):
        source.file_name, source.last_downloaded_at = downloaded.file_name, now
        source.source_modified_at, source.source_etag = downloaded.modified_at, downloaded.etag
        source.drive_revision = downloaded.drive_revision

    async def reopen_review(self, version, previous_id, encryption):
        review = await self.session.scalar(select(ResumeProfileReview).where(ResumeProfileReview.version_id == version.id))
        payload = read_review(review, encryption)
        if review.approved_at:
            payload.setdefault("approval_history", []).append({"profile_version": review.approved_profile_version, "approved_at": review.approved_at.isoformat()})
        previous = await self.session.scalar(select(ResumeProfileReview).where(ResumeProfileReview.version_id == previous_id)) if previous_id else None
        payload["previous_facts"] = read_review(previous, encryption)["facts"] if previous else None
        profile = await CandidateProfileRepository(self.session).get_primary_profile()
        payload["profile_at_detection"] = CandidateProfileCreate.model_validate(profile).model_dump(mode="json") if profile else None
        payload["differences"] = differences(payload["previous_facts"], payload["facts"], profile.verified_skills if profile else [], payload["profile_at_detection"])
        review.review_cycle += 1
        review.status, review.approved_at, review.approved_profile_version = "pending", None, None
        review.base_profile_version = profile.version if profile else None
        review.review_ciphertext = encryption.encrypt(json.dumps(payload).encode())
        await self.notify(version.id, review.review_cycle)

    async def notify(self, version_id, cycle=1):
        from backend.app.dashboard.notifications import notification_window, preferences

        if notification_window(await preferences(self.session)) != "available":
            return  # Saved-activity checks pick up the durable pending review later.
        # This records in-app availability only, with no external delivery attempt.
        result = await self.session.execute(insert_for(self.session)(Notification).values(
            dedup_key=f"resume_review:{version_id}:{cycle}", kind="resume_review",
            title="A resume version needs your review",
            body="Review the private PDF and profile differences before activating this version.", href="/profile",
        ).on_conflict_do_nothing(index_elements=["dedup_key"]).returning(Notification.id))
        notification_id = result.scalar_one_or_none()
        if notification_id:
            await self.session.execute(insert_for(self.session)(NotificationDelivery).values(
                notification_id=notification_id, channel="in_app", status="available_in_app", attempt_count=1,
            ).on_conflict_do_nothing(index_elements=["notification_id", "channel"]))
