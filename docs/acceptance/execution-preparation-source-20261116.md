# Native saved-source/preparation checkpoint — 2026-11-16

Implementation [`4b47ae34bf344cb3e56599c0b20e6d225f1858a0`](https://github.com/karanagg166/automated-apply/commit/4b47ae34bf344cb3e56599c0b20e6d225f1858a0), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Source only; no running scheduler or provider acceptance.

The local producer consumes at most ten saved records per enabled source with durable timestamp/identity cursors. Approved Gmail alerts remain restricted to the existing gmail_job_alerts/local:1 scope; other accounts/deferred sources do not become authorized. It loads only URL/source/cursor metadata, never message contents. Deduplication, prior evidence and backpressure are shared with enqueue; an unconsumed record remains behind its cursor. Original sources are preserved.

Local preparation uses the existing queue claim, confirmed profile, current factual eligibility, saved packet builder, selected encrypted-PDF preflight and approved account binding. Missing facts/resume remain durable holds with packet/questions retained; no quota or browser action is admitted. Waiting standing-policy work requires fresh preparation. Idle inspection-only backlog does not acquire the owner lock.

Source review found that the original packet preview/create requires a repeatable snapshot, while preparation must read policy after waiting for the owner lock. A separate internal create_locked_in path now uses the established current job/profile/resource material locks under READ COMMITTED. Existing preview/create calls keep their original snapshot path. Packet replay/read uses the corresponding material path. No isolation requirement was silently relaxed.

## Evidence matrix

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Implementation/source tracing | PASS (source only) | Actual saved-source cursor, preparation and packet-context logic read; formatter applied |
| New native PostgreSQL tests | NOT TESTED | 4 declarations: idle owner-lock avoidance; ten-row account-filtered/private-body cursor; backpressure cursor; actual guarded factual packet creation followed by missing-resume hold |
| Prior packet creation/replay/concurrency regression | NOT TESTED | Full existing cases must rerun at the combined gate because a shared helper was refactored |
| Build/Clippy/all suites/checks | NOT TESTED | Source-first/final combined run per owner; new tests executed0 |
| Scheduler/native broker/profile/questionnaire | NOT TESTED | Further source integration remains required |
| Actual Mac/browser/provider/mail/online DB/install | NOT TESTED | No live reads, applications, migrations, queue updates, notices or component replacement |
| Production schema/whole-family STOP cutover | BLOCKED | Reviewed operator migration/grants and installation remain required |
| Actual strict receipt/AUTOMATIC | BLOCKED | Last live evidence0 strict receipts; no activation |
| Focus/locked/restart/24h resources | NOT TESTED | Prior focus findings remain; no timing/resource comparison |

Last fully validated checkpoint is still9c4ace5:193 standard +262 dedicated native-PG tests,455 distinct. Those are prior results and do not validate this implementation. Engineering estimate stays58% complete /42% remaining, not a measured score.

## Reproduction and limits

After all planned source units are integrated, run `scripts/run_acceptance.py` under its existing coordinated locks with fictional native PostgreSQL. New cases are in `tests/support/execution_preparation_pg.rs`. Never provide real mailbox/database configuration. No executed failure logs exist. Expected conservative hold/failure codes include confirmed_primary_resume_required, verified_profile_context_changed, prior_application_or_unknown_submission_no_replay, queue_backpressure and execution_commit_outcome_unknown.

Each saved-source transaction handles at most ten records per enabled source. Preparation handles one claim and retains the shared active inventory bounds. Model/provider/browser work does not run inside this preparation transaction; SQL and local PDF decryption do. Owner-lock duration, code correctness, full restart behavior and speed/resource differences need final measurement. A lost commit is unknown and is not replayed.

Continue ordinary search discovery/profile checks, profile sync, questionnaire answers/owner replies, the authenticated broker and production scheduler. Then all remaining services/providers/platforms and final local/live acceptance in the [completion plan](../plans/completion-execution-20261116.md). Existing STOP162, lifetime4/hour1, three quarantines, filters, first-receipt rule, focus, Gmail read/draft-only, installed services and private data remain unchanged.
