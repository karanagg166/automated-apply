# Durable startup UUID resources and local completion — source checkpoint2026-11-17

Implementation [dcbaadf48ea8271377e653f67a4aac62d256b5f7](https://github.com/karanagg166/automated-apply/commit/dcbaadf48ea8271377e653f67a4aac62d256b5f7), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested/uninstalled source; no actual provider/recovery request, production SQL, browser or Mac acceptance.

Existing startup saved-run GET now has UUID PUT for original native job-led admission and empty-body POST /complete for retained local work. Normalized source/body validation precedes the shared request slot; methods, nil IDs, manual PUT and arbitrary completion fields refuse. Legacy keyed POST/manual company-first remain separate compatible paths. Local complete reads the original parent/child and can finish retained jobs/rankings/company results without a provider client. Unknown child states return saved status rather than obtaining another remote grant. Paid acknowledged-run read recovery remains an explicit separate child-job operation.

Preview reports effective provider query separately from original company filters, native readiness and selected actual-query paid estimate/caps/blocker. No provider calls, budget reservation or owner-fence writes occur. Exact UUID gateway policy adds PUT and narrow local-complete POST; canonical policy and both generated copies are source-generated identically. Full API inventory/OpenAPI/types remain a final combined gate.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source/generation/formatting | PASS(source only) | Closed UUID methods, original PUT, saved GET/local complete, effective provider query and paid preview caps/readiness, shared host resources and narrow generated gateway policy |
| New standard declaration | NOT TESTED |1: exact startup UUID GET/PUT/local POST and invalid path/nil/method refusal |
| New PG/HTTP declarations | NOT TESTED |5: original public PUT/replay/read/local-complete; failed parent local recovery; changed/manual/auth/body guards; unknown paid child local completion without IO; actual paid-query estimate/read-only preview |
| New gateway declaration | NOT TESTED |1: UUID PUT/GET and local POST-only path surface |
| Current tests/build/check/lint/types | NOT TESTED |New executed tests0. Remaining agreed source precedes combined gates |
| Actual provider/Mac/browser/install | NOT TESTED |No real token file, production SQL, provider/recovery request, browser or installation operation |
| Timing/resources | NOT TESTED |Existing shared request slot/temporary connection; no new pool; no measured comparison |
| Startup durable dashboard | NOT TESTED/incomplete |Next source replaces prior in-memory key/POST flow with retained UUID/GET-only mount/local recovery and paid consent |

Fixed codes include startup_run_idempotency_conflict, startup_provider_orchestration_not_implemented, startup_run_write_ack_failed and invalid_startup_query. Fixture failures remain declarations; no raw private/provider log is published. Native implementation/readiness does not establish actual platform discovery or application acceptance.

Deferred reproduction: `cargo test --locked -p automated-apply-agents --test startup_job_led`; dedicated PostgreSQL harness `cargo test --locked -p automated-apply-agents --test postgres startup_uuid -- --ignored --test-threads=1`; `pnpm -C frontend test -- tests/phase3-proxy.test.ts`. Full source registry/public/paid startup/security/gateway/type/browser regressions remain final combined gates; none ran in this checkpoint.

Last validated checkpoint remains9c4ace570535a5856184775f8045ee89eafdd05f:193 standard Rust+262 dedicated PG=455 distinct passes, which do not validate this head. Estimate held58%/42%. Last observed queue STOPPED162; lifetime4/hour1, three uncertain jobs quarantined, one fourth admission remaining, strict worker receipts0. Identity/PDF/filter/focus constraints remain. No hosted Actions, merge, cleanup, sending/application, paid provider or installed-service operation.
