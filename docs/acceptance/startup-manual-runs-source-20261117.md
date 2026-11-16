# Original manual startup runs — source checkpoint 2026-11-17

Implementation [a3c977d841af00139725c601c30ae0aad092c630](https://github.com/karanagg166/automated-apply/commit/a3c977d841af00139725c601c30ae0aad092c630), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

Manual company-first runs now use the original discovery_runs ledger and actual startup-prefixed request hashes. An owner-first serializable claim commits the exact row and private opaque180-second invocation before ingestion. Idempotency replays return retained history without reconstructing execution authority. Permission-confirmed observations and company-scoped saved ranking complete in one second serializable transaction, with complete run/journal ACK and original deadline checks. Scope filtering excludes unrelated companies before candidate limits/ranking.

Failed/cancelled completion preserves the admitted running claim and rolls back the observation/company batch. Expired retained runs are qualified recovery_required without GET writes, refresh or automatic replay. Output excludes raw request/journal/vendor fields and untrusted legacy diagnostics; saved rankings pass the selected public projection. Empty manual requests honestly return manual_input_required. This is a manual-only domain service; full source registry/provider orchestration/host route integration follows, so no provider or operational completeness is claimed.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Original manual claim/opaque invocation, atomic observation+scoped ranking+finalization, retained read projection and no replay; formatting applied |
| Standard fixtures | NOT TESTED | 1 declaration:16 actual claim fingerprint-expression comparisons, including startup prefix/Unicode/defaults/idempotency exclusion |
| Native PG fixtures | NOT TESTED | 10 declarations: manual/scoped ranking/replay; empty input; conflicting key; original invocation lost; expired GET qualification; failed observation rollback; admission/finish ACK rollback; complete-row drift; permission/nonmanual refusal; private retained history exclusion |
| Frontend additions | NOT TESTED | No new declarations in this slice; previous source remains unrun |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests0; complete source precedes combined gates |
| Actual Mac/provider/runtime/install | NOT TESTED | No provider/account/browser/production/installed action |
| Timing/resources/concurrency | NOT TESTED | Source deadline/fences/connection reuse only; no measured runtime comparison |

Fixed findings include `startup_run_idempotency_conflict`, `startup_run_invocation_conflict`, `startup_run_invocation_expired`, `startup_run_write_ack_failed`, `startup_run_recovery_required` and `startup_manual_run_required`. No executed failure logs, candidate data, mail or raw private evidence are published. A completed local import grants no platform/account/application authority.

Final reproduction: coordinated `scripts/run_acceptance.py`, Rust `startup_runs`, complete dedicated disposable PG `startup_run_*`, later full startup/public research/UI/browser gates. Commands are documented, not executed now. Continue source registry/owner startup endpoints/provider status, durable public research and remaining dashboard/registry/provider/CLI/conversation/eight-platform source before coordinated gates and reviewed migration/install/live evidence. Last validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard+262 native PG=455 distinct passes; not current-head evidence.58/42 held. Last observed STOP162/lifetime4/hour1/three uncertain quarantines/strict worker receipts0 and filters/identity/PDF/focus rules remain unchanged. No hosted Actions, merge, cleanup, sending or installation.
