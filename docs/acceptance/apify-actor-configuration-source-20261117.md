# Apify actor configuration — source checkpoint 2026-11-17

Implementation [a26d8006d85a70a6a6e85ad876ee4c4fa1dd1149](https://github.com/karanagg166/automated-apply/commit/a26d8006d85a70a6a6e85ad876ee4c4fa1dd1149), branch `feat/rust-agent-runtime`, [PR 50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. This checkpoint is untested, uninstalled source.

The native configuration dependency now freezes the actual ActorConfiguration model without importing provider clients or application settings. It normalizes public review URLs, pinned builds, declared mappings, costs and review flags. The pure input builder requires a unique limit mapping, preserves fixed inputs and overrides only mapped query fields. Actor identifiers and collection inputs use the existing denied-pattern policy; cookie, session, password, token and LinkedIn collection inputs cannot pass that policy.

Preflight checks saved enablement, review expiry within the next 24 hours, inclusive platform/account cost review, local credential presence and positive bounded budget configuration. Its output always says `live_verified: false` and `dispatch_authorized: false`. Saved configuration and connected MCP availability establish neither runtime credentials nor current provider entitlement. There is no account probe, actor POST, default actor, implicit budget or transport in this slice. Expanded input and output are capped at 64 KiB.

The startup filter normalizer also preserves Pydantic's omitted integer default score versus explicitly supplied floating score, which matters for exact original request hashes. Existing startup hash/contract fixtures cover that distinction but remain unrun.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Frozen actual actor schema, input builder, denied collection patterns, qualified preflight and acceptance drift stage; formatting applied |
| Standard fixtures | NOT TESTED | 3 declarations: 48 actual DTO cases; 36 actual mapping/identifier/collection cases; 16 actual preflight cases plus explicit bounds and no-authority assertions |
| Native PG / frontend additions | NOT TESTED | No new declarations in this slice; prior source remains unrun |
| Current tests, build, checks, lint, types | NOT TESTED | New executed tests: 0; full source precedes combined gates |
| Actual Mac, provider, runtime, installation | NOT TESTED | No account, credential, HTTP, browser, production or installed operation |
| Timing and resources | NOT TESTED | Bounds are source rules; no measured speed or memory improvement |

Sanitized finding codes include `invalid_apify_actor_configuration`, `apify_unique_bounded_limit_mapping_required`, `apify_collection_method_not_authorized`, `apify_actor_review_expired_or_missing` and `apify_positive_bounded_budget_required`. No executed failure logs or private configuration are published.

Final reproduction, deferred: `uv run --no-project --python .venv/bin/python python -m rust.scripts.export_apify_contracts --check`, `cargo test --locked -p automated-apply-agents --test apify_config`, then the coordinated `uv run --no-project python scripts/run_acceptance.py` and applicable provider/install/live gates. Continue the native source registry, startup owner endpoints, durable public research/provider execution and remaining agreed full source before running those gates.

Last validated checkpoint `9c4ace570535a5856184775f8045ee89eafdd05f` remains 193 standard + 262 dedicated native PG = 455 distinct passes; it is not current-source evidence. Estimated completion remains 58% / 42%. Last observed STOP revision 162, lifetime allowance 4/hourly 1, three uncertain quarantines, zero strict worker receipts, filters, identity/PDF checks and focus constraints are unchanged. No hosted Actions, merge, cleanup, sending or installation occurred.
