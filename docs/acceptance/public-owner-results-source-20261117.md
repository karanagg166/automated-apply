# Atomic owner public results and rankings — source checkpoint2026-11-17

Implementation [35a1a302e06cd16bda88e2110d534f7e2b5dfeca](https://github.com/karanagg166/automated-apply/commit/35a1a302e06cd16bda88e2110d534f7e2b5dfeca), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source; full owner-host/dashboard/platform acceptance remains pending.

The owner service composes original-only acquisition with local result completion. Fresh completion shares one owner-first transaction for employer/job/source observations, immutable local receipt, saved-profile rankings and terminal actual discovery run/journal. Independent acknowledgements after parent writes recheck all new rows, source window, original profile/config, finding lifetime and ranking/history inputs. A previously completed local receipt can finish its parent without refreshing job or observation times; pending reads show local_intake_complete and rankings_pending honestly. Existing acquisition-only callers remain available.

The existing native domain discovery matcher produces relevance scores using the original-pinned current saved profile. Confirmed reviewed local mailbox history omits prior applications from rankings without rewriting job decisions or inferring provider confirmation. Saved IDs are deduplicated; equal scores sort by UUID. Disabled/absent profiles produce empty rankings without profile/history lookups. History reads now bound5000 rows,256KiB each and8MiB total before client transfer; ranking job/company input bounds are1MiB per row/32MiB total. Terminal read/replay validates original local receipt, counts/IDs/ranking hashes and projects closed results without current profile/config/history reads or HTTP. No score grants application authority.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS(source only) | Shared transaction-local intake, terminal actual row/journal, native matcher, bounded history/ranking input, saved projection and formatting applied |
| New dedicated PG additions | NOT TESTED |11 declarations: original loopback/completed replay without profile table; saved-profile/history suppression; UUID ties/filtered no-results; parent ACK rollback/local retry; late journal mutation; profile-trigger rollback; history-trigger rollback; preexisting local receipt; unknown child refusal; individual/aggregate history limits; missing original receipt refusal |
| Existing deferred fixture update | NOT TESTED |One earlier intake assertion now expects truthful parent local_intake_complete with rankings still pending; no additional distinct test claimed |
| Current tests/build/check/lint/types | NOT TESTED |New executed tests:0; full source still precedes combined gates |
| Actual native provider / Mac / install | NOT TESTED |No production DB, browser, provider, application, installation or current live acceptance |
| Timing/resources | NOT TESTED |Existing connection reused/no new pool; bounds are source limits, no measured comparison |
| Owner host/dashboard/startup integration | NOT TESTED/incomplete |Service is source only; routes/UI follow |

Fixed failures include discovery_run_write_ack_failed, discovery_run_intake_receipt_missing, invalid_discovery_run_ranking, discovery_run_ranking_inventory_limit, gmail_history_limit_reached and existing profile/config/finding holds. Findings in new fixtures are fictional or explicit numeric loopback; none were executed. No private logs or candidate/mailbox data are published.

Deferred reproduction: `cargo test --locked -p automated-apply-agents --test postgres -- --ignored --test-threads=1` through the dedicated disposable harness and full `uv run --no-project python scripts/run_acceptance.py` after remaining source. Continue owner discovery routes/dashboard recovery, startup child orchestration, reviewed Apify execution and remaining runtime/platform source.

Last validated `9c4ace570535a5856184775f8045ee89eafdd05f` remains193 standard+262 dedicated native PG=455 distinct passes, not current-source evidence. Estimate stays58%/42%. STOP162, lifetime4/hourly1, three uncertain quarantines, zero strict worker receipts and focus/identity/PDF/filter rules remain unchanged. No hosted Actions, merge, cleanup, sending or installation occurred.
