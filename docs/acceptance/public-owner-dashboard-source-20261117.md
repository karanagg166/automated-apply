# Public discovery owner API and durable dashboard — source checkpoint2026-11-17

Implementation [39be30083d6840315bbeb3519c43731ae542161e](https://github.com/karanagg166/automated-apply/commit/39be30083d6840315bbeb3519c43731ae542161e), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source; full native contract/combined/live acceptance remains pending.

Original preview/POST/GET paths and UUID PUT resources now dispatch through owner authentication, existing CSRF gateway, the single shared transient permit and one temporary connection. Original POST requires a stable compatibility key mapped into a fixed UUID namespace. DTO/source/method/query checks precede connection/admission. Preview uses a read-only snapshot without owner fencing or provider calls. UUID GET reads saved state only; an empty POST to the exact UUID/complete path can finish retained observations locally and cannot create remote authority. Unsupported manual/paid execution remains explicit501 until its separate lifecycle is implemented. Seven public providers expose owner-run implementation metadata independently from live verification; existing scheduled feeds and startup job-led paths remain separately qualified.

Missing original native scope never becomes an execution grant. A legacy GET projects bounded saved counts/IDs with qualification, omits private error/usage blobs and marks running legacy work recovery_required; it does not adopt/replay the row. Missing sidebar entries/transcript recovery remain separate account-continuity findings.

The dashboard persists only opaque UUID/source before original PUT, uses cross-tab Web Locks, reads saved GET on mount and recovers retained findings through local-only completion. Network loss, changed criteria and reload do not discard unresolved pointers. New original dispatch requires its explicit consent;404 recovery reuses the original UUID/source and requires consent again. A reviewed terminal GET may release the browser pointer while DB history/source pacing remain untouched. Result identity/count/shape checks refuse malformed responses. Criteria remain locked around unresolved admissions; a missing server admission permits review of the same source. Existing component fixtures now exercise the native paths.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS(source only) | Owner routes, client/config connection, closed error mapping, metadata qualification, UUID dashboard recovery and formatting applied |
| Contract generation | PASS(generation only) | Fixed gateway PUT/complete POST rules copied to both package-local HTTP policies; no tests/check mode executed; full native API inventory/types remain final-gate work |
| New Rust standard additions | NOT TESTED |3 declarations: closed routes/methods, stable compatibility identity/unsupported source refusal, distinct owner/feed/startup metadata |
| New PG/HTTP additions | NOT TESTED |7 declarations: read-only preview without owner fence; original UUID loopback run/replay; original keyed POST/conflict; sanitized legacy read; local-only completion/GET boundaries; auth/method/query/key/source guards; shared transient permit |
| New frontend additions | NOT TESTED |11 durable helper cases and1 component reload/review case =12 new declarations |
| Existing frontend fixture updates | NOT TESTED |9 component cases adapted for native UUID transport, Web Locks, response-loss GET and truthful fixture UUID/counts; no extra distinct tests claimed |
| Current tests/build/check/lint/types | NOT TESTED |New executed tests:0. Total new declarations in this checkpoint:22; complete source still precedes combined gates |
| Actual native/provider/browser/Mac/install | NOT TESTED |No current production DB, browser, provider, installation, application or actual live acceptance |
| Timing/resources | NOT TESTED |Existing shared permit/connection budget retained; no new pool; no measured timing comparison |

Fixed codes include discovery_run_idempotency_key_required, discovery_source_execution_not_implemented, invalid_discovery_query, discovery_method_not_allowed, discovery_run_outcome_unknown and existing context/identity holds. Source-only failure paths were not exercised. No raw private logs, provider responses or candidate data are published.

Deferred reproduction: `cargo test --locked -p automated-apply-agents --test public_job_owner`, dedicated disposable PG harness `cargo test --locked -p automated-apply-agents --test postgres -- --ignored --test-threads=1`, `pnpm -C frontend test -- tests/job-discovery-attempt.test.ts tests/job-discovery.test.tsx`, HTTP policy/native contract inventories and full `uv run --no-project python scripts/run_acceptance.py` after remaining source. Continue startup job-led original child orchestration, reviewed Apify execution and remaining owner dashboard/runtime/platform source.

Last validated `9c4ace570535a5856184775f8045ee89eafdd05f` remains193 standard+262 dedicated native PG=455 distinct passes, not current-source evidence. Estimate stays58%/42%. STOP162, lifetime4/hourly1, three uncertain quarantines, zero strict worker receipts and focus/identity/PDF/filter rules remain unchanged. No hosted Actions, merge, cleanup, sending or installation occurred.
