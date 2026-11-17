# Original paid research admissions — source checkpoint 2026-11-17

Implementation [b8b83b7577271a572408cfdcb213cc20efedf215](https://github.com/karanagg166/automated-apply/commit/b8b83b7577271a572408cfdcb213cc20efedf215), branch `feat/rust-agent-runtime`, [PR 50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled domain source. Provider transport, retained findings and host/dashboard integration follow.

Paid professional search now has explicit saved rights/credential/domain/opt-in gates and an original UUID admission. Before any future transport, the domain service commits exact normalized input, configuration hash, bounded company snapshot, original 30-second deadline, opaque single-use grant and one durable local search-request reservation. Replaying or reading the saved intent cannot reconstruct that grant. Expired unresolved intent is qualified outcome_unknown without GET writes, deadline renewal or a second reservation. Manual and paid imports cannot reuse the same UUID to change operation type.

The existing numeric budget/cooldown ledger now supports a distinct serper / people_ namespace. Units are local search requests, not verified provider credits or dollars. Prior uncertain reservations remain consumed and cross-month cooldown blocks new admission. Reservation/month rows are reread after triggers, again after journal insertion, and terminal findings independently reread their reservation. No current balance, provider charge, credential entitlement or live availability is inferred. Saved status excludes keys and reviewed domain URLs.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Private settings, original intent/grant, domain snapshot, request reservation/replay/read qualification, provider namespaces and post-trigger budget ACKs; formatting applied |
| Standard fixtures | NOT TESTED | 2 declarations covering independent rights/credential/domain/paid gates, local budget units/defaults and bounded private settings |
| Native PG fixtures | NOT TESTED | 9 declarations: original claim/replay; input/manual-paid conflicts; expired read; prerequisites/no admission; cap/cross-month cooldown; journal/budget/after-journal trigger rollback; company ambiguity; no held transaction; provider namespace/invalid retained record |
| HTTP / frontend additions | NOT TESTED | None in this slice; UUID owner endpoint/controller/dashboard recovery remain pending |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests: 0; complete source precedes combined gates |
| Actual Mac/provider/install | NOT TESTED | No credential, account, provider execution, real budget, browser, production or installation action |
| Timing/resources | NOT TESTED | Bounded source snapshots/deadline/owner fence only; no measured speed or memory claim |

Fixed codes include `public_research_permission_required`, `public_research_paid_opt_in_required`, `public_research_official_domain_not_authorized`, `public_research_company_identity_ambiguous`, `public_research_request_conflict`, `public_research_original_dispatch_unconfirmed` and `contact_budget_write_ack_failed`. No executed failure logs or private evidence are published.

Deferred reproduction: `cargo test --locked -p automated-apply-agents --test people_research_settings`, full dedicated disposable PG `people_search_*` and shared `contact_budget_*`, then `uv run --no-project python scripts/run_acceptance.py` and later provider/UI/install/live gates. Continue fixed transport, retained parsed findings and conservative local completion before calling the research workflow operational.

Last validated `9c4ace570535a5856184775f8045ee89eafdd05f` remains 193 standard + 262 dedicated native PG = 455 distinct passes, not current-source evidence. Estimated completion remains 58% / 42%. Last observed STOP revision 162, lifetime allowance 4/hourly 1, three uncertain quarantines, zero strict worker receipts and all current filters/identity/PDF/focus rules remain unchanged. No hosted Actions, merge, cleanup, sending or installation occurred.
