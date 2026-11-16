# Local outreach ledger — source checkpoint 2026-11-17

Implementation [2ebf11878fbaf0e85601d9d8c670337ae1912797](https://github.com/karanagg166/automated-apply/commit/2ebf11878fbaf0e85601d9d8c670337ae1912797), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

Local creation now persists grounded copy and the exact private evidence snapshot in the original outreach_logs ledger, under owner-first serializable locks and stable request idempotency. It refuses REST narrative requests, which need a separate durable writer admission. MCP local composition never invokes a writer. Existing idempotency returns the original draft with current stale/eligibility findings instead of regenerating it. Creation is currently a domain service; the unified preview/create IO controller follows this slice.

Owner-only list/detail/eligibility/edit/approve/reject routes are connected. GETs remain repeatable-read/read-only without the owner mutex. Mutations refuse every historical send attempt or sent row, check the reviewed revision, invalidate old approval after edits and bind approval to resulting revision/content/recipient/current evidence. Unsupported edited sentences and incompatible legacy contexts cannot be approved. Private snapshots and approval hashes are excluded from public draft responses; provider metadata is whitelisted. Sending stays disabled even with current approval.

The source review found the actual additive database guard supplies its own timestamps/revision. The writer accepts only updated/edit timestamps within the current database operation window, compares every other field exactly and reloads the full row after triggers. Same-state no-op decisions retain the original revision. Fixtures load the repository's actual final guard, including immutable provider history; they do not replace it with a permissive revision mock.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Original local ledger/idempotency/guarded edits and approval, read routes, complete row ACK with bounded guard timestamps; formatting applied |
| Standard fixtures | NOT TESTED | 2 declarations:20 actual Unicode sentence-support cases;14 actual revision/content/recipient/evidence hash bindings |
| Dedicated native PG/HTTP fixtures | NOT TESTED | 12 declarations: complete lifecycle; idempotency/stale replay; stale revision/unsupported copy; recipient changes; all historical attempts/sent immutability; before/after UPDATE corruption; suppressed/changed INSERT; read/privacy; missing context/local-only writer refusal; owner HTTP; concurrent same key; material-lock rollback |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests0; full source precedes combined acceptance |
| Actual Mac/Gmail/provider/runtime/install | NOT TESTED | No real mail/credential/account request, browser work or installed change |
| Timing/resources/concurrency | NOT TESTED | Isolated concurrency fixture source only; no measured runtime comparison or live acceptance |

Fixed failures include `outreach_draft_revision_conflict`, `outreach_send_reserved_draft_immutable`, `outreach_draft_not_eligible`, `outreach_write_ack_failed`, `outreach_idempotency_key_conflict` and `outreach_writer_intent_required`. No executed failure logs, candidate data, mail or private evidence are published.

Final reproduction: coordinated `scripts/run_acceptance.py`, Rust `outreach_rules`, complete dedicated disposable native PG `outreach_drafts_*`, full UI/types/browser checks. Commands are documented, not executed now. Next: preview/create controller with durable optional grounded-writer intents outside owner/material locks, remaining research/company/dashboard/registry/provider/CLI/conversation/eight-platform source, then combined gates and reviewed migration/install/live evidence. Last validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard+262 native PG=455 distinct passes; not current-head evidence.58/42 held. STOP162/lifetime4/hour1/three uncertain quarantines/strict worker receipts0 and current filters/identity/PDF/focus rules remain. No hosted Actions, merge, cleanup, sending or installation.
