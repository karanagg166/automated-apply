# Account/profile controls — source checkpoint 2026-11-16

Implementation [`a7415da954e69bdf09d9792f2334385905945da1`](https://github.com/karanagg166/automated-apply/commit/a7415da954e69bdf09d9792f2334385905945da1), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Source only; no account or portal update occurred.

Owner PUT `/api/v1/execution/naukri/account-binding` now shares its existing URL with GET. It requires explicit owner confirmation, current revision, the primary candidate and an existing selected browser binding. It records only the approved identity/evidence hashes and exact source/time, preserving candidate contact data. Native/model clients remain denied. Method errors advertise GET, PUT.

GET `/api/v1/execution/naukri/profile-sync` uses a read-only coherent snapshot with profile ID/version and policy/work/latest-record references; it does not take the owner lock or expose private work summary/leases. PUT `/api/v1/execution/naukri/profile-sync/policy` requires CAS and the current confirmed profile version when enabling. It refuses policy replacement during an executing save, clears stale inspect leases and preserves every existing uncertain save attempt. Disabled verify_saved_resume remains omitted for legacy rollback compatibility. These routes configure future work; profile comparison/save execution and actual reconciliation are still pending.

## Evidence matrix

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source implementation/tracing | PASS (source only) | Existing account/profile-sync service and current auth boundary traced; formatter applied |
| New native PostgreSQL tests | NOT TESTED | 5 declarations: explicit confirmation/primary/selected browser and contact preservation; suppressed ACK/concurrent CAS; read-only status/privacy under owner lock; pinned sync policy/unknown-save preservation; owner HTTP/method/closed DTO |
| Build/Clippy/all checks/suites | NOT TESTED | Owner's complete-source-first/final combined gate remains active; new tests executed0 |
| Full profile-sync worker/save/native broker | NOT TESTED | Further implementation required |
| Broader serializable owner-wait/control audit | NOT TESTED | Required before installation |
| Actual Mac/browser/provider/account/profile/online DB/install | NOT TESTED | No real operation, binding change, notice, migration or runtime replacement |
| Production schema/whole-family cutover | BLOCKED | Reviewed operator migration/grants and STOP installation required |
| Actual strict worker receipt/AUTOMATIC | BLOCKED | Last live evidence0; no activation |
| Focus/locked/restart/24h resources | NOT TESTED | Previous focus findings remain; no timing/resource comparison |

Prior validated checkpoint remains9c4ace5:193 standard +262 dedicated disposable-PG tests,455 distinct. No new source inherits those results. Estimate stays58% complete /42% remaining, an engineering estimate rather than measured acceptance.

## Reproduction, limits and continuation

After all source units are integrated, run `scripts/run_acceptance.py` under its coordinated locks with fictional native PostgreSQL. New cases are in `tests/support/execution_profile_policy_pg.rs`; no repository environment or real account belongs in the fixtures. No executed failure logs exist. Expected sanitized failures include owner_account_confirmation_required, account_binding_revision_conflict, account_binding_context_changed, current_confirmed_profile_version_required, profile_sync_revision_conflict, profile_sync_in_progress_reconcile_before_change and execution_write_ack_failed.

The controller uses the shared owner lock and exact write acknowledgements; unknown commits remain unknown without replay. Status is not an account login, profile comparison, provider save or receipt. Saved policy and unsupported fields do not become capabilities. No speed/resource/correctness comparison is claimed.

Continue full portal/profile checks, supported add-only saves and independent persistence verification, questionnaires/owner replies, search discovery/native broker/scheduler and all other services/providers/platforms in the [completion plan](../plans/completion-execution-20261116.md). Existing installed services, STOP162, lifetime4/hour1, three quarantines, current filters, focus, Gmail read/draft-only and private history remain unchanged.
