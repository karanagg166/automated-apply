# Read-only Naukri dashboard summary — source checkpoint 2026-11-16

Implementation [`983838baba7f23aff1a7046b7082390f5263a719`](https://github.com/karanagg166/automated-apply/commit/983838baba7f23aff1a7046b7082390f5263a719), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Uninstalled source, with compilation and tests deferred.

GET /api/v1/execution/naukri now projects preparation controls, retained decisions/executions, current profile/resume metadata, selected ordinary-browser status, account-session observations, alert generations and receipt counts in a REPEATABLE READ READ ONLY transaction. PUT remains the separate guarded preparation configuration endpoint. The actual legacy capability function is frozen through the existing schema generator; discovery/form/source candidates remain unaccepted and recurring submission disabled. A sidebar/account observation is not an identity proof or API connection.

Status policy validation uses snapshot reads rather than mutation-only profile share locks. Expired alerts are omitted without rewriting their stored records on GET. Source leases, browser secrets, alert leases and page tokens are excluded; account generation must match before an existing local alert policy appears enabled. Those saved policies are observations, not activation of the unfinished Rust alert worker. Future heartbeats do not count as current worker evidence. Whole-family runtime acceptance and the original first strict dispatched/current-account receipt gate remain separate.

Receipt summaries stream100 retained records at a time and aggregate packets in SQL instead of loading every packet. Damaged evidence increases records_requiring_review; it is not counted as submitted and still blocks replay elsewhere. Existing legacy preparation decision/execution/alert arrays have a10000-record fail-closed response bound; those full inventories still need later paging if that bound is reached. The application queue's independent paginated status/history remains separate. No timing or memory improvement has been measured.

| Gate | Result | Evidence / limitation |
| --- | --- | --- |
| Source/schema generation | PASS (source only) | GET/PUT method boundary, coherent snapshot summary, frozen actual capabilities and private reference filtering; formatter applied |
| New standard tests | NOT TESTED | 1 declaration compares the capability function with actual Python AST execution, without application settings |
| New native PostgreSQL tests | NOT TESTED | 4 declarations: held owner lock/read-only policy/status/private alert preservation;10102 retained receipts including damaged history; account-generation alert projection/private token omission; HTTP auth/GET/PUT/methods |
| Compile/Clippy/lint/all suites | NOT TESTED | New executed tests0; combined final gate deliberately deferred |
| Actual Mac/worker/browser/provider/install | NOT TESTED | No source installation, provider/browser call, production database read or new receipt |
| Actual resource/query timing/restart/concurrency | NOT TESTED | Batching describes source only; no sampled performance comparison |
| Complete source parity | NOT TESTED | Owner import, full legacy preparation worker/recovery, Telegram/Gmail/outreach/provider/platform services remain unfinished |
| Focus/strict receipt/awake/locked/24h | BLOCKED / NOT TESTED | Existing account/focus/operator migration gates stand; strict worker receipts0 |

Last fully validated source9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 dedicated native PostgreSQL passes,455 distinct; it does not validate this head. No new executed failure log exists. Static sanitized failures include execution_active_inventory_limit, invalid_execution_saved_record, execution_database_error and execution_read_commit_failed. Private profile facts, mail, browser secrets and transcript bytes are not published.

After all source is integrated, reproduce through `scripts/run_acceptance.py`, including tests/execution_owner.rs and tests/support/execution_summary_pg.rs. Then complete reviewed whole-family migration/install and actual per-platform acceptance under the [plan](../plans/completion-execution-20261116.md). Estimate58% complete /42% remaining is unchanged; no reliable finish time is claimed. Installed STOP162, lifetime4/hour1, three quarantines, current filters/history/identity/PDF, Gmail read/draft-only and browser focus protections remain. No hosted Actions, merge, live activation or cleanup.
