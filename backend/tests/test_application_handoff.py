"""Copyable approved packets have no implicit browser or submission side effect."""

import pytest

from backend.app.models.job import Job
from backend.app.services.applications.review import ApplicationReview
from backend.tests.phase5a_fakes import approve, create


@pytest.mark.asyncio
async def test_handoff_exact_approved_fields_preserved(
    packet_service, application_target, db_session
):
    job, resume = application_target
    packet = await approve(packet_service, await create(packet_service, job))
    handoff = await ApplicationReview(packet_service).handoff(packet.id)
    assert handoff.fields == packet.fields
    assert handoff.resume.selected.resource_id == resume.id
    assert handoff.application_url == "https://circuit.example.org/careers/backend"
    assert handoff.professional_links["github"] == "https://github.com/example"
    assert handoff.submitted is False and handoff.submission_mode == "manual_handoff"
    assert (await packet_service.read(packet.id)).revision == packet.revision
    assert (await db_session.get(Job, job.id)).status == "discovered"
