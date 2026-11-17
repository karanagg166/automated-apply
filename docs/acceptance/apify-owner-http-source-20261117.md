# Reviewed paid discovery owner HTTP — source checkpoint2026-11-17

Implementation [c9ab52784201505cf755805ea91bae4cd876cb2d](https://github.com/karanagg166/automated-apply/commit/c9ab52784201505cf755805ea91bae4cd876cb2d), including [3c233ac](https://github.com/karanagg166/automated-apply/commit/3c233ac235272a825765058052ed708aca864a68), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested and uninstalled source; no actual paid provider, production database or Mac/browser acceptance.

Existing authenticated preview, keyed POST, UUID PUT/GET and empty-body local complete routes now select the original public or paid implementation. Paid original POST keys use a separate deterministic namespace; public key mapping stays unchanged. Source/body validation precedes the shared transient semaphore and temporary connection. Saved native kind uses bounded private original keys in a read-only snapshot; conflicting scopes refuse and legacy reads refuse either native scope appearing in a later snapshot. Legacy paid rows cannot become fresh paid intent. Local complete does not accept arbitrary provider targets or restart an Actor.

Source registry adds native implemented/owner-run flags and a separate saved execution readiness projection requiring local token, exact USD caps, reviewed permitted route, pinned opaque build/schema and bounded input. Original legacy source availability is preserved as a separate configuration view. Invalid optional paid settings disable execution while public routes and terminal saved reads remain available. Preview expands the saved query and reports selected estimated/capped costs and a fixed blocker without provider calls, budget reservation or owner-fence writes. Costs remain local estimates/full-cap limits, not current provider credits or final billing. Fixed errors distinguish opt-in/input, conflicts, budget/cooldown and uncertain commit/transport outcomes.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source implementation/formatting | PASS(source only) | Native host config, paid routing, original-key read/complete selection, saved preview/readiness and sanitized errors |
| New standard declarations | NOT TESTED |1: paid request namespace, explicit default opt-in false, unsupported manual data and readiness distinction |
| New PG/HTTP declarations | NOT TESTED |7: read-only preview/caps/no owner lock; original PUT/GET/replay/complete; keyed POST/conflict; parent-failure local recovery; unknown start/no second POST; auth/opt-in/method/body guards; legacy/ambiguous native scope refusal |
| Existing fixture updates | NOT TESTED |3: pure owner paid validation; registry legacy comparison excludes only additional native readiness and asserts it independently; earlier unsupported-source HTTP fixture now distinguishes paid opt-in422 from unsupported manual501 |
| Current tests/build/check/lint/types | NOT TESTED |New executed tests0; remaining agreed source precedes combined gates |
| Actual provider/Mac/browser/install | NOT TESTED |No real token file, provider operation, production SQL, browser or installation operation |
| Timing/resources | NOT TESTED |One existing request permit and temporary connection; extra bounded saved-kind read snapshot is unbenchmarked |
| Paid dashboard/full API inventory/types/known-run recovery | NOT TESTED/incomplete |Subsequent source work remains |

Fixed codes include apify_paid_opt_in_required, apify_reviewed_execution_route_required, apify_execution_budget_exhausted, apify_execution_cooling_down, apify_intake_finding_missing, discovery_run_original_scope_ambiguous and apify_owner_commit_outcome_unknown. Fixture paths are declared, not executed errors. No raw provider/private log is published.

Deferred reproduction: `cargo test --locked -p automated-apply-agents --test public_job_owner`; dedicated disposable PostgreSQL harness `cargo test --locked -p automated-apply-agents --test postgres apify_owner_http -- --ignored --test-threads=1`. Full source registry/public owner/native gateway/type contracts remain final combined gates. Fixture success will not establish production/provider acceptance.

Last validated checkpoint remains9c4ace570535a5856184775f8045ee89eafdd05f:193 standard Rust+262 dedicated PG=455 distinct passes; these older results do not validate this head. Estimate held58%/42%. Last queue observation STOPPED162, lifetime4/hour1, three uncertain jobs quarantined, one eligible fourth admission, strict worker receipts0. Identity/PDF/filter/focus constraints remain. No hosted Actions, merge, cleanup, sending/application, paid provider or installed-service operation. GitHub CLI publication fallback is used while the connector is unavailable.
