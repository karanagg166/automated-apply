"""Revision-specific human review and copy-ready handoff, without external actions."""

from backend.app.schemas.applications import Handoff, PacketSnapshot
from backend.app.services.applications.base import (
    ApplicationConflict,
    ApplicationInvalid,
)
from backend.app.services.applications.eligibility import readiness
from backend.app.services.applications.service import TERMINAL


class ApplicationReview:
    def __init__(self, service):
        self.service, self.repo, self.session = service, service.repo, service.session

    async def review(self, packet_id, request):
        packet, _, _ = await self.service.locked(packet_id, request.expected_revision)
        items = await self.repo.fields(packet_id)
        field_ids = {f.id for f in items}
        if (
            len(set(request.reviewed_field_ids)) != len(request.reviewed_field_ids)
            or set(request.reviewed_field_ids) - field_ids
        ):
            raise ApplicationInvalid(
                "Review IDs must be unique questions belonging to this packet"
            )
        fields = [self.repo.field_read(f) for f in items]
        for field in fields:
            if field.id in request.reviewed_field_ids:
                if (
                    not field.effective_answer
                    or field.validation_status != "draft_ready"
                ):
                    raise ApplicationInvalid(
                        "Only valid answered fields can be reviewed"
                    )
                field.review_status = "reviewed"
        eligible = readiness(
            PacketSnapshot.model_validate(packet.snapshot), fields, approved=True
        )
        if request.action == "approve":
            if not request.confirm_resume or not request.confirm_destination:
                raise ApplicationInvalid(
                    "Explicitly confirm the selected resume and saved application destination"
                )
            if eligible.state != "ready_for_manual_handoff":
                raise ApplicationConflict(
                    "Packet cannot be approved: " + "; ".join(eligible.blockers)
                )
        previous = packet.lifecycle_state
        await self.repo.advance(packet, request.expected_revision)
        for item in items:
            if item.id in request.reviewed_field_ids:
                item.review_status = "reviewed"
        # Field reviews must be durable before the database can validate approval.
        await self.session.flush()
        packet.lifecycle_state = (
            "approved_for_manual_handoff" if request.action == "approve" else "reviewed"
        )
        packet.approved_revision = (
            packet.revision if request.action == "approve" else None
        )
        packet.readiness_state = (
            "ready_for_manual_handoff"
            if request.action == "approve"
            else "needs_review"
        )
        await self.session.flush()
        self.repo.event(
            packet,
            "packet_approved" if request.action == "approve" else "packet_reviewed",
            previous,
        )
        await self.session.flush()
        return await self.service.read(packet_id)

    async def handoff(self, packet_id):
        packet = await self.service.read(packet_id, lock_context=True)
        if (
            packet.lifecycle_state in TERMINAL
            or packet.approved_revision != packet.revision
        ):
            raise ApplicationConflict(
                "Approve the current packet revision before manual handoff"
            )
        if (
            packet.readiness.state != "ready_for_manual_handoff"
            or packet.readiness.stale
        ):
            raise ApplicationConflict(
                "Packet is stale or incomplete; refresh, review and approve it"
            )
        return Handoff(
            packet_id=packet.id,
            revision=packet.revision,
            approved_revision=packet.approved_revision,
            company=packet.snapshot.company_name,
            job_title=packet.snapshot.job_title,
            application_url=packet.snapshot.destination.application_url,
            destination_kind=packet.snapshot.destination.kind,
            resume=packet.snapshot.resume,
            professional_links=packet.snapshot.professional_links,
            fields=packet.fields,
            manual_steps=packet.readiness.manual_steps,
            warnings=packet.readiness.warnings,
        )
