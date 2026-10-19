"""User reports and outcomes are explicit, audited, and never provider confirmations."""

from uuid import uuid4

from sqlalchemy import select

from backend.app.models.application_packet import (
    ApplicationEvent,
    ApplicationSubmissionEvidence,
)
from backend.app.schemas.applications import (
    ApplicationEventRead,
    PacketSnapshot,
    SubmissionRead,
)
from backend.app.services.applications.base import (
    ApplicationConflict,
    ApplicationInvalid,
)
from backend.app.services.applications.resume_selector import digest

POST_SUBMISSION = {
    "applied_manually",
    "application_rejected",
    "interview_scheduled",
    "offer_received",
}


class ApplicationTracker:
    def __init__(self, service):
        self.service, self.repo, self.session = service, service.repo, service.session

    async def report(self, packet_id, request):
        packet = await self.repo.get(packet_id, lock=True)
        request_hash = digest(
            {"packet_id": str(packet_id), **request.model_dump(mode="json")}
        )
        existing = await self.repo.submission(packet_id)
        if existing:
            if (
                existing.idempotency_key != request.idempotency_key
                or existing.request_hash != request_hash
            ):
                raise ApplicationConflict(
                    "Submission was already reported; reload the application history"
                )
            return SubmissionRead.model_validate(existing)
        if (
            request.human_confirmed is not True
            or request.confirmation
            != "I submitted this application on the official website"
        ):
            raise ApplicationInvalid(
                "Explicit human confirmation of actual external submission is required"
            )
        if packet.revision != request.expected_revision:
            raise ApplicationConflict(
                "Packet revision changed; reload before recording submission"
            )
        if packet.lifecycle_state in {
            "withdrawn",
            "abandoned",
            "provider_confirmed_submitted",
        }:
            raise ApplicationConflict("Closed packets cannot record a new submission")
        key_owner = await self.session.scalar(
            select(ApplicationSubmissionEvidence).where(
                ApplicationSubmissionEvidence.idempotency_key == request.idempotency_key
            )
        )
        if key_owner:
            raise ApplicationConflict("Submission key belongs to another application")
        previous = packet.lifecycle_state
        await self.repo.advance(packet, request.expected_revision)
        evidence = ApplicationSubmissionEvidence(
            id=uuid4(),
            packet_id=packet.id,
            packet_revision=packet.revision,
            confirmation_source="user_reported",
            receipt_reference=request.receipt_reference,
            evidence_confidence="self_reported_unverified",
            human_confirmed=True,
            idempotency_key=request.idempotency_key,
            request_hash=request_hash,
        )
        self.session.add(evidence)
        await self.session.flush()
        packet.lifecycle_state, packet.tracking_state = (
            "user_reported_submitted",
            "applied_manually",
        )
        packet.readiness_state = "completed_by_user"
        # Deliberately keep Job.status unchanged. This is a separate, auditable self-report.
        await self.session.flush()
        self.repo.event(
            packet,
            "user_reported_submission",
            previous,
            evidence_id=evidence.id,
            note=request.note,
        )
        await self.session.flush()
        return SubmissionRead.model_validate(evidence)

    async def track(self, packet_id, request):
        packet = await self.repo.get(packet_id, lock=True)
        if packet.revision != request.expected_revision:
            raise ApplicationConflict(
                "Packet revision changed; reload before updating tracking"
            )
        submitted = await self.repo.submission(packet_id) is not None
        if request.tracking_state in POST_SUBMISSION and not submitted:
            raise ApplicationConflict(
                "Record actual manual submission explicitly before a post-submission outcome"
            )
        if submitted and request.tracking_state in {
            "not_applied",
            "application_incomplete",
        }:
            raise ApplicationConflict(
                "An outcome cannot erase existing submission evidence"
            )
        if request.lifecycle_state == "external_application_opened":
            from backend.app.services.applications.review import ApplicationReview

            await ApplicationReview(self.service).handoff(packet_id)
        if (
            packet.lifecycle_state in {"withdrawn", "abandoned"}
            and request.lifecycle_state
        ):
            raise ApplicationConflict("Closed application lifecycle cannot be reopened")
        if request.lifecycle_state == "withdrawn" and not submitted:
            raise ApplicationConflict(
                "Only a submitted application can be withdrawn; use abandoned for a draft"
            )
        previous = packet.lifecycle_state
        # Tracking changes do not change any approved field, resume or destination. The
        # audit explicitly carries the unchanged approval forward to the next revision.
        stale_approval = False
        if packet.approved_revision:
            _, _, current = await self.service.builder.context(
                packet.job_id, packet.resume_resource_id, lock=True
            )
            stale_approval = (
                current.context_digest
                != PacketSnapshot.model_validate(packet.snapshot).context_digest
            )
        await self.repo.advance(
            packet, request.expected_revision, preserve_approval=not stale_approval
        )
        if stale_approval:
            packet.lifecycle_state = "needs_input"
            packet.readiness_state = "needs_review"
        if request.tracking_state:
            packet.tracking_state = request.tracking_state
        if request.lifecycle_state:
            packet.lifecycle_state = request.lifecycle_state
        if packet.lifecycle_state in {"withdrawn", "abandoned"}:
            packet.approved_revision = None
        await self.session.flush()
        self.repo.event(packet, "tracking_updated", previous, note=request.note)
        await self.session.flush()
        return await self.service.read(packet_id)

    async def events(self, packet_id, *, offset=0, limit=50):
        await self.repo.get(packet_id)
        events = (
            await self.session.scalars(
                select(ApplicationEvent)
                .where(ApplicationEvent.packet_id == packet_id)
                .order_by(
                    ApplicationEvent.packet_revision,
                    ApplicationEvent.created_at,
                    ApplicationEvent.id,
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return [ApplicationEventRead.model_validate(e) for e in events]
