# Coupled original owner run and public admission — source checkpoint 2026-11-17

Implementation [da0ca27ce351e7f35fe5e22bfa032d78dd594085](https://github.com/karanagg166/automated-apply/commit/da0ca27ce351e7f35fe5e22bfa032d78dd594085), branch `feat/rust-agent-runtime`, [PR 50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source; no current production acceptance.

One owner-first SERIALIZABLE transaction now creates the actual discovery_runs row, private original request/profile/query scope, public child admission and shared source window. Final independent acknowledgements follow all parent writes and triggers. The actual run UUID binds its child; compatibility-key collisions, legacy runs without native scope and preexisting unscoped children are refused. Profile changes during admission roll back the entire transaction. Saved reads and UUID replays return original retained state without new grants, profile refresh, source-window extension or HTTP. Original acquisition consumes the opaque child once and retains its finding; the parent honestly remains running/local_intake_pending with zero inserted jobs until separate SQL intake exists. A shorter configured owner deadline caps the nonrenewable child lease; finite parsing finishing after deadline cannot report complete traversal.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Actual parent row, private scope, atomic child/window admission, post-trigger ACKs, retained read/acquisition and formatting applied |
| Dedicated PG additions | NOT TESTED | 12 declarations covering admission/replay, changed request, missing board, compatibility collision, unscoped child, private profile pin/disabled profile, trigger rollback, saved tampering/legacy refusal, retained loopback acquisition and shorter deadline |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests: 0; complete source precedes combined gates |
| Actual Mac/native/provider/install | NOT TESTED | No current production DB, browser, native provider or installation operation |
| Timing/resources | NOT TESTED | Existing connection reused; no new pool; deadline limits are source only, no measured comparison |
| SQL local job/company intake | NOT TESTED / incomplete | No saved job IDs, local intake receipt, rankings or application authority claimed |

Fixed failure codes include discovery_run_request_conflict, discovery_run_compatibility_key_conflict, discovery_run_original_scope_missing, discovery_run_source_id_already_claimed, discovery_run_write_ack_failed, invalid_discovery_profile_scope and public_job_original_grant_expired. No executed failure logs or private candidate/provider data are published.

Deferred reproduction: `cargo test --locked -p automated-apply-agents --test postgres -- --ignored --test-threads=1` using the documented disposable PG harness and `uv run --no-project python scripts/run_acceptance.py`, after remaining source. Continue guarded atomic SQL job/company/observation/receipt intake, parent local completion and startup/owner dashboard orchestration, reviewed Apify execution and remaining runtime/platform source.

Last validated `9c4ace570535a5856184775f8045ee89eafdd05f` remains 193 standard +262 dedicated native PG =455 distinct passes, not current-source evidence. Estimate stays 58% /42%. STOP162, lifetime4/hourly1, three uncertain quarantines, zero strict worker receipts and all identity/PDF/filter/focus constraints remain unchanged. No hosted Actions, merge, cleanup, sending or installation occurred.
