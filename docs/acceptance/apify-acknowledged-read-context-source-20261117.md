# Acknowledged Apify evidence and fixed read targets — source checkpoint2026-11-17

Implementation [75132e923e22a06788ea8ec59484abb1ebd80680](https://github.com/karanagg166/automated-apply/commit/75132e923e22a06788ea8ec59484abb1ebd80680), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested/uninstalled pure source. Durable read admissions, checkpoint transport and owner read-recovery routes remain incomplete.

Original selected run evidence now retains only the closed acknowledged build/timeout/restart/cap/item options. Later provider status must preserve these original options as well as original actor/run/build/start/cap/dataset and terminal status. Restoration round-trips selected actor/run evidence through the same bounded parser; extra or promoted flags, altered identity and invalid options refuse. Original private/raw provider metadata is excluded.

A separate pure ReadContext can construct only fixed GET targets for an acknowledged run, original build and original dataset. It requires the original75-second intent expired, a bound selected run/reservation, matching saved configuration/query and a24-hour recovery window. A newly accepted successful status is required before original build/dataset use; dataset offsets remain0/50 under the original item limit. This context grants no HTTP, reservation, paid start or abort. The durable caller must independently validate actual SQL scope/reservation, current reviewed configuration/credential, read budget and checkpoints. Unknown starts with no acknowledged run remain held; no guessing/latest-run search.

| Gate | Status | Evidence |
| --- | --- | --- |
| Pure source/formatting | PASS(source only) | Closed acknowledged options, original restoration/round-trip checks, fixed GET-only context and fresh-success gate |
| New standard fixtures | NOT TESTED |6: selected round-trip/privacy/GET; expired original/TTL/missing evidence; source/query/scope/attachment/start mutations; promoted flags/invalid options/identity; changed status identity/options; fresh success/build and bounded dataset offsets |
| Current tests/build/check/lint/types | NOT TESTED |New executed tests0; remaining agreed source precedes combined gates |
| Actual provider/Mac/browser/install | NOT TESTED |No real token file, API/status request, production SQL, browser or installation operation |
| Timing/resources | NOT TESTED |Pure data/target construction only; no measured comparison |
| Durable read grant/transport/owner recovery | NOT TESTED/incomplete |Next source: maximum3 separately keyed read rounds,4GETs/45seconds each,5-minute spacing/cooldown, durable response/finding CAS and explicit owner action |

Fixed codes include apify_read_original_checkpoint_invalid, apify_read_original_still_active, apify_read_original_expired, apify_execution_evidence_invalid and apify_run_original_binding_changed. Declared failures are unexecuted fixtures. No raw log is published; retained preliminary cost/termination observations do not establish final billing, independent termination or a refund.

Deferred reproduction: `cargo test --locked -p automated-apply-agents --test apify_job_plan`, followed by original paid admission/transport/intake/owner fixtures during the final combined gate because selected checkpoint shape now contains closed acknowledged options. No current tests/build/check were run.

Last validated checkpoint remains9c4ace570535a5856184775f8045ee89eafdd05f:193 standard Rust+262 dedicated PG=455 distinct passes; older results do not validate this head. Estimate held58%/42%. Last queue observation STOPPED162, lifetime4/hour1, three uncertain jobs quarantined, one fourth admission remaining and strict worker receipts0. Identity/PDF/filter/focus constraints remain. No hosted Actions, merge, cleanup, sending/application, paid provider or installed-service operation. GitHub CLI publication fallback is used while the connector is unavailable.
