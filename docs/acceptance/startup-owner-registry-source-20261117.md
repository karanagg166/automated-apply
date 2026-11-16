# Startup source registry and owner API — source checkpoint 2026-11-17

Implementation [e97c210dc19b528ca030666d5950b09ddcf9498e](https://github.com/karanagg166/automated-apply/commit/e97c210dc19b528ca030666d5950b09ddcf9498e), branch `feat/rust-agent-runtime`, [PR 50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

The owner API now exposes saved job/startup source metadata, read-only startup preview, original manual company-first POST and retained run GET. Preview reads one repeatable-read snapshot for saved profile preferences without taking the owner fence. Source metadata performs no database or provider operation after the normal owner boundary. Preview/import/read share the existing transient request permit and connection budget; no new pool, process or scheduler is introduced.

Registry output preserves existing source prerequisites while excluding private actor inputs, board employers, credentials and evidence URLs. Saved configuration is explicitly separate from current provider verification, dispatch authorization and native implementation availability. Himalayas/WWR feed capabilities remain separate from startup job-led orchestration. Public search additionally requires a valid permission evidence URL before reporting availability. Unsupported directories and unported startup provider orchestration remain explicit; the latter returns 501 before admitting a run. This is a remaining implementation dependency, not accepted provider functionality.

Manual imports retain the original domain claim, permission checks, atomic ingestion and scoped ranking. Stable request keys are required to support safe response-loss recovery. Conflicting keys return 409; missing keys and invalid contracts return 422. The host passes the original input to admission so a second default normalization cannot change the original request hash. Retained GET never replays provider or import work.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Registry, private configuration, preview/manual/read routing, shared permit and sanitized failures; formatting applied |
| Standard fixtures | NOT TESTED | 3 declarations: 10 full saved settings comparisons against actual registry/adapter rules; permission/bounds/privacy; closed route methods |
| Native PG / loopback HTTP | NOT TESTED | 8 declarations: profile snapshot/zero writes; explicit and absent preferences; owner-lock independence/invalid inputs; auth/config privacy; exact original hash/replay/read; conflicts/unported/missing input; method/query/body bounds; transient contention with readable source status |
| Frontend additions | NOT TESTED | None in this slice; durable startup dashboard recovery remains pending |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests: 0; full source precedes combined gates |
| Actual Mac/provider/install | NOT TESTED | No live account, provider, browser, production or installation action |
| Timing/resources | NOT TESTED | Source reuses connection/permit budgets; no measured performance claim |

Sanitized codes include `invalid_discovery_source_settings`, `startup_source_unknown`, `startup_run_idempotency_key_required`, `startup_run_idempotency_conflict`, `startup_provider_orchestration_not_implemented` and `bounded_background_request_running`. No executed failure logs or private evidence are published.

Deferred reproduction: `cargo test --locked -p automated-apply-agents --test source_registry`, complete dedicated disposable PG `startup_owner_*`, then `uv run --no-project python scripts/run_acceptance.py` and later full provider/UI/install/live gates. Continue durable public research, startup provider orchestration, dashboard/registry/CLI/conversation and remaining agreed full source. No provider path may be marked operational merely because its configuration validates.

Last validated `9c4ace570535a5856184775f8045ee89eafdd05f` remains 193 standard + 262 dedicated native PG = 455 distinct passes, not current-source evidence. Estimated completion stays 58% / 42%. Last observed STOP revision 162, lifetime allowance 4/hourly 1, three uncertain quarantines, zero strict worker receipts and all current filters/identity/PDF/focus rules remain unchanged. No hosted Actions, merge, cleanup, sending or installation occurred.
