# Original owner-run and private profile scope — source checkpoint 2026-11-17

Implementation [1e8734c4e213d9d2feaaa53d8dcb3c92a5bd946b](https://github.com/karanagg166/automated-apply/commit/1e8734c4e213d9d2feaaa53d8dcb3c92a5bd946b), branch `feat/rust-agent-runtime`, [PR 50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source; parent/child admission and SQL intake integration follow.

The actual RunRequest schema/defaults and original sorted-JSON request hash are ported, excluding the compatibility idempotency field as in the existing service. Pure public-source scope distinguishes owner-explicit query from profile-expanded provider terms and preserves use_profile/allow_paid input. It rejects unsupported public sources and manual records before remote authority. A private canonical profile UUID/version/content-hash pin binds all saved facts without copying raw candidate/contact/resume fields into the plan. Disabled profile use ignores supplied profile data; an absent enabled profile remains distinguishable through the flag and null pin. Query expansion is bounded and actual DTO validation remains enforced.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Actual RunRequest schema generation, native defaults/hash, query expansion, private profile pin, public scope guards and formatting applied |
| Standard additions | NOT TESTED | 4 declarations: 32 actual request DTO cases, 16 actual hash cases, 24 actual query-expansion cases and private pin/disabled-profile/manual/size guards; 72 actual comparisons declared |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests: 0; full source precedes combined gates |
| Actual native provider / Mac / install | NOT TESTED | No native provider, account/application/browser, production DB or installation operation |
| Timing/resources | NOT TESTED | Pure source/hash limits only; no measured comparison |

The deferred oracle extracts the actual RunRequest/build_query behavior without importing provider clients, ORM or application settings. Native public planning additionally rejects a malformed profile pin and oversized request rather than assuming a canonical profile. Scope construction grants neither provider dispatch nor local ingestion. Fixed failures include `invalid_discovery_run_request`, `discovery_run_request_limit`, `invalid_discovery_profile_scope`, `public_job_manual_source_required` and `public_job_source_unknown`. No raw private data or executed failure logs is published.

Deferred reproduction: `uv run --no-project python -m rust.scripts.export_startup_contracts --check`, `cargo test --locked -p automated-apply-agents --test public_job_scope`, earlier source suites and full `uv run --no-project python scripts/run_acceptance.py` after remaining source. Continue parent/child original scope admission and owner-fenced atomic job/company/source-observation/local-receipt intake with current context/TTL/history checks, then startup orchestration, owner endpoints/dashboard recovery, reviewed Apify execution and remaining runtime/platform source.

Last validated `9c4ace570535a5856184775f8045ee89eafdd05f` remains 193 standard +262 dedicated native PG =455 distinct passes, not current-source evidence. Estimate remains 58% /42%. STOP162, lifetime4/hourly1, three uncertain quarantines, zero strict worker receipts and all identity/PDF/filter/focus constraints remain unchanged. No hosted Actions, merge, cleanup, sending or installation occurred.
