"""Transaction-neutral packet persistence with database uniqueness and revision CAS."""

from datetime import datetime, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from backend.app.models.application_packet import (
    ApplicationEvent,
    ApplicationPacket,
    ApplicationPacketField,
    ApplicationSubmissionEvidence,
)
from backend.app.schemas.applications import PacketField
from backend.app.services.applications.base import (
    ApplicationConflict,
    ApplicationNotFound,
)


class ApplicationPacketRepository:
    def __init__(self, session):
        self.session = session

    async def get(self, packet_id, *, lock=False, consistent=False):
        query = (
            select(ApplicationPacket)
            .where(ApplicationPacket.id == packet_id)
            .execution_options(populate_existing=True)
        )
        if lock:
            query = query.with_for_update()
        elif consistent:
            # Hold a shared parent lock until the caller's transaction ends so a read
            # cannot mix an approved parent revision with concurrently edited fields.
            query = query.with_for_update(read=True)
        packet = await self.session.scalar(query)
        if packet is None:
            raise ApplicationNotFound("Application packet not found")
        return packet

    async def fields(self, packet_id):
        return list(
            (
                await self.session.scalars(
                    select(ApplicationPacketField)
                    .where(ApplicationPacketField.packet_id == packet_id)
                    .order_by(ApplicationPacketField.position)
                    .execution_options(populate_existing=True)
                )
            ).all()
        )

    async def field(self, packet_id, field_id):
        field = await self.session.scalar(
            select(ApplicationPacketField).where(
                ApplicationPacketField.packet_id == packet_id,
                ApplicationPacketField.id == field_id,
            )
        )
        if field is None:
            raise ApplicationNotFound(
                "Question does not belong to this application packet"
            )
        return field

    async def insert(self, values):
        insert = (
            pg_insert
            if self.session.get_bind().dialect.name == "postgresql"
            else sqlite_insert
        )
        return await self.session.scalar(
            insert(ApplicationPacket)
            .values(**values)
            .on_conflict_do_nothing()
            .returning(ApplicationPacket)
        )

    async def existing(self, key, job_id, profile_id):
        return list(
            (
                await self.session.scalars(
                    select(ApplicationPacket).where(
                        or_(
                            ApplicationPacket.idempotency_key == key,
                            (ApplicationPacket.job_id == job_id)
                            & (ApplicationPacket.candidate_profile_id == profile_id),
                        )
                    )
                )
            ).all()
        )

    async def advance(self, packet, expected_revision, *, preserve_approval=False):
        result = await self.session.execute(
            update(ApplicationPacket)
            .where(
                ApplicationPacket.id == packet.id,
                ApplicationPacket.revision == expected_revision,
            )
            .values(
                revision=expected_revision + 1,
                approved_revision=expected_revision + 1
                if preserve_approval and packet.approved_revision
                else None,
                lifecycle_state=packet.lifecycle_state
                if preserve_approval
                else "preparing",
                updated_at=datetime.now(timezone.utc),
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise ApplicationConflict(
                "Packet revision changed; reload it before retrying"
            )
        await self.session.refresh(packet)

    def add_field(self, packet_id, field, position):
        item = ApplicationPacketField(
            packet_id=packet_id,
            position=position,
            **field.model_dump(mode="json", exclude={"effective_answer"}),
        )
        # UUID columns use UUID objects, not client metadata or nested ORM values.
        item.id = field.id
        self.session.add(item)
        return item

    def event(self, packet, event_type, previous_state, *, note=None, evidence_id=None):
        self.session.add(
            ApplicationEvent(
                packet_id=packet.id,
                event_type=event_type,
                previous_state=previous_state,
                next_state=packet.lifecycle_state,
                packet_revision=packet.revision,
                origin="owner_rest",
                evidence_id=evidence_id,
                note=note,
            )
        )

    async def submission(self, packet_id):
        return await self.session.scalar(
            select(ApplicationSubmissionEvidence).where(
                ApplicationSubmissionEvidence.packet_id == packet_id
            )
        )

    @staticmethod
    def field_read(item):
        field = PacketField.model_validate(item)
        field.effective_answer = (
            item.human_answer if item.human_answer is not None else item.proposed_answer
        )
        return field
