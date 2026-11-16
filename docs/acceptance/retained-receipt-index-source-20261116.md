# Retained receipt indexing without evidence downgrade — source checkpoint 2026-11-16

Implementation [`531ab20779258832adbd106b57eed4240cf3c5d7`](https://github.com/karanagg166/automated-apply/commit/531ab20779258832adbd106b57eed4240cf3c5d7), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Uninstalled source; compilation/tests deferred.

The existing execution connection now indexes at most five retained owner UI observations per tick using the original updated_at/key cursor. Only the existing genuine-record predicate can create a SUBMITTED_RECORDED historical projection. Original receipt bytes and packet lifecycle are preserved. Invalid evidence still advances the bounded scan; its existence independently prevents replay, while it does not count as a confirmed submission. A later receipt correction is considered through its updated_at version.

Source review found that the older indexer could overwrite stronger current worker evidence or clear an unknown/original-form work context. The Rust indexer leaves SUBMITTED_CONFIRMED, SUBMISSION_UNKNOWN, spent admissions, packet bindings, active/unknown reads, pending forms and outstanding leases unchanged. This intentionally strengthens the legacy index transition. Historical owner observations never become installed-worker receipts, consume no admission and cannot satisfy the strict first dispatched/current-account receipt gate. The indexer shares the owner fence, SERIALIZABLE snapshot and exact event/work/cursor acknowledgment transaction; idle scans avoid the owner lock.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Five-row scan, history projection, protected stronger/uncertain work and atomic cursor/event/work publication; formatter applied |
| New standard tests | NOT TESTED | New declarations0; existing genuine-record predicate oracle remains applicable but has not run on this head |
| New native PostgreSQL tests | NOT TESTED | 4 declarations:5+2 scan/preserved receipt bytes/no admissions; unchanged strict/unknown/form work; dropped event ACK rollback; idle lock avoidance and AUTO refusal after historical indexing |
| Compile/Clippy/lint/all suites | NOT TESTED | New executed tests0; complete source precedes the combined gate |
| Actual Mac/browser/application/installation | NOT TESTED | No source installation, provider/UI read, owner-data query or new receipt |
| Resource/restart/latency measurements | NOT TESTED | Batch bounds describe source only; no performance improvement claimed |
| Full project/platform acceptance | BLOCKED / NOT TESTED | Complete Telegram/Gmail/outreach/provider/platform source and actual account/focus/operator migration gates remain; actual strict receipts0 |

Final reproduction after all source is integrated: `scripts/run_acceptance.py`, including tests/support/retained_index_pg.rs in the disposable native PostgreSQL harness. No new executed failure log exists. Sanitized failures remain invalid_execution_saved_record, execution_database_error, execution_write_ack_failed, execution_rollback_unconfirmed and execution_commit_outcome_unknown. No private receipt evidence beyond fictional fixture metadata is published.

Last validated source9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 dedicated native PostgreSQL passes,455 distinct; it does not validate this head. Estimate58% complete /42% remaining remains unchanged, with no reliable finish time. Continue the [complete-source plan](../plans/completion-execution-20261116.md), then combined testing, reviewed whole-family installation and independently verified per-platform results. Installed STOP162, lifetime4/hour1, three quarantines, current saved filters/history/identity/PDF, first strict receipt, Gmail read/draft-only and actual browser focus rules remain. No hosted Actions, merge or live activation.
