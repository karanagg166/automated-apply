"""Public ATS discovery must feed the existing review/manual-handoff engine."""

import pytest
from sqlalchemy import func, select

from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.job import Job
from backend.app.schemas.applications import CreatePacket
from backend.app.services.applications.review import ApplicationReview
from backend.app.services.job_ingestion import JobIngestionService
from backend.app.services.job_sources.public_ats import AshbyAdapter, LeverAdapter
from backend.tests.phase5a_fakes import approve
from backend.tests.test_public_ats import configuration, posting

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    "adapter,region",
    [(LeverAdapter, "global"), (LeverAdapter, "eu"), (AshbyAdapter, "global")],
)
async def test_ats_ingestion_packet_review_handoff_and_replay(
    db_session, application_target, packet_service, adapter, region
):
    # The existing target fixture supplies the confirmed fictional canonical resume.
    raw = posting(adapter)
    if region == "eu":
        raw = {
            k: v.replace("jobs.lever.co", "jobs.eu.lever.co")
            if isinstance(v, str)
            else v
            for k, v in raw.items()
        }
    item = adapter(settings=configuration(LEVER_REGION=region)).parse(
        raw, "fictional", "Fictional Employer"
    )
    result = await JobIngestionService(db_session).ingest_jobs([item])
    await db_session.commit()
    from uuid import UUID

    job = await db_session.get(Job, UUID(result.job_ids[0]))
    request = CreatePacket(idempotency_key="fictional-public-ats-handoff")
    packet = await packet_service.create(job.id, request)
    assert (
        packet.snapshot.preparation_supported and packet.platform == adapter.source_name
    )
    assert (
        packet.snapshot.destination.valid
        and packet.snapshot.destination.source_confidence == "source_consistent"
    )
    assert packet.snapshot.resume.selected.resource_id == application_target[1].id
    packet = await approve(packet_service, packet)
    handoff = await ApplicationReview(packet_service).handoff(packet.id)
    assert handoff.application_url == item.application_url
    assert packet.tracking_state == "not_applied" and job.status == "discovered"
    replay = await packet_service.create(job.id, request)
    assert replay.id == packet.id and replay.revision == packet.revision
    assert (
        await db_session.scalar(select(func.count()).select_from(ApplicationPacket))
        == 1
    )
    assert not packet_service.builder.answers.answer_service.provider.calls


@pytest.mark.parametrize(
    "destination",
    [
        "https://jobs.lever.co/other/fictional-post-001/apply",
        "https://jobs.lever.co/fictional/other-job/apply",
        "https://jobs.eu.lever.co/fictional/fictional-post-001/apply",
        "https://jobs.lever.co/fictional/fictional-post-001/apply?redirect=evil",
        "https://employer.example/apply",
    ],
)
async def test_saved_ats_destination_cannot_switch_board_job_or_host(
    db_session, application_target, packet_service, destination
):
    job = application_target[0]
    job.source_platform, job.source_verification_status = "lever", "source_reported"
    job.job_url = posting(LeverAdapter)["hostedUrl"]
    job.application_url = destination
    await db_session.commit()
    preview = await packet_service.preview(job.id)
    assert not preview.snapshot.destination.valid
    assert preview.readiness.state == "needs_input"
