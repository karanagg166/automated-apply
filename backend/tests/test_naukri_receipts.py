"""Fictional retained UI observations; no live Naukri or employer confirmation."""

import copy
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.app.dashboard.models import OwnerPreference
from backend.app.execution import recurring, store
from backend.app.execution.naukri_receipts import PREFIX, summary
from backend.app.execution.worker import prepare
from backend.app.models.job import Job

REQUISITION = "291026123456"


def observation(**changes):
    return {
        "requisition": REQUISITION,
        "status": "Application Sent",
        "confirmation_source": "naukri_application_status_ui",
        "operation_mode": "owner_authorized_software_operated_ui",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "persistent_after_reload": True,
        "private_evidence_sha256": "a" * 64,
        "job_title": "Fictional Backend Developer",
        "hiring_company": "Fictional employer",
        "private_answer": "must never appear in aggregate status",
        **changes,
    }


async def test_retained_ui_receipt_counts_without_falsifying_packet_or_worker(db_session):
    receipt = OwnerPreference(key=PREFIX + REQUISITION, value=observation())
    db_session.add(receipt)
    await db_session.commit()
    original = copy.deepcopy(receipt.value)
    view = await recurring.status(db_session)
    assert view["counts"]["submitted_confirmed"] == view["counts"]["naukri_recorded"] == 1
    assert view["counts"]["installed_worker_recorded"] == 0
    assert view["counts"]["employer_acknowledged"] == view["counts"]["user_reported"] == 0
    assert view["application_receipts"]["live_reverified_by_this_read"] is False
    assert "private_answer" not in json.dumps(view)
    assert "private_evidence_sha256" not in json.dumps(view)
    assert receipt.value == original
    # Repeated status reads cannot manufacture another receipt or delivery.
    assert (await summary(db_session))["naukri_recorded"] == 1
    assert not db_session.dirty and not db_session.new


@pytest.mark.parametrize("changes", [
    {"status": "You have successfully applied"},
    {"status": "HTTP 200"},
    {"confirmation_source": "mock_employer"},
    {"confirmation_source": "user_reported"},
    {"operation_mode": "installed_recurring_worker"},
    {"persistent_after_reload": False},
    {"persistent_after_reload": "true"},
    {"private_evidence_sha256": ""},
    {"observed_at": "2026-01-01T12:00:00"},
    {"observed_at": "invalid"},
    {"observed_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()},
    {"requisition": "291026654321"},
])
async def test_incomplete_or_untrusted_observation_does_not_count_but_prevents_replay(db_session, changes):
    db_session.add(OwnerPreference(key=PREFIX + REQUISITION, value=observation(**changes)))
    await db_session.commit()
    counts = await summary(db_session)
    assert counts["naukri_recorded"] == 0 and counts["records_requiring_review"] == 1
    # Even a changed slug and lost local job.status cannot authorize another Apply.
    job = Job(title="Fictional renamed role", source_platform="naukri", status="discovered",
              job_url="https://www.naukri.com/job-listings-changed-slug-" + REQUISITION)
    db_session.add(job)
    await db_session.flush()
    assert await store.previously_applied(db_session, job)
    assert job.status == "discovered"  # Read model preserves original evidence.


async def test_receipt_dedup_is_exact_requisition_and_platform(db_session):
    db_session.add(OwnerPreference(key=PREFIX + REQUISITION, value=observation()))
    await db_session.commit()
    other_job = Job(title="Other fictional vacancy", source_platform="naukri", status="discovered",
                    job_url="https://www.naukri.com/job-listings-fictional-291026654321")
    db_session.add(other_job)
    await db_session.flush()
    assert not await store.previously_applied(db_session, other_job)
    other_job.source_platform = "fictional_fixture"
    other_job.job_url = "https://www.naukri.com/job-listings-fictional-" + REQUISITION
    await db_session.flush()
    assert not await store.previously_applied(db_session, other_job)


@pytest.mark.parametrize("persistent", [True, False])
async def test_restarted_worker_fences_retained_receipt_and_can_claim_another_job(db_session, phase2_profile, persistent):
    job = Job(title="Fictional Backend Developer", source_platform="naukri", status="discovered",
              job_url="https://www.naukri.com/job-listings-fictional-" + REQUISITION)
    db_session.add_all([job, OwnerPreference(key=PREFIX + REQUISITION,
                       value=observation(persistent_after_reload=persistent))])
    await db_session.commit()
    intent = (await store.start(db_session, [job.id]))[0]
    identity = await store.claim(db_session)
    await db_session.commit()
    # A fresh worker session uses the committed lease and persisted observation.
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False, autoflush=False)
    async with factory() as restarted, restarted.begin():
        await prepare(restarted, identity)
    stopped = await store.load(db_session, intent["id"])
    assert stopped.value["state"] == "REJECTED" and stopped.value["packet_id"] is None
    other = Job(title="Other fictional vacancy", source_platform="naukri", status="discovered",
                job_url="https://www.naukri.com/job-listings-fictional-291026654321")
    db_session.add(other)
    await db_session.flush()
    next_intent = (await store.start(db_session, [other.id]))[0]
    assert (await store.claim(db_session))[0] == next_intent["id"]
