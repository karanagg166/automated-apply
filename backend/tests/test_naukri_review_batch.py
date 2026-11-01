"""Bounded dashboard reads preserve packet/receipt/requisition replay evidence."""

from uuid import uuid4

import pytest
from sqlalchemy import event

from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import store
from backend.app.execution.naukri_review import review_jobs
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.company import Company
from backend.app.models.job import Job


@pytest.mark.asyncio
async def test_review_batch_matches_individual_replay_guards_with_constant_queries(
    db_session, phase2_profile,
):
    company = Company(name="Fictional Batch", domain="batch.example.org")
    db_session.add(company)
    await db_session.flush()
    jobs = [Job(
        title="Backend Developer", company_id=company.id,
        job_url=f"https://www.naukri.com/job-listings-fictional-batch-{281026100000 + i}",
        source_platform="naukri", location="India", skills_required=["Python"],
        description="Fictional Python backend", status="discovered",
    ) for i in range(30)]
    db_session.add_all(jobs)
    await db_session.flush()
    for i, state in enumerate([
        "user_reported_submitted", "provider_confirmed_submitted", "submitting", "submission_unknown",
    ]):
        db_session.add(ApplicationPacket(
            job_id=jobs[i].id, candidate_profile_id=phase2_profile.id,
            candidate_profile_version=phase2_profile.version, platform="naukri",
            lifecycle_state=state, readiness_state="needs_review", idempotency_key=str(uuid4()),
            request_hash="a" * 64, snapshot={},
        ))
    # A changed slug for the same requisition must retain the packet fence.
    alias = Job(
        title="Backend Developer", company_id=company.id,
        job_url=jobs[2].job_url.replace("fictional-batch", "different-slug"),
        source_platform="naukri", skills_required=["Python"], status="discovered",
    )
    db_session.add(alias)
    for i, prefix in [(5, "naukri_receipt:"), (6, "naukri_worker_receipt:")]:
        db_session.add(OwnerPreference(key=prefix + jobs[i].job_url.rsplit("-", 1)[-1], value={"damaged": True}))
    jobs[7].status = "applied"
    jobs[8].discovery_metadata = {"data_provenance": {"posting_status": "already_applied"}}
    await db_session.flush()
    valid = [*jobs, alias]
    expected = {str(j.id): await store.previously_applied(db_session, j) for j in valid}
    invalid = Job(title="Invalid", job_url="https://example.org/invalid", source_platform="naukri", status="discovered")
    db_session.add(invalid)
    await db_session.flush()
    queries = []
    def count(_connection, _cursor, statement, _parameters, _context, _many):
        queries.append(statement)
    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", count)
    try:
        result = await review_jobs(db_session, [*valid, invalid])
    finally:
        event.remove(engine, "before_cursor_execute", count)
    assert len(queries) == 5  # Companies, packets, receipt keys, profile, confirmation.
    assert all((v["vacancy_review"] == "already_applied") == expected[v["id"]] for v in result[:-1])
    assert result[-1]["reason"] == "invalid_requisition_identity"
    assert all(v["submission_allowed"] is False for v in result)
