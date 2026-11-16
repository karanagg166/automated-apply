# Waiting-owner snapshot fence — source checkpoint 2026-11-16

Implementation [`30cd2140946ee3124c54ad7a2f26ceb02f348d75`](https://github.com/karanagg166/automated-apply/commit/30cd2140946ee3124c54ad7a2f26ceb02f348d75), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Source only; no installed/runtime/database change.

The source audit found two distinct snapshot races. A serializable form operation can establish its snapshot while waiting for the shared owner row. Locking an existing changed authority row after that wait detects the conflict. A control record inserted for the first time is invisible in the older snapshot, so authority-row locks alone cannot cover that case.

Rust browser/execution owner locks and the legacy Python cached owner lock now advance only the existing owner row's updated_at metadata and require an exact acknowledgement. PostgreSQL row-version conflict must then abort an older waiting snapshot. Private conversation JSON, its own message/TTL timestamps, request IDs and account/session identities are preserved. Python nested guards retain the existing transaction/savepoint cache; a lock version is advanced once on first acquisition, not on cached nested calls. This is application owner-lock metadata, not a Codex account/thread identity rewrite.

Serializable form paths also lock bounded current control/profile/confirmation/project-reference rows after the owner wait. Normal status/checkpoint reads keep their separate read-only path. Native health/capability reads now issue SELECT1 to verify PostgreSQL reachability without waiting for or updating the owner fence; their public capability data is unchanged and grants no submission.

## Evidence matrix

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source audit and implementation | PASS (source only) | Existing/first-control snapshot cases traced; exact ACKs and unchanged memory JSON; Rust formatter applied; Python diff kept minimal |
| New Rust native PostgreSQL tests | NOT TESTED | 5 declarations: existing-control race without metadata touch; first-control race with version advancement; preserved memory/TTL with changed xmin; dropped ACK rollback; health/capability reads under held owner lock |
| New backend PostgreSQL tests | NOT TESTED | 1 declaration: actual Python owner-lock helper versus repeatable snapshot before first OFF control insertion |
| Existing backend lock/timing cases | NOT TESTED | Two cases updated for one SELECT plus one fence UPDATE on first acquisition; cached nested guards still require no SQL |
| Build/Clippy/Ruff checks/all suites | NOT TESTED | Source-first/final combined gate remains active; new tests executed0 |
| Actual Mac/live DB/browser/model/account/install | NOT TESTED | No live operation, message, application or component replacement |
| Whole writer-family installation | BLOCKED | All participating writers must use the coordinated fence; no mixed installed Python/Rust writer family or uncoordinated DB-writer guarantee |
| Actual first worker receipt/AUTOMATIC | BLOCKED | Last real evidence0; no activation |
| Focus/locked/restart/24h resources | NOT TESTED | Previous focus findings remain; all actual comparisons pending |

Prior validated checkpoint remains9c4ace5:193 standard +262 dedicated native PostgreSQL tests,455 distinct. It does not validate this source. Estimate stays58% complete /42% remaining, an engineering estimate rather than an acceptance score.

## Reproduction, costs and remaining work

Run `scripts/run_acceptance.py` only after all planned source units are integrated. The native-PG cases are `tests/support/owner_snapshot_pg.rs`; the backend case is appended to `backend/tests/test_reliability_postgres.py`. Use the guarded disposable fixtures only, never real owner data/configuration. No executed failure logs exist. Expected conservative failures are browser_profile_database_error/execution_database_error for a serialization abort and the existing write_ack_failed codes for a dropped update. There is no action replay.

Source-level cost change: first acquired owner guard adds one metadata UPDATE; cached Python nested guards add none. Serializable form scope transfers at most10,001 keys and fails/rolls back above10,000 combined control/project keys. Native health uses one small database read instead of an owner transaction. These are code/query-count descriptions, not measured timing, throughput, memory, latency or resource improvements. Final load/concurrency/rollback measurements remain required. Metadata touch requires the existing updated_at column and UPDATE privilege, not new DDL.

The source fence coordinates participating local writers; it does not provide distributed safety against arbitrary external SQL or an unpatched mixed writer family. Installer inventory and whole-family STOP cutover remain mandatory. Full account/profile sync work, questionnaires/owner replies, search/native broker/scheduler and all other remaining services/providers/platforms still need completion under the [plan](../plans/completion-execution-20261116.md). Existing installed services, last STOP162, lifetime4/hour1, three quarantines, filters, focus, Gmail read/draft-only and private history are unchanged by this checkpoint.
