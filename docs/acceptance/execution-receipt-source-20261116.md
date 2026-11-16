# Native history and receipt source checkpoint — 2026-11-16

Implementation [`fd85d94bc1ec10a158ea27fe37582e4cd8511ae0`](https://github.com/karanagg166/automated-apply/commit/fd85d94bc1ec10a158ea27fe37582e4cd8511ae0), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Internal source only; no actual provider or native-browser acceptance.

The state observer now ports profile verification, exact application inspection, one admitted Apply observation, questionnaire handoff, account rechecks and independent history reconciliation. An Apply click is never a receipt. Current selected-account checks, exact work lease/binding and native report DTO validation fence observations. Failed or missing execution responses retain spent actions and quarantine uncertain outcomes. Transport descriptors omit private source/admission/secret fields.

Confirmation requires matching account/requisition/title/company and two different history documents observed in order. New document IDs must satisfy the actual native DTO. The immutable receipt, job applied status, existing canonical packet/evidence guard transition, local_worker audit and owner notice/outbox writes share one transaction. Existing receipt keys are never overwritten. A worker-dispatched receipt requires an actual Apply fingerprint; reconciled history without it cannot rewrite the packet as worker-confirmed or unlock the first-receipt AUTO prerequisite. Prior submitted/manual evidence is preserved.

Internal recovery schedules history reads only, retains admissions and stops scheduling after three reported account/history attempts; Stop prevents recovery scheduling. The final broker still needs to bound lost-read/admission responses consistently, so the complete restart/resource behavior is not accepted. Existing in-app preferences, queue opt-in Telegram flag and fixed-owner configuration gate durable notices; no Telegram transport or arbitrary recipient is introduced. Source packet transitions now explicitly update updated_at.

## Evidence matrix

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source implementation/tracing | PASS (source only) | Actual legacy state branches, frozen native report, existing encryption/receipt predicates and real schema guards reused; formatter applied |
| New standard Rust tests | NOT TESTED | 2 declarations: closed native observation DTO/defaults and descriptor redaction/binding |
| New native PostgreSQL tests | NOT TESTED | 4 declarations: separate-document confirmation with actual packet guards; dropped receipt ACK rollback; wrong identity/failure quarantine; bounded/STOP recovery |
| Native broker/full encrypted-PDF Apply/questionnaire/restart | NOT TESTED | Required integration and broader failure fixtures remain pending |
| Build/Clippy/all suites/checks | NOT TESTED | Owner's source-first/final combined run remains in force; new tests executed0 |
| Actual Mac/browser/provider/online DB/notice delivery/install | NOT TESTED | No real operation, receipt, Apply, queue change, migration, component replacement or message delivery |
| Production schema/whole-family cutover | BLOCKED | Rust tables absent; reviewed operator migration/grants and STOP installation required |
| Actual first worker receipt/AUTOMATIC | BLOCKED | Last live evidence still0 strict receipts; no activation |
| Focus/locked/24h resources | NOT TESTED | Prior focus failures remain in force; no new timing/resource comparison |

Prior fully validated checkpoint remains9c4ace5,193 standard +262 dedicated disposable-PG tests,455 distinct. It does not validate this implementation. Estimate stays58% complete /42% remaining; no measured acceptance percentage or success claim.

## Reproduction and remaining work

After all source units in the [completion plan](../plans/completion-execution-20261116.md) are integrated, run `scripts/run_acceptance.py` under its coordinated locks using fictional native PostgreSQL. New fixtures are `tests/submission_observations.rs` and `tests/support/execution_submission_pg.rs`. Their direct internal helpers simulate an existing admission; they are not browser authentication, actual admission/Apply or genuine provider evidence. The latter all need separate end-to-end validation. No executed failure logs exist. Expected failure codes include independent_history_reload_required, provider_receipt_identity_changed, queue_lease_lost, existing_worker_receipt_requires_review, execution_write_ack_failed and execution_commit_outcome_unknown.

Receipt storage is immutable on conflict. A transaction failure rolls back job/packet/evidence/notice/outbox/work changes; a lost commit is unknown and must be reread rather than replayed. Recovery inventory is capped at10,000 active records; full resource measurements and lost-read counter handling await the broker. No performance or production-correctness claim follows from this source.

Continue queue discovery/preparation,30-minute portal/profile checks, profile sync, original forms/questions/owner replies, the complete authenticated native broker and scheduler. Finish the remaining service/provider/platform ports, then combined tests and actual Mac/install/per-platform acceptance. Installed services, STOP162, lifetime4/hour1, three uncertain jobs, current filters, focus, Gmail read/draft-only and all private data remain unchanged.
