# Outreach history and draft contracts — source checkpoint 2026-11-17

Implementation [504cf2ce819ae7ee1e7c8131fcf8fbd5355a4904](https://github.com/karanagg166/automated-apply/commit/504cf2ce819ae7ee1e7c8131fcf8fbd5355a4904), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

The original draft input/edit/decision schemas are frozen from the actual Pydantic declarations through an AST-only exporter. Native normalization preserves omitted edit fields, rejects explicit null edits and header injection, and retains actual defaults/coercions. A drift stage is added to the final coordinated runner.

Owner-only saved history and send-attempt GET routes use one repeatable-read, read-only transaction and database timestamp. The timeline includes one attempt per recorded intent or a local draft without an attempt, with deterministic pagination and explicit public-column projections. Private confirmations, request identities, sender bindings, evidence snapshots and generation data are excluded. Per-row and aggregate byte bounds fail closed.

Expired prepared/attempting records are qualified only in the response. Their original status stays visible, the original database rows remain unchanged and no GET adopts, retries or refunds an intent. Recorded legacy sent dates never become acceptance dates. Even a saved provider-acceptance record is explicitly historical, with delivery verification false. Sending remains disabled by owner policy.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | DTO export/native contracts, bounded history projection, owner routes/configuration/errors; formatting applied |
| Standard fixtures | NOT TESTED | 3 declarations:70 actual DTO cases (32 input/28 edit/10 decision); pure interruption/proof projection; pagination/settings/route bounds |
| Dedicated native PG/HTTP fixtures | NOT TESTED | 8 declarations: timeline/privacy; old/recent attempts/recorded acceptance; owner-lock independence; legacy sent qualification; deterministic paging; missing/malformed context; method/body/query refusal; owner HTTP authentication/policy refusal |
| Current tests/build/lint/types | NOT TESTED | New executed tests0; full source still precedes combined acceptance |
| Actual Mac/Gmail/runtime/install | NOT TESTED | No provider request, credential read, installed change or real message/application action |
| Timing/resources | NOT TESTED | One saved snapshot/connection and bounded projections by design; no measured speed/resource comparison |

Fixed errors include `outreach_send_attempt_not_found`, `invalid_outreach_contract`, `invalid_outreach_query`, `invalid_outreach_saved_record` and `outreach_history_projection_limit`. No executed failure logs, candidate data, mail or private browser evidence are published. Formatter/source generation is not a test pass.

Final reproduction: coordinated `scripts/run_acceptance.py`, `cargo test -p automated-apply-agents --test outreach_contract`, and dedicated disposable native PG `outreach_history_*` cases through the complete PG harness. These commands are documented, not executed now. Grounded draft context/creation/edit/approval, remaining public research/company/dashboard/registry/provider/CLI/conversation/eight-platform source and final migration/install/live gates remain. The previous validated checkpoint9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard+262 native PG=455 distinct passes; those results do not validate this source.58/42 estimate held. STOP162, lifetime4/hour1, three uncertain quarantines, strict worker receipts0, current filters, identity/PDF checks and focus controls remain. No hosted Actions, merge, cleanup, sending or installation.
