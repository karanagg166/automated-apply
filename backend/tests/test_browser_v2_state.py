import pytest

from backend.app.browser_v2.adapters.base import JobListing
from backend.app.browser_v2.state import (
    ApplicationState as S,
)
from backend.app.browser_v2.state import (
    InvalidTransition,
    ReplayRefused,
    check_transition,
    guard_apply,
)
from backend.app.browser_v2.store import MemoryStore
from backend.scripts.migrate_v2_core import (
    QUARANTINE_REASON,
    classify_legacy_rows,
)


@pytest.mark.parametrize("state", [S.APPLIED, S.SUBMISSION_UNKNOWN])
def test_never_replay_states_refuse_apply(state):
    with pytest.raises(ReplayRefused, match="never_replay"):
        guard_apply(state)


@pytest.mark.parametrize("state", [S.APPLYING, S.WAITING_FOR_USER, S.FILTERED_OUT])
def test_in_flight_or_filtered_states_are_not_auto_applied(state):
    with pytest.raises(ReplayRefused, match="not_apply_eligible"):
        guard_apply(state)


def test_new_and_retryable_states_may_apply():
    for state in (None, S.DISCOVERED, S.SCORED, S.QUOTA_HIT_PENDING, S.DRAFTED_AND_QUEUED, S.FAILED):
        guard_apply(state)


def test_terminal_states_have_no_exits():
    for target in S:
        if target not in (S.APPLIED, S.SUBMISSION_UNKNOWN):
            with pytest.raises(InvalidTransition):
                check_transition(S.APPLIED, target)
            with pytest.raises(InvalidTransition):
                check_transition(S.SUBMISSION_UNKNOWN, target)


async def test_memory_store_is_idempotent_and_versioned():
    store = MemoryStore()
    listing = JobListing(platform="naukri", external_job_id="261126000001", url="https://www.naukri.com/x")
    first = await store.upsert_discovered(listing)
    again = await store.upsert_discovered(listing)
    assert first.id == again.id and first.state is S.DISCOVERED and len(store.records) == 1
    applying = await store.transition(first, S.APPLYING, "apply_started", count_attempt=True)
    assert applying.attempts == 1 and applying.version == first.version + 1
    with pytest.raises(InvalidTransition, match="stale_version"):
        await store.transition(first, S.APPLYING, "duplicate_worker")
    applied = await store.transition(applying, S.APPLIED, "confirmed")
    with pytest.raises(InvalidTransition):
        await store.transition(applied, S.APPLYING, "replay")


def legacy_rows():
    quarantined = [
        ("apply_work:a", {"platform": "naukri", "requisition": "051126000230", "stage": "SUBMISSION_UNKNOWN",
                          "title": "Backend Engineer", "company": "Acme"}),
        ("apply_work:b", {"platform": "naukri", "requisition": "061126013473", "stage": "NEEDS_INPUT",
                          "admitted_actions": [{"fingerprint": "apply:061126013473"}]}),
        ("apply_work:c", {"platform": "naukri", "requisition": "080524010245", "stage": "SUBMISSION_UNKNOWN"}),
    ]
    other = [
        ("apply_work:d", {"platform": "naukri", "requisition": "261026028027", "stage": "SUBMITTED_CONFIRMED"}),
        ("apply_work:e", {"platform": "naukri", "requisition": "111111111111", "stage": "DISCOVERED"}),
        ("naukri_receipt:222222222222", {"status": "Application Sent"}),
        ("naukri_receipt:051126000230", {}),
        ("exec_config:naukri", {}),
    ]
    return quarantined + other


def test_legacy_quarantine_migrates_to_submission_unknown():
    fences = {f.external_job_id: f for f in classify_legacy_rows(legacy_rows())}
    for requisition in ("051126000230", "061126013473", "080524010245"):
        assert fences[requisition].state == "SUBMISSION_UNKNOWN"
        assert fences[requisition].reason == QUARANTINE_REASON
    assert fences["261026028027"].state == "APPLIED"
    assert fences["222222222222"].state == "SUBMISSION_UNKNOWN"
    assert "111111111111" not in fences
    assert len(fences) == 5


async def test_migrated_quarantine_is_never_replayed_by_service():
    from backend.app.browser_v2.service import BrowserService

    store = MemoryStore()
    for fence in classify_legacy_rows(legacy_rows()):
        await store.upsert_discovered(JobListing(
            platform="naukri", external_job_id=fence.external_job_id, url="https://www.naukri.com/x"))
        store.records[("naukri", fence.external_job_id)].state = S(fence.state)

    class NoBrowser:
        def job(self):
            raise AssertionError("browser must not open for a never-replay job")

    service = BrowserService(NoBrowser(), store)  # type: ignore[arg-type]
    for requisition in ("051126000230", "061126013473", "080524010245", "261026028027"):
        url = f"https://www.naukri.com/job-listings-backend-engineer-acme-bengaluru-0-to-3-years-{requisition}"
        for dry_run in (True, False):
            result = await service.apply_to_job("naukri", url, dry_run=dry_run)
            assert result["refused"].startswith("never_replay:")
