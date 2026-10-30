# Approved diagnostic preflight stopped: eager checkout regression corrected

**Cutover STOPPED before installation under the owner's condition 2.** Database capacity preflight succeeded, but a real disposable PostgreSQL regression proved the approved instrumentation made SQL-free native rejection wait behind unrelated database work. Production remains installed at **`79ce5f6b514279e6d9022d85b659ad77fb31bd89`**. No genuine browser cycle was attempted on the candidate, and no new live reliability PASS is claimed.

Branch `fix/live-prepare-discovery-20261030`, base `main`, [PR #48](https://github.com/karanagg166/automated-apply/pull/48). Approved diagnostic SHA was `d504d26e889859b2b39111bb5deedce80c4bd589`; it was **not installed**. Corrected candidate requiring new review is [074fb828e6da04a093024c0ac4227b0d4ebca712](https://github.com/karanagg166/automated-apply/commit/074fb828e6da04a093024c0ac4227b0d4ebca712). This report's later commit changes only public evidence. [Sanitized measurements](status-contention-preflight-metrics-20261030.json). [Prior candidate report and installation/rollback proposal](status-contention-fix-20261030.md).

## Owner authorization and actual Mac capacity preflight

The owner approved only exact SHA `d504d26…` for bounded diagnostics/read-only acceptance, with a mandatory stop if eager checkout added contention. No unattended operation, merge, filling, submission, Gmail sending, new browser permission or locked-screen test was approved. New runtime code remains subject to new exact-SHA approval.

Before any direct DB connection, HTTP preflight verified the existing acceptance task was PAUSED, had no field authorization and no queued/leased/executing Chrome command. Only the known Telegram LaunchAgent was gracefully booted out at **2026-10-30 13:00:44.742 UTC**. Its original process exit was verified. The existing API, execution worker and frontend were left running. No unidentified session or process was killed. With Telegram quiescent, one explicitly named temporary capacity-audit connection queried `pg_stat_activity`/`pg_roles` in a read-only transaction and saved a narrow private state snapshot.

| Session observed after quiescing Telegram | State | Wait evidence |
| --- | --- | --- |
| `automated-apply:execution` | idle | Client / ClientRead |
| `automated-apply:api` | idle | Client / ClientRead |
| `automated-apply:capacity-audit` | active | none |
| **Total / role connection limit** | **3 / 5** | All three identified |

The audit connection was closed **before** Telegram was restored, with bootstrap success at **13:00:59.787 UTC**. No connection limit was raised. No duplicate runtime engine, additional observer or local acceptance helper using production SQL was started. This establishes safe capacity for this preflight; it does not explain the earlier role-exhaustion event retrospectively. The separate readiness session was not present in this snapshot. The intended full budget remains API business 1 + API readiness 1 + execution 1 + Telegram 1, with one operator slot. That full four-session occupancy was not freshly inventoried after restoration; do not label the design sum as a measurement.

Current inventory had no unidentified same-role sessions. Session IDs, addresses/ports, query text and business values stay private. The earlier `role_connection_limit` failure remains in the historical report and is not erased by this successful snapshot.

## Proven pre-install instrumentation regression

A new test calls the **actual native route handler** with an extension identity that must be rejected with 403 before dispatch or SQL. The local disposable PostgreSQL engine has one connection and zero overflow. A separate transaction holds that slot for a controlled 150ms observation window. This tests native identity validation after the already-established owner boundary; it is not a new production browser request or an employer action.

Against the unchanged approved eager dependency:

- The request did **not** finish before the holder released its connection.
- `pool_checkout_wait` measured **150.629ms**.
- An unnecessary checkout/check-in occupied the connection for **0.468ms**, despite zero SQL in the rejected request.
- The new regression failed with `native authorization rejection waited for an unrelated database transaction` (**1 failed, 8 deselected**). This genuine failure triggered the stop; it is retained privately and in sanitized metrics.

Against the corrected dependency, the same route returned 403 in **1.311ms**, while the holder remained active throughout the 150ms observation. The rejected request recorded session creation only: **zero acquisition, zero SQL and zero connection occupancy**. Final disposable PostgreSQL suite: **9 passed in 3.24s**.

A second explicit fixture measures the eager occupancy effect rather than inferring it from HTTP latency. It compares the approved dependency loaded from its exact Git source against the correction, using the same one-slot isolated SQLite pool, the same 50ms pre-SQL asynchronous delay, and a concurrent status-style `SELECT 1`:

| Measurement | Approved eager | Corrected lazy |
| --- | ---: | ---: |
| Connections occupied before any SQL intent | 1 | 0 |
| Primary connection occupancy | **52.742ms** | **0.551ms** |
| Peer connection acquisition | **52.696ms** | **0.543ms** |
| Peer read finishes during pre-SQL delay | no | yes |
| Primary SQL execution | 0.248ms | 0.107ms |
| Primary connection acquisition | 0.951ms | 0.085ms |

Both comparison cases passed in **0.31s**. These are controlled fixture observations of eager instrumentation overhead, not an assertion that a 50ms pre-SQL delay exists in the production native path, nor a general performance estimate. They separate observed queue/acquisition delay, SQL execution and occupancy. No owner row lock is acquired in these two cases; row-lock waits remain separately instrumented in genuine business paths. The earlier historical 16–20s native bottleneck is **still unproven** until a corrected candidate is approved and installed.

## Root correction and limits

`get_db_session` again creates a session and yields it without obtaining a database connection. The existing engine now uses `TimedAsyncAdaptedQueuePool`, a transparent subclass of the same SQLAlchemy async queue pool. Its `_do_get` hook surrounds only **natural connection demand**, returning the same record and propagating the same errors/cancellation. No new engine or slot is created; pool sizes, overflow, connect/command/pool deadlines, pre-ping and recycling stay unchanged. Implicit flush-only writes are measured too. SQL-free session commit/rollback and native rejection do not demand a slot.

The corrected stage is named **`pool_acquisition`**. It covers queue wait plus new connection creation when needed. It **excludes pre-ping**, which SQLAlchemy performs after this hook. It is not labeled pure queue time. Existing checkout/check-in events measure occupancy; SQL execution/failure and owner-lock spans remain separate; parent and child spans overlap and must not be summed. The old eager `pool_checkout_wait` stage appears only in the retained before trace and historical documentation.

`_do_get` is an internal SQLAlchemy hook, a concrete compatibility risk to recheck on dependency upgrades. Both current development and installed release libraries are **SQLAlchemy 2.1.4**, and both have the same `(self) -> ConnectionPoolEntry` hook signature. Tests cover natural checkout, implicit flush, multiple statements reusing one connection, no-SQL commit, cancelled waiter accounting, connection recovery and PostgreSQL pool/fault safety. No installed dependency was changed.

The correction inherits prior task revision, focus no-op, exact profile/tab/window/session, Stop/Pause, packet freshness, lease expiry, receipt and unknown-outcome fences. It adds no retries and cannot reauthorize an invalidated plan. Long business transactions are not split by this correction; installed spans are still needed to identify and correct their dominant cost.

## Final actual installed state and HTTP checks

Final HTTP-only checks at approximately **13:06:46 UTC**, after Telegram restoration:

| Endpoint | HTTP | Seconds |
| --- | ---: | ---: |
| health | 200 | 0.0261 |
| readiness | 200 | 4.0490 |
| profile status | 200 | 1.4494 |
| acceptance task | 200 | 0.9682 |

The existing task remains PAUSED with **zero authorization and zero active commands**. Selected binding is unchanged. All four existing LaunchAgents are loaded and reference `79ce5f6…`. Installed tracked source is clean at that exact SHA. Four service definitions, native wrapper and frontend launcher match the approved `79ce5f6…` install plans; two private env files and native-host manifest match their preserved hashes. These checks do not expose or alter credential values.

An initial checksum comparison used the **backup taken before the previous 79ce5f6 installation**, so service/native/frontend paths naturally differed. It was corrected to compare against that installation's approved plans; all nine checks then matched. No files were overwritten to make a checksum pass. The original diagnostic comparison is retained privately. No Chrome preferences, binding, extension identity, permissions, release directory or rollback file was changed.

There was no cutover and therefore **no rollback was necessary or attempted**. Only the known Telegram process was quiesced/restored for capacity inventory. Historical releases and execution history remain intact. These four HTTP samples establish final preflight state only: they are not concurrent workload acceptance, a restart acceptance rerun or a zero-timeout reliability claim.

## PASS / FAIL / BLOCKED / NOT TESTED matrix

| Item | Result | Evidence / limitation |
| --- | --- | --- |
| Actual capacity preflight | PASS for snapshot | Identified 3 sessions including audit / role limit 5; audit closed before Telegram restored |
| Known service restoration / old installation preserved | PASS | All four loaded, same installed SHA, selected binding unchanged, nine static checks match |
| Approved eager instrumentation under contention | **FAIL** | SQL-free native rejection queued 150.629ms; controlled additional occupancy demonstrated |
| Stop before unsafe candidate installation | PASS | No cutover or candidate runtime started |
| Corrected native rejection under real local PostgreSQL contention | PASS, fixture | 403 in 1.311ms while holder remains occupied |
| Corrected backend regressions | PASS | **394 passed in 40.47s** |
| Corrected disposable PostgreSQL regressions | PASS | **9 passed in 3.24s**, loopback-only isolated fault-injection databases |
| Explicit checkout comparison | PASS, fixture | **2 passed in 0.31s**, reproduction below |
| Ruff E9/F/I / diff checks | PASS | Five changed Python files |
| Frontend/extension | Prior evidence only | No JS changed here; prior 284 frontend/134 extension passes not rerun or relabeled |
| Candidate installed live bottleneck / overhead | NOT TESTED | New corrected SHA needs review |
| Three consecutive genuine Open→Prepare cycles | BLOCKED | Installation stopped under owner condition 2; zero new attempts |
| Concurrent original-12s status / readiness monitoring | NOT TESTED on candidate | No candidate installed; no observer started |
| Profile 8 tab lifecycle provenance | NOT TESTED on candidate | No candidate extension reloaded; historical tab changes remain unattributed |
| Genuine supported employer form | NOT TESTED | No DOM/fill claim; prior zero-field results remain no-verified-form only |
| Locked-screen acceptance | NOT TESTED | Owner-deferred |
| Filling / submission / Gmail sending | NOT TESTED / not authorized | No such action performed |
| Candidate rollback | NOT REQUIRED | Candidate never installed; old installation remained in place |

## Reproduction and remaining installation plan

```sh
# Explicitly set PROFILE_TEST_DATABASE_URL to a disposable localhost candidate_profile_test.
.venv/bin/python -m pytest backend/tests/test_reliability_postgres.py -q -s
.venv/bin/python -m pytest backend/tests/benchmark_checkout_overhead.py -q -s
.venv/bin/python -m pytest backend/tests/test_request_timing.py backend/tests/test_browser_forms.py backend/tests/test_reliability.py backend/tests/test_chrome_profiles.py backend/tests/test_execution_naukri.py backend/tests/test_naukri_recurring.py backend/tests/test_naukri_alert_email.py backend/tests/test_telegram_pairing.py backend/tests/test_agent_execution.py backend/tests/test_live_prepare_recovery.py backend/tests/test_local_gmail_discovery.py backend/tests/test_operational_health.py backend/tests/test_config.py backend/tests/test_extension_tasks.py backend/tests/test_packet_telegram_questions.py backend/tests/test_database_safety.py backend/tests/test_phase1_installation.py -q
```

Raw receipts and test output stay owner-only under `status-contention-install-20261030`; sanitized inventory/spans/counts are published alongside this report. An intermediate focused run passed 124 tests, but is not summed into the final 394 count. The final 9 PostgreSQL cases include the new rejection regression.

The next installation proposal replaces **only the proposed candidate SHA** in the [published seven-step installation/rollback plan](status-contention-fix-20261030.md#exact-installation--rollback-proposal--requires-owner-approval) with **`074fb828e6da04a093024c0ac4227b0d4ebca712`**. The approval for `d504d26…` does not authorize this replacement. Review the corrected SHA before any cutover. Revalidate capacity/task/commands and preserved configuration at the start of a newly approved window; current inventory is a dated snapshot, not a permanent reservation. Preserve `79ce5f6…` as the exact rollback release. Keep the same 12s status deadline, single HTTP-only observer, three uninterrupted genuine read-only attempts, bounded tab audit and stop-on-capacity-error/unknown-outcome rules. Restore only the approved service/native/frontend/extension references after reconciling any original command outcomes; never restore stale authorizations or discard receipts/history. No merge, unattended expansion, new browser permissions, filling/sending/submission, locked-screen test or cleanup is included.

Once corrected installed spans identify the historical native cost, fix that measured root cause and publish a new exact SHA for review when runtime code changes. This pre-install correction addresses a measured diagnostic regression; it does **not** claim to have solved the original native transaction latency.

Modified implementation files in this milestone:

- `backend/app/core/timing.py`
- `backend/app/db/session.py`
- `backend/tests/test_reliability_postgres.py`
- `backend/tests/test_request_timing.py`
- `backend/tests/benchmark_checkout_overhead.py`

Public evidence changes: this report, its sanitized metrics JSON, and the current-evidence link in the preceding report. No production source, credentials or browser data were written. Hosted Actions were not dispatched or rerun; PR #48 remains unmerged.
