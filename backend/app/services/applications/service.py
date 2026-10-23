"""One application service shared by REST and read-only MCP; callers own commit/rollback."""

from sqlalchemy import select

from backend.app.models.application_packet import ApplicationPacket
from backend.app.repositories.application_packet import ApplicationPacketRepository
from backend.app.schemas.applications import (
    PacketList,
    PacketRead,
    PacketSnapshot,
    PrepareInput,
    QuestionInput,
)
from backend.app.services.application_answer_service import ApplicationAnswerService
from backend.app.services.applications.answer_builder import value_error
from backend.app.services.applications.base import (
    ApplicationConflict,
    ApplicationInvalid,
)
from backend.app.services.applications.eligibility import readiness
from backend.app.services.applications.packet_builder import PacketBuilder
from backend.app.services.applications.resume_selector import digest

TERMINAL = {
    "user_reported_submitted",
    "provider_confirmed_submitted",
    "submitting",
    "submission_unknown",
    "withdrawn",
    "abandoned",
}


class ApplicationPacketService:
    def __init__(self, session, answer_service=None):
        self.session = session
        self.repo = ApplicationPacketRepository(session)
        self.builder = PacketBuilder(
            session, answer_service or ApplicationAnswerService(session)
        )

    def capabilities(self):
        return [p.capabilities() for p in self.builder.platforms]

    async def preview(self, job_id, request=None):
        return await self.builder.preview(job_id, request or PrepareInput())

    async def create(self, job_id, request):
        # Check durable keys before building the current snapshot: retries return the exact
        # original packet even if saved facts changed since the first request.
        _, profile, _ = await self.builder.context(job_id)
        if profile is None:
            raise ApplicationInvalid(
                "Save a candidate profile before persisting an application packet"
            )
        request_hash = digest(
            {"job_id": str(job_id), **request.model_dump(mode="json")}
        )
        existing = await self.repo.existing(request.idempotency_key, job_id, profile.id)
        if existing:
            return await self._replay(existing, request, request_hash)
        preview = await self.preview(job_id, request)
        packet = await self.repo.insert(
            dict(
                job_id=job_id,
                candidate_profile_id=profile.id,
                candidate_profile_version=profile.version,
                resume_resource_id=preview.snapshot.resume.selected.resource_id
                if preview.snapshot.resume.selected
                else None,
                application_url=preview.snapshot.destination.application_url,
                platform=preview.snapshot.platform or "unsupported",
                lifecycle_state="created",
                tracking_state="not_applied",
                revision=1,
                readiness_state=preview.readiness.state,
                idempotency_key=request.idempotency_key,
                request_hash=request_hash,
                snapshot=preview.snapshot.model_dump(mode="json"),
            )
        )
        if packet is None:
            return await self._replay(
                await self.repo.existing(request.idempotency_key, job_id, profile.id),
                request,
                request_hash,
            )
        for position, field in enumerate(preview.fields):
            self.repo.add_field(packet.id, field, position)
        await self.session.flush()
        self.repo.event(packet, "packet_created", None)
        await self.session.flush()
        return await self.read(packet.id)

    async def _replay(self, existing, request, request_hash):
        matches = [
            p
            for p in existing
            if p.idempotency_key == request.idempotency_key
            and p.request_hash == request_hash
        ]
        if len(matches) != 1:
            raise ApplicationConflict(
                "Idempotency key or candidate/job already belongs to a different packet request"
            )
        return await self.read(matches[0].id)

    async def read(self, packet_id, *, lock_context=False):
        packet = await self.repo.get(packet_id, consistent=True)
        snapshot = PacketSnapshot.model_validate(packet.snapshot)
        _, profile, current = await self.builder.context(
            packet.job_id, packet.resume_resource_id, lock=lock_context
        )
        stale = (
            current.context_digest != snapshot.context_digest
            or profile is None
            or profile.id != packet.candidate_profile_id
        )
        fields = [self.repo.field_read(f) for f in await self.repo.fields(packet_id)]
        submitted = await self.repo.submission(packet_id) is not None
        eligible = readiness(
            snapshot,
            fields,
            stale=stale,
            approved=packet.approved_revision == packet.revision,
            submitted=submitted,
        )
        if packet.lifecycle_state in {"abandoned", "withdrawn"} and not submitted:
            eligible.state, eligible.blockers = (
                "manual_action_required",
                ["This packet is closed; no handoff is available"],
            )
        if packet.lifecycle_state == "provider_confirmed_submitted":
            eligible.state = "completed_verified"
            eligible.warnings = [w for w in eligible.warnings if "self-reported" not in w]
        if packet.lifecycle_state in {"submitting", "submission_unknown"}:
            eligible.state = "manual_action_required"
            eligible.blockers = ["Submission outcome must be reconciled; never resubmit this application"]
        return PacketRead(
            id=packet.id,
            job_id=packet.job_id,
            candidate_profile_id=packet.candidate_profile_id,
            candidate_profile_version=packet.candidate_profile_version,
            platform=packet.platform,
            snapshot=snapshot,
            fields=fields,
            readiness=eligible,
            lifecycle_state=packet.lifecycle_state,
            tracking_state=packet.tracking_state,
            revision=packet.revision,
            approved_revision=packet.approved_revision,
            review_status="stale"
            if stale
            else "approved"
            if packet.approved_revision
            else "reviewed"
            if packet.lifecycle_state == "reviewed"
            else "pending",
            created_at=packet.created_at,
            updated_at=packet.updated_at,
        )

    async def list(
        self, *, offset=0, limit=25, platform=None, job_id=None, status=None
    ):
        query = select(ApplicationPacket.id)
        for column, value in [
            (ApplicationPacket.platform, platform),
            (ApplicationPacket.job_id, job_id),
            (ApplicationPacket.lifecycle_state, status),
        ]:
            if value is not None:
                query = query.where(column == value)
        ids = (
            await self.session.scalars(
                query.order_by(
                    ApplicationPacket.created_at.desc(), ApplicationPacket.id
                )
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return PacketList(
            packets=[await self.read(i) for i in ids], offset=offset, limit=limit
        )

    async def locked(self, packet_id, expected_revision, *, editable=True, fresh=True):
        packet = await self.repo.get(packet_id, lock=True)
        if packet.revision != expected_revision:
            raise ApplicationConflict(
                "Packet revision changed; reload it before retrying"
            )
        if editable and packet.lifecycle_state in TERMINAL:
            raise ApplicationConflict("Closed or submitted packets cannot be edited")
        _, profile, current = await self.builder.context(
            packet.job_id, packet.resume_resource_id, lock=True
        )
        if profile is None or profile.id != packet.candidate_profile_id:
            raise ApplicationConflict("Saved candidate no longer matches this packet")
        if (
            fresh
            and current.context_digest
            != PacketSnapshot.model_validate(packet.snapshot).context_digest
        ):
            raise ApplicationConflict(
                "Saved evidence changed; refresh the packet before editing or reviewing"
            )
        return packet, profile, current

    async def finish(self, packet, previous, event_type, *, note=None):
        await self.session.flush()
        fields = [self.repo.field_read(f) for f in await self.repo.fields(packet.id)]
        eligible = readiness(PacketSnapshot.model_validate(packet.snapshot), fields)
        packet.lifecycle_state = (
            "needs_input"
            if eligible.state in {"needs_input", "needs_resume", "unsupported"}
            else "ready_for_review"
        )
        packet.readiness_state = eligible.state
        await self.session.flush()
        self.repo.event(packet, event_type, previous, note=note)
        await self.session.flush()
        return await self.read(packet.id)

    async def edit(self, packet_id, request):
        if (
            not request.refresh_saved_data
            and "resume_resource_id" not in request.model_fields_set
        ):
            raise ApplicationInvalid("Select a resume or request refresh_saved_data")
        packet, profile, _ = await self.locked(
            packet_id, request.expected_revision, fresh=False
        )
        fields = await self.repo.fields(packet.id)
        if any(item.field_type == "multi_select" for item in fields):
            from backend.app.services.applications.multi_select import require_available

            await require_available(self.session)
        previous = packet.lifecycle_state
        selected = (
            request.resume_resource_id
            if "resume_resource_id" in request.model_fields_set
            else packet.resume_resource_id
        )
        _, _, snapshot = await self.builder.context(packet.job_id, selected, lock=True)
        await self.repo.advance(packet, request.expected_revision)
        packet.snapshot = snapshot.model_dump(mode="json")
        packet.platform = snapshot.platform or "unsupported"
        packet.resume_resource_id = (
            snapshot.resume.selected.resource_id if snapshot.resume.selected else None
        )
        packet.application_url = snapshot.destination.application_url
        packet.candidate_profile_version = profile.version
        await self.session.flush()
        for item in fields:
            prior = self.repo.field_read(item)
            # Refresh deterministic facts; invalidate all narratives and human edits to avoid
            # silently retaining claims based on old candidate evidence.
            rebuilt = await self.builder.answers.build(
                QuestionInput.model_validate(
                    prior.model_dump(include=set(QuestionInput.model_fields))
                ),
                packet.job_id,
                profile,
                origin=prior.provenance.origin,
                resume=snapshot.resume,
            )
            item.proposed_answer, item.human_answer = rebuilt.proposed_answer, None
            item.provenance, item.validation_status = (
                rebuilt.provenance.model_dump(mode="json"),
                rebuilt.validation_status,
            )
            item.missing_information, item.requires_review = (
                rebuilt.missing_information,
                rebuilt.requires_review,
            )
            item.review_status, item.answer_revision = (
                "pending",
                item.answer_revision + 1,
            )
        return await self.finish(packet, previous, "packet_refreshed")

    async def add_questions(self, packet_id, request):
        if any(question.field_type == "multi_select" for question in request.questions):
            from backend.app.services.applications.multi_select import require_available

            await require_available(self.session)
        packet, profile, _ = await self.locked(packet_id, request.expected_revision)
        fields = await self.repo.fields(packet_id)
        if len(fields) + len(request.questions) > 100:
            raise ApplicationInvalid(
                "A packet supports at most 100 checklist and screening fields"
            )
        previous = packet.lifecycle_state
        await self.repo.advance(packet, request.expected_revision)
        for i, question in enumerate(request.questions, len(fields)):
            self.repo.add_field(
                packet_id,
                await self.builder.answers.build(
                    question,
                    packet.job_id,
                    profile,
                    resume=PacketSnapshot.model_validate(packet.snapshot).resume,
                ),
                i,
            )
        return await self.finish(packet, previous, "questions_added")

    async def generate(self, packet_id, field_id, request):
        # Do not hold a packet write claim while the quota manager commits its independent
        # reservation. Check the revision/evidence again after the bounded provider call.
        packet = await self.repo.get(packet_id)
        if (
            packet.revision != request.expected_revision
            or packet.lifecycle_state in TERMINAL
        ):
            raise ApplicationConflict("Packet changed or is closed")
        item = await self.repo.field(packet_id, field_id)
        _, profile, context = await self.builder.context(
            packet.job_id, packet.resume_resource_id
        )
        if (
            context.context_digest
            != PacketSnapshot.model_validate(packet.snapshot).context_digest
        ):
            raise ApplicationConflict("Saved evidence changed; refresh this packet")
        prior = self.repo.field_read(item)
        if prior.field_type == "multi_select":
            from backend.app.services.applications.multi_select import require_available

            await require_available(self.session)
        result = await self.builder.answers.build(
            QuestionInput.model_validate(
                prior.model_dump(include=set(QuestionInput.model_fields))
            ),
            packet.job_id,
            profile,
            generate=True,
            origin=prior.provenance.origin,
            resume=context.resume,
        )
        packet, _, _ = await self.locked(packet_id, request.expected_revision)
        previous = packet.lifecycle_state
        await self.repo.advance(packet, request.expected_revision)
        item.proposed_answer, item.human_answer = result.proposed_answer, None
        item.provenance, item.validation_status = (
            result.provenance.model_dump(mode="json"),
            result.validation_status,
        )
        item.missing_information, item.requires_review = (
            result.missing_information,
            result.requires_review,
        )
        item.review_status, item.answer_revision = "pending", item.answer_revision + 1
        return await self.finish(packet, previous, "answer_generated")

    async def edit_answer(self, packet_id, field_id, request):
        packet, _, _ = await self.locked(packet_id, request.expected_revision)
        item = await self.repo.field(packet_id, field_id)
        field = self.repo.field_read(item)
        if field.field_type == "multi_select":
            from backend.app.services.applications.multi_select import require_available

            await require_available(self.session)
        if (
            field.field_type == "file"
            or field.validation_status == "file_upload_required"
        ):
            raise ApplicationInvalid(
                "An answer cannot attest to a portal file upload; upload the file on the official website"
            )
        error = value_error(field, request.answer)
        if error:
            raise ApplicationInvalid(error)
        previous = packet.lifecycle_state
        await self.repo.advance(packet, request.expected_revision)
        item.human_answer = request.answer
        item.provenance = {**item.provenance, "source": "human", "resolver": "human"}
        item.validation_status, item.review_status, item.requires_review = (
            "draft_ready",
            "pending",
            True,
        )
        item.missing_information, item.answer_revision = [], item.answer_revision + 1
        return await self.finish(packet, previous, "answer_edited")
