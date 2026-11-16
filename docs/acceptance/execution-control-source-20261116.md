# Native queue control source checkpoint — 2026-11-16

Implementation: [`757ea0154aa18404ce38b9e5359dfc41e15452c1`](https://github.com/karanagg166/automated-apply/commit/757ea0154aa18404ce38b9e5359dfc41e15452c1), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. This is unvalidated source, not a running-platform acceptance report.

The existing owner PUT `/api/v1/execution/queue/policy` and POST `/api/v1/execution/queue/control` now dispatch to Rust. Mutations take the legacy owner lock before rereading policy/revision, acknowledge saved values, commit outbox events with state, and report uncertain commits without replay. Reads retain their separate read-only snapshots.

Stop/Pause revoke queue search/profile leases and eligible active work, quarantine executing writes, preserve spent admissions and already-unknown work, pause legacy intents, and revoke Naukri packet tasks/plans/commands even without an execution association. Other packets remain independent. A stronger existing browser-task Stop survives a subsequent Pause. Start requires enabled configuration/platform, routes paused writes through fresh inspection and does not resume individual legacy tasks. Missing legacy automation records stay absent.

Policy changes pause a running queue, preserve saved controls except explicit replacements, request durable filter reconsideration when factual filters change and resolve an existing applicant-count policy notice when its decision changes. The reconsideration worker itself remains pending. AUTOMATIC requires the current selected account plus a strict admitted, dispatched worker receipt; historical/operator receipts and malformed proofs do not satisfy it. Proof lookup uses ten-row keyset batches, without a retained-history inventory cutoff. Existing invalid receipt keys still prevent replay in the pending kernel port.

## Evidence matrix

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Implementation and source review | PASS (source only) | Contracts traced to actual legacy control, account, receipt, reconsideration and browser-task code; formatter applied |
| New Rust standard tests | NOT TESTED | 1 new declaration covering interrupted writes, preserved admissions, terminal states and fresh-resume paths |
| New native PostgreSQL tests | NOT TESTED | 10 new declarations covering Stop, Start, cross-channel revocation, 20,002 inert holds, two injected rollback failures, policy/recheck, concurrent CAS, HTTP authorization, 16 retained proofs and applicant notification resolution |
| Build / Clippy / checks / all local suites | NOT TESTED | Deliberately deferred until complete source, per owner instruction |
| Actual Mac/browser/provider/online DB | NOT TESTED | No live IO, window action, application, migration, installation or queue change by this checkpoint |
| Production schema readiness | BLOCKED | Rust tables remain absent; operator migration/grants review and whole-family STOP cutover required |
| First strict worker receipt | BLOCKED | Last live evidence remains zero; no recurring AUTOMATIC activation |
| Focus / locked / 24h resources | NOT TESTED | Previous Brave window-creation focus failure remains unresolved; that path stays suspended |

Last validated checkpoint remains `9c4ace5`:193 standard +262 dedicated native PostgreSQL tests,455 distinct. Those are prior results and do not validate this commit. New tests executed here: **0**. Full scope estimate remains **58% complete /42% remaining**, an engineering estimate rather than an acceptance score.

## Reproduction and limits

After all planned source units are integrated, use the final combined runner in `scripts/run_acceptance.py` under its coordinated locks. The new pure fixture is `rust/agent-runtime/tests/execution_fences.rs`; PostgreSQL cases are included from `tests/support/execution_control_pg.rs`. They require the dedicated fictional native-PG harness, never the real database or repository `.env`. No partial suite was run here.

Source bounds: more than10,000 active revocation candidates fails closed with `execution_active_inventory_limit` (or the browser inventory code) and rolls back the complete control transaction. Inert never-attempted holds are excluded in SQL; the new20,002-row fixture is unrun. Saved malformed authority fails rather than being reset. Commit/rollback loss returns `execution_commit_outcome_unknown` / `execution_rollback_unconfirmed`; callers must reread, not replay. Exact ACK failure is `execution_write_ack_failed`. No sanitized failure logs exist because these fixtures have not executed. No timing/resource improvement is claimed; comparisons await the final gate.

Continue native queue/kernel eligibility, identity/PDF, claims/admissions, original forms, questions, strict receipts/reconciliation, then all remaining provider/platform/parity work in the [completion plan](../plans/completion-execution-20261116.md). Installed legacy services, lifetime4/hour1, three quarantines, saved filters, Gmail read/draft-only, budgets, owner focus and rollback inventories remain unchanged.
