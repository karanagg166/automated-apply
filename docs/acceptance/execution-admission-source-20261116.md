# Native queue and admission source checkpoint — 2026-11-16

Implementation [`c83f2fbd0f5634c6f95e0e3c29d08b898425ae21`](https://github.com/karanagg166/automated-apply/commit/c83f2fbd0f5634c6f95e0e3c29d08b898425ae21), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Source phase only; no running submission capability is claimed.

New internal queue entries preserve the UUIDv5 requisition identity, source-reference hash, prior receipt existence fences and cross-packet submission history. Capacity is counted in PostgreSQL without transferring retained descriptions. Claims exclude waiting/terminal history, recover expired writes into unknown state, check all active leases before assigning another, preserve FIFO within priority lanes and reread current policy/mode under the shared owner lock. A read lease never reserves an application quota.

The internal admission transaction checks current policy/local platform preference, exact lease/revision/binding and receipt existence. Writes additionally require current account approval, confirmed profile, factual eligibility, packet freshness and decrypted canonical private-PDF integrity. Provider account, prior application status and downloaded-resume observations must be no older than two minutes; freshness/lease are checked again after proof/history costs. Original questionnaire continuation requires the original Apply admission, submitting packet, profile/PDF version, reviewed answer source, optional project digest and original form binding. These are internal primitives awaiting native dispatch integration.

Lifetime/hour/day reservations share the admission transaction. A single SQL aggregate reads admission arrays, not full retained history payloads; malformed IDs/arrays/entries/times or future admission times require reconciliation rather than becoming an allowance. SUPERVISED Apply counts lifetime work items containing Apply, including unknown outcomes across midnight; hourly work remains counted once, and existing daily reservations are never refunded. Apply admission is saved before the existing schema guard permits the packet's revisioned transition to submitting, with a local_worker event in the same transaction. Commit loss remains unknown and does not replay.

## Evidence matrix

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Implementation/source tracing | PASS (source only) | Ported actual queue, matching/eligibility, account, upload-preflight, original-questionnaire and admission behavior; existing domain matcher/encryption/schema guards reused; formatter applied |
| New standard Rust tests | NOT TESTED | 2 declarations for any/all verified skills, other filters, unknown experience, custom experience/salary and preserved admissions |
| New native PostgreSQL tests | NOT TESTED | 9 declarations for permanent identity/damaged receipt, concurrent claims, all-expired-write recovery, unadmitted Apply recovery, operation/policy filtering, read admission, cross-midnight totals,12 malformed-history variants and changed mode/binding/token/expiry |
| Full write admission/schema-guard fault integration | NOT TESTED | Canonical encrypted-PDF Apply and questionnaire integration fixtures still need completion with the native kernel |
| Build / Clippy / all checks and local suites | NOT TESTED | Owner explicitly requested all source first, tests together at the end; new tests executed:0 |
| Native broker/receipt/preparation scheduling | NOT TESTED | Not integrated into dispatch or scheduled production; remaining implementation is required |
| Actual Mac/browser/provider/online PostgreSQL/install | NOT TESTED | No live operation, application, migration, queue update or component replacement |
| Production schema and whole-family cutover | BLOCKED | Rust tables absent under current runtime role; reviewed operator migration/grants and STOP cutover remain required |
| Actual strict first worker receipt | BLOCKED | Last live evidence remains0; no recurring AUTOMATIC activation |
| Focus / locked / restart /24h resources | NOT TESTED | Prior focus findings remain in force; no timing/resource comparison claimed |

Prior validated checkpoint is still9c4ace5:193 standard +262 dedicated disposable-PG tests,455 distinct. Those tests do not validate this implementation. Estimate remains58% complete /42% remaining; it is an engineering estimate, not a measured acceptance percentage.

## Reproduction, limits and next work

Run `scripts/run_acceptance.py` after every planned source unit is integrated, using its fictional native PostgreSQL stages and coordinated locks. New files are `tests/execution_eligibility.rs`, `tests/support/execution_queue_pg.rs` and `sql/execution_admission_totals.sql`. No repository environment, real account or production DB belongs in these fixtures.

Active queue inventory is bounded at10,000 with fail-closed rollback above that; normal configured pending cap is at most500. Expired leased/executing records without a valid expiry fail closed. Inert holds/terminal history stay outside claim transfers. More conservative differences from legacy: all expired writes are recovered before a live lease returns no work; malformed admission history/identity fails instead of becoming empty history; delayed proof time is rechecked. SQL aggregates, guards and performance are unvalidated. No logs/failure codes from executed cases exist. Expected sanitized failures include queue_lease_lost, admission_history_requires_reconciliation, supervised_application_allowance_exhausted, hourly_application_cap_reached, daily_application_cap_reached and execution_commit_outcome_unknown.

Continue native dispatch/descriptors, discovery/profile/preparation, complete original questionnaire generation/receipt paths, independent history reconciliation and strict immutable receipts. Then finish the remaining services/providers/platforms, combined tests, reviewed migration/install/rollback and real per-platform acceptance in the [completion plan](../plans/completion-execution-20261116.md). Full plan is incomplete. Installed legacy services, STOP162, lifetime4/hour1, three quarantines, filters, focus and private data remain unchanged.
