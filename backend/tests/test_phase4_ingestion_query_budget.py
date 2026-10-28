"""Bound URL resolution round trips without changing conservative identity priority."""

from sqlalchemy import event

from backend.app.models.job import Job
from backend.app.schemas.normalized_job import NormalizedJob
from backend.app.services.job_deduplication import JobDeduplication


async def test_new_posting_url_resolution_needs_at_most_two_database_reads(db_session):
    statements = []
    engine = db_session.get_bind()

    def observe(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        item = NormalizedJob(
            source_name="manual", source_job_id="new-round-trip-budget",
            original_url="https://fictional.example/jobs/new", title="Engineer",
        )
        job, reason, possible = await JobDeduplication(db_session).resolve(item, None)
        assert job is None and reason == "new" and possible == []
        assert len(statements) <= 2
    finally:
        event.remove(engine, "before_cursor_execute", observe)


async def test_exact_url_still_precedes_legacy_normalization(db_session):
    canonical = "https://fictional.example/jobs/priority"
    exact = Job(
        title="Exact owner-reviewed posting", job_url=canonical,
        canonical_key=canonical, source_platform="manual", status="applied",
    )
    legacy = Job(
        title="Legacy posting", job_url=canonical + "?utm_source=legacy",
        canonical_key=None, source_platform="manual", status="shortlisted",
    )
    db_session.add_all([legacy, exact])
    await db_session.flush()
    item = NormalizedJob(source_name="manual", original_url=canonical, title="Engineer")
    job, reason, _ = await JobDeduplication(db_session).resolve(item, None)
    assert job.id == exact.id and reason == "canonical_url"
    assert job.status == "applied"
    await db_session.delete(exact)
    await db_session.flush()
    job, reason, _ = await JobDeduplication(db_session).resolve(item, None)
    assert job.id == legacy.id and reason == "legacy_canonical_url"
    assert job.status == "shortlisted"
