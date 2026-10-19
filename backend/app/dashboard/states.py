"""Submission evidence, not packet preparation or URL visits, means applied."""

from sqlalchemy import select

from backend.app.models.application_packet import ApplicationPacket

SUBMITTED = {"user_reported_submitted", "provider_confirmed_submitted"}


def matches_status(job, packet, status):
    submitted = bool(packet and packet.lifecycle_state in SUBMITTED)
    # Preserve independently recorded legacy applied jobs.
    submitted = submitted or job.status == "applied"
    if status == "not_applied":
        return not submitted
    if status == "applied":
        return submitted
    if status == "packet_prepared":
        return packet is not None and not submitted
    if status == "shortlisted":
        return job.status == "shortlisted"
    if status == "interview":
        return bool(packet and packet.tracking_state == "interview_scheduled")
    if status == "rejected":
        return job.status == "rejected" or bool(
            packet and packet.tracking_state == "application_rejected"
        )
    return True


async def packet_map(session, job_ids=None):
    statement = select(
        ApplicationPacket.job_id,
        ApplicationPacket.lifecycle_state,
        ApplicationPacket.tracking_state,
    )
    if job_ids is not None:
        statement = statement.where(ApplicationPacket.job_id.in_(job_ids))
    return {p.job_id: p for p in (await session.execute(statement)).all()}
