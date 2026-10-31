"""Fictional bulk discovery regression: bounded SQL, durable replay fences."""

from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.agent.tools import ToolDenied
from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import application_queue as queue
from backend.app.models.application_packet import ApplicationPacket
from backend.app.models.job import Job
from backend.tests.test_application_queue import running


def url(req, slug="fictional"):
    return f"https://www.naukri.com/job-listings-{slug}-{req}"


async def test_bulk_publication_preserves_identity_and_outbox_on_duplicate_reports(db_session):
    await running(db_session)
    first = [url(str(291026110000 + i)) for i in range(20)]
    assert await queue.enqueue_batch(db_session, first, "naukri_ui_search") == 20
    await db_session.commit()
    assert await queue.enqueue_batch(db_session, [x.replace("fictional", "new-slug") for x in first], "naukri_ui_search") == 0
    assert len(await queue.items(db_session)) == 20
    events = (await db_session.scalars(select(OwnerPreference).where(OwnerPreference.key.startswith(queue.EVENT)))).all()
    assert len(events) == 20 and all(row.value["event"] == "enqueued" for row in events)


async def test_bulk_never_replays_receipts_or_uncertain_packets(db_session, phase2_profile):
    await running(db_session)
    for prefix, req in [("naukri_receipt:", "291026110001"), ("naukri_worker_receipt:", "291026110002")]:
        db_session.add(OwnerPreference(key=prefix + req, value={"damaged_requires_reconciliation": True}))
    job = Job(id=uuid4(), title="Fictional", source_platform="naukri", job_url=url("291026110003", "historical-slug"), status="new")
    db_session.add(job)
    await db_session.flush()
    db_session.add(ApplicationPacket(job_id=job.id, candidate_profile_id=phase2_profile.id,
                                    candidate_profile_version=phase2_profile.version, platform="naukri",
                                    lifecycle_state="submission_unknown", readiness_state="needs_review",
                                    idempotency_key="fictional-uncertain-batch", request_hash="a" * 64, snapshot={}))
    await db_session.commit()
    urls = [url(str(291026110001 + i)) for i in range(4)]
    assert await queue.enqueue_batch(db_session, urls, "naukri_ui_search") == 1
    assert [r.value["requisition"] for r in await queue.items(db_session)] == ["291026110004"]


async def test_bulk_capacity_and_invalid_urls_do_not_create_partial_invalid_work(db_session):
    current = await running(db_session)
    current["policy"]["max_pending"] = 2
    await queue.put(db_session, queue.POLICY_KEY, current)
    urls = ["https://attacker.example/job-listings-invalid-291026110000", url("291026110001"),
            url("291026110001", "same-identity"), url("291026110002"), url("291026110003")]
    assert await queue.enqueue_batch(db_session, urls, "naukri_ui_search") == 2
    assert len(await queue.items(db_session)) == 2
    with pytest.raises(ToolDenied, match="bounded_supported_queue_batch"):
        await queue.enqueue_batch(db_session, [url("291026110004")] * 21, "naukri_ui_search")


async def test_twenty_candidates_have_constant_database_round_trips(db_session, record_property):
    await running(db_session)
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    counts = []
    statements = []

    def count(*args):
        statements.append(1)

    event.listen(db_session.bind.sync_engine, "before_cursor_execute", count)
    try:
        for size, base in [(1, 291026120000), (20, 291026130000)]:
            statements.clear()
            async with factory() as session, session.begin():
                assert await queue.enqueue_batch(session, [url(str(base + i)) for i in range(size)], "naukri_ui_search") == size
            counts.append(len(statements))
    finally:
        event.remove(db_session.bind.sync_engine, "before_cursor_execute", count)
    record_property("one_candidate_sql", counts[0])
    record_property("twenty_candidate_sql", counts[1])
    assert counts[1] <= counts[0] + 2, counts


async def test_bulk_stop_preserves_unknown_writes_and_transactional_events(db_session, record_property):
    await running(db_session)
    await queue.enqueue_batch(db_session, [url(str(291026140000 + i)) for i in range(20)], "naukri_ui_search")
    rows = await queue.items(db_session)
    rows[0].value = {**rows[0].value, "status": "executing", "operation": "apply"}
    rows[1].value = {**rows[1].value, "status": "unknown", "stage": "SUBMISSION_UNKNOWN"}
    await db_session.commit()
    statements = []
    def count(*args):
        statements.append(1)
    event.listen(db_session.bind.sync_engine, "before_cursor_execute", count)
    try:
        await queue.fence(db_session, "global_stop")
        await db_session.commit()
    finally:
        event.remove(db_session.bind.sync_engine, "before_cursor_execute", count)
    record_property("twenty_item_stop_sql", len(statements))
    assert len(statements) <= 8, len(statements)
    saved = [row.value for row in await queue.items(db_session)]
    assert sum(v["stage"] == "SUBMISSION_UNKNOWN" for v in saved) == 2
    assert sum(v["stage"] == "PAUSED" for v in saved) == 18
    events = (await db_session.scalars(select(OwnerPreference).where(OwnerPreference.key.startswith(queue.EVENT)))).all()
    assert sum(e.value["event"] == "fenced" for e in events) == 19
