# Contact run invocation — source checkpoint 2026-11-17

Implementation [970de71dd2f5709007d45590111cd1d9f4ed67fd](https://github.com/karanagg166/automated-apply/commit/970de71dd2f5709007d45590111cd1d9f4ed67fd), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

The native local run starter atomically inserts the original enrichment run and immutable invocation journal under the shared owner/SERIALIZABLE fence. It preserves actual ordered compact UTF-8 request hashes, binds company facts, normalized input/configuration and a same-process token with an original180-second deadline. The token has no Debug/Serialize interface. Replaying an idempotency key returns retained history only: no renewed lease, reconstructed invocation, adopted legacy process or remote permission. Mismatched request reuse fails closed.

Invocation guards recheck the pinned token/start/deadline, current company snapshot/configuration and exact saved request/company/state/roles/providers/idempotency binding. Altering a journal deadline cannot renew the opaque original token. Starting/checking a run performs no provider request, budget reservation or lookup admission. The later controller must independently require current credentials/capability proof, target identity, immutable lookup intent and committed credits. Saved-run serialization now whitelists root fields as well as nested usage, preventing internal idempotency/hash fields from reaching public history when called from native admission.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Local atomic run/journal, actual request hash, nonrenewable context checks and public root whitelist; formatter applied |
| Standard fixtures | NOT TESTED | 1 new declaration with14 actual Pydantic ordered-hash comparisons, including defaults/flags/Unicode/escaping/idempotency exclusion |
| Dedicated native PostgreSQL | NOT TESTED | 8 new declarations: atomic/public boundary; repeated idempotency/no renewal; retained legacy uncertainty/no adoption;5 altered journal fields/company/config;2 run insert ACK faults;2 journal ACK faults/private conversation; stale state/oversized row; concurrent single invocation |
| Existing fixture schema | NOT TESTED | Saved-run fixture now includes the actual idempotency uniqueness constraint |
| Current-head build/lint/tests | NOT TESTED | New executed tests0; full source precedes combined execution |
| Native lookup controller/provider IO | NOT TESTED / INCOMPLETE | Run admission is not wired to a billable provider endpoint; execution readiness remains false |
| Actual provider/Mac/install/timing/resources | NOT TESTED | No private provider call, account action, installation or measured comparison |

Fixed findings include `contact_run_idempotency_conflict`, `contact_run_context_changed`, `contact_run_write_ack_failed` and `contact_run_commit_outcome_unknown`. Oversized retained payloads remain distinct from an absent row and cannot authorize a new run. No executed failure log, invocation token, private account data or raw record is published.

Final reproduction: coordinated `scripts/run_acceptance.py`, Rust `contact_rules`, dedicated `contact_run_*` PostgreSQL cases and later controller/lookup/provider recovery integration cases after source completion. Remaining work includes durable per-target lookup admission, fixed transport/current capability, identity ingestion, grounded outreach and the rest of the full completion plan. Prior validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 native PG passes,455 distinct; it does not validate this head.58/42 held. STOP162/lifetime4/hour1/three quarantines/strict worker receipts0, saved filters/identity/PDF/focus/history controls remain. No hosted Actions, merge, cleanup, purchase, provider activation or runtime installation.
