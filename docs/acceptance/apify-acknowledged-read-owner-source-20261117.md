# Explicit keyed owner read-recovery resources — source checkpoint2026-11-17

Implementation [f67fc0233f86c8725f07eb9df7ec2655827e68eb](https://github.com/karanagg166/automated-apply/commit/f67fc0233f86c8725f07eb9df7ec2655827e68eb), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested and uninstalled source; no actual provider/status request, production SQL, browser or Mac acceptance.

Native owner routes now expose distinct nonzero parent/read UUID resources at discovery/runs/{parent}/reads/{read}. GET reads retained state only; explicit PUT with exactly{} may consume a separate acknowledged-run read claim; POST to /complete reconstructs retained pages locally. Methods, arbitrary run/dataset/restart/body fields and query strings refuse. A retained native paid parent is required, with its actual parent scope validated; public and legacy rows gain no recovery authority. Parent job ingestion/ranking completion remains a separate existing local action. Ordinary parent GET/PUT/local-complete cannot dispatch these recovery reads.

Requests share existing owner auth, transient semaphore, temporary connection and host timeout. Closed paid parent usage now exposes only read count/limit, original last read UUID and next allowed read time for response-loss recovery. Completed/read saved state remains readable without current credentials/configuration; optional bad paid configuration does not hide saved history. Fixed errors distinguish missing read404, context/authority409, spacing/lifetime429 and unknown commit timeout.

Two narrow gateway patterns allow only keyed read GET/PUT and local completion POST, preserving owner session/CSRF validation. Source policy and both generated package copies use the same canonical formatted bytes. Full API inventory/OpenAPI/type work remains a final gate; the generated policy is source generation, not test evidence.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source/generation/formatting | PASS(source only) | Exact owner resource parser, paid parent guard, distinct saved/read/local paths, allowance metadata, shared resource slot, sanitized errors and gateway copies |
| New standard declaration | NOT TESTED |1: exact distinct/nonzero UUID routes, closed methods and provider-target/extra-path refusal |
| New PG/HTTP declarations | NOT TESTED |6: explicit PUT/saved GET/separate parent completion; auth/body/method/query; legacy/public parent refusal; failed finding/local completion; unknown start/no new call; existing request slot with readable local metadata |
| New frontend gateway declarations | NOT TESTED |2: narrow route/method surface; CSRF denial before backend and exact authenticated empty PUT forwarding |
| Current tests/build/check/lint/types | NOT TESTED |New executed tests0; remaining agreed source precedes combined gates |
| Actual provider/Mac/browser/install | NOT TESTED |No real token file, recovery request, production DB, browser or installation operation |
| Timing/resources | NOT TESTED |Existing temporary connection/shared permit; extra bounded saved-parent snapshot is unbenchmarked; no measured comparison |
| Durable read dashboard pointer/consent | NOT TESTED/incomplete |Next source work; later runtime/tool/platform and final combined/live gates remain |

Fixed codes include apify_read_intent_not_found, apify_read_native_owner_required, apify_read_original_checkpoint_invalid, apify_read_spacing_required, apify_read_lifetime_limit, apify_read_local_completion_required and apify_read_commit_outcome_unknown. Fixture failures are declarations, not actual error logs; no raw private logs are published. These bounded GET rounds do not alter Naukri Apply caps or resolve unknown paid starts without an acknowledged run.

Deferred reproduction: `cargo test --locked -p automated-apply-agents --test public_job_owner`; dedicated PostgreSQL fixture harness `cargo test --locked -p automated-apply-agents --test postgres apify_read_http -- --ignored --test-threads=1`; `pnpm -C frontend test -- tests/phase3-proxy.test.ts`. Full security/gateway/native API/type/browser regressions remain combined gates. Fixture success will not establish production/provider acceptance.

Last validated checkpoint remains9c4ace570535a5856184775f8045ee89eafdd05f:193 standard Rust+262 dedicated PG=455 distinct passes, which do not validate this head. Estimate held58%/42%. Last observed queue STOPPED162, lifetime4/hour1, three uncertain jobs quarantined, one fourth admission remaining and strict worker receipts0. Identity/PDF/filter/focus constraints remain. No hosted Actions, merge, cleanup, sending/application, paid provider or installed-service operation. GitHub CLI publication fallback is used while its connector is unavailable.
