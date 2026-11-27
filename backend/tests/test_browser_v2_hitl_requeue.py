"""Phase 4 priority re-queue: an owner-resolved HITL job runs before new discoveries,
gets the owner's (one-time) answer, and APPLIED/SUBMISSION_UNKNOWN never re-run."""

import pytest

from backend.app.browser_v2.adapters.base import ApplyResult, HitlQuestion
from backend.app.browser_v2.answers import hitl_override, match_option
from backend.app.browser_v2.hitl import HITLResolutionService
from backend.app.browser_v2.state import ApplicationState as S
from backend.tests.test_browser_v2_worker import (
    FakeAdapter,
    build,
    job,
    live_store,
    rules,
)


class RecordingAdapter(FakeAdapter):
    """Asks one question the first time; afterwards applies using the owner's HITL answer."""

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self.answers_seen: list[tuple[str, dict | None]] = []

    async def apply_job(self, page, detail, profile, *, dry_run=True, existing_state=None, hitl_answers=None):
        job_id = detail.listing.external_job_id
        self.answers_seen.append((job_id, hitl_answers))
        self.applied.append((job_id, dry_run))
        owner = hitl_override("Notice period (days)?", ("15", "30", "60"), hitl_answers)
        if job_id == "naukri-1" and owner is None:
            return ApplyResult(S.WAITING_FOR_USER, "question_requires_owner", False, clicked_apply=True,
                               question=HitlQuestion(kind="QUESTION", prompt="Notice period (days)?",
                                                     options=("15", "30", "60")))
        return ApplyResult(S.APPLIED, "confirmation_text", False, clicked_apply=True, receipt={"answer": owner})


def test_match_option_accepts_index_exact_and_casefold_only():
    options = ("Yes", "No", "Open to discuss")
    assert match_option("2", options) == "No"
    assert match_option("  open TO   discuss ", options) == "Open to discuss"
    assert match_option("4", options) is None and match_option("maybe", options) is None
    assert match_option(" free text ", ()) == "free text"
    assert hitl_override("Notice period (days)?", ("15", "30"), {"notice period (days)": "2"}) == "30"
    assert hitl_override("Other question?", ("15", "30"), {"notice period (days)": "2"}) is None


async def test_resolved_hitl_job_runs_first_with_owner_answer():
    adapter = RecordingAdapter("naukri", [job(1)])
    store = live_store({"naukri": rules(max_delay_sec=45)})
    worker, _ = build(store, {"naukri": adapter})
    first = await worker.cycle()
    assert first.portals[0].waiting_for_user == 1
    record = store.records[("naukri", "naukri-1")]
    assert record.state is S.WAITING_FOR_USER
    hitl_rows, _ = await store.list_hitl("OPEN")
    resolver = HITLResolutionService(store)  # no cache: e.g. a /once answer
    result = await resolver.answer(hitl_rows[0].id, "2", cache_answer=False, via="telegram")
    assert result.ok and result.answer == "30" and result.requeued and not result.cached
    assert store.records[("naukri", "naukri-1")].state is S.SCORED
    # New discoveries appear, but the re-queued job must be processed before them.
    adapter.jobs = [job(2), job(3)]
    adapter.applied.clear()
    adapter.answers_seen.clear()
    second = await worker.cycle()
    portal = second.portals[0]
    assert portal.requeued == 1 and next(j for j, _ in adapter.applied) == "naukri-1"
    assert adapter.answers_seen[0] == ("naukri-1", {"Notice period (days)?": "30"})
    assert store.records[("naukri", "naukri-1")].state is S.APPLIED
    receipt = store.records[("naukri", "naukri-1")].receipt
    assert receipt["answer"] == "30"
    assert receipt["timing"]["first_mover_lag_seconds"] is not None and receipt["timing"]["started_at"]
    assert all(row["consumed_at"] is not None for row in store.hitl if row["status"] == "ANSWERED")
    assert await store.requeued_applications("naukri") == []  # consumed: not prioritized again


@pytest.mark.parametrize("terminal", [S.APPLIED, S.SUBMISSION_UNKNOWN])
async def test_answered_hitl_never_reruns_a_terminal_job(terminal):
    adapter = RecordingAdapter("naukri", [job(1)])
    store = live_store({"naukri": rules()})
    worker, _ = build(store, {"naukri": adapter})
    await worker.cycle()
    record = store.records[("naukri", "naukri-1")]
    current = await store.get_application(record.id)
    if terminal is S.APPLIED:
        current = await store.transition(current, S.APPLYING, "manual")
    await store.transition(current, terminal, "confirmed_elsewhere")
    hitl_rows, _ = await store.list_hitl("OPEN")
    result = await HITLResolutionService(store).answer(hitl_rows[0].id, "30", via="dashboard")
    assert result.ok and not result.requeued and result.application_state == terminal.value
    adapter.applied.clear()
    report = await worker.cycle()
    assert report.portals[0].requeued == 0 and adapter.applied == []
    assert store.records[("naukri", "naukri-1")].state is terminal


async def test_skip_moves_waiting_job_to_filtered_out_and_it_is_not_reapplied():
    adapter = RecordingAdapter("naukri", [job(1)])
    store = live_store({"naukri": rules()})
    worker, _ = build(store, {"naukri": adapter})
    await worker.cycle()
    hitl_rows, _ = await store.list_hitl("OPEN")
    result = await HITLResolutionService(store).skip(hitl_rows[0].id, via="dashboard")
    assert result.ok and result.application_state == "FILTERED_OUT"
    adapter.applied.clear()
    await worker.cycle()
    assert adapter.applied == []
