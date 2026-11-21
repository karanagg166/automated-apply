# Local dashboard release validation

AGY completed the clean local release gate on `c4329d178c513ba1e24da975aba1e02353c043c9`
and installed that release through plan `rust-plan-r6kp4_kd` on the owner's Mac.
Run `20261121T091756Z-270fdc49c59e4b1d99e07caea2114e8e` passed all 37
stages in 2,124.961 seconds. The suites included 435 Rust workspace tests,
1,091 Rust PostgreSQL tests, 3,433 Python tests with one skipped, 420 frontend
tests, 406 extension tests, and 48 backend browser cases. AGY observed preserved
foreground and window order during activation and restart.

| Installed release check | Result | Evidence |
| --- | --- | --- |
| Exact artifact and rollback | PASS | The installed artifact matched the clean gate's checksums. Rollback `rust-preinstall-buvft9x6` retained nine definitions and twenty references, with zero missing references. |
| Default Jobs page | PASS | HTTP 200 in 3.918 seconds, with 20 saved jobs on the first page and 3,017 eligible records from 3,018 saved jobs. The earlier release exceeded 25 seconds on the same request. |
| Dashboard routes and local auth | PASS | All ten owner dashboard reads returned HTTP 200. The three restored Automation reads took 2.162, 1.222 and 0.989 seconds. Unauthenticated readiness and dashboard proxy requests returned HTTP 401. |
| Retained runtime state | PASS | All 19 retained fields matched the previous snapshot, including the profile, resume references and submission evidence fingerprints. Three uncertain jobs and three reservations remain. The queue is STOPPED at revision 162. |
| Installed MCP | PASS | The catalog exposed 25 tools. Runtime status, browser readiness, both saved-job tools, Telegram status and Apify status answered. Telegram is disabled. Apify has no live verification in this read. |
| Runtime observation | IN PROGRESS | A read-only 24-hour observation started at 10:52 UTC. The initial readiness sample returned four HTTP 200 responses with both services loaded. |
| Naukri and updated Brave extension | BLOCKED | The selected Brave profile had an extension worker and zero page targets. The new native host is registered under the same extension ID. An owner launcher passed its release, loopback, STOP and no-existing-tabs checks. A visible sign-in is required. |

The owner can open the dedicated Naukri profile from
`.local/browser-profiles/open-brave-naukri-automation.command`. This launcher
uses the installed extension and retires only the verified windowless instance.
The owner's ordinary sign-in enables the next account and resume readback.

## Startup catalog

AGY identified the default startup search's 500-company limit. A read-only
production inventory counted 1,222 companies and 3,016 associated jobs. The
follow-up code reads saved company, job, observation and contact data in
bounded batches in one database snapshot. It retains the existing filters,
ranking and complete result count before pagination. A disposable PostgreSQL
fixture returned two distinct pages and a total of 1,222 companies, preserved
source narrowing, and rejected a catalog above the new 5,000-company bound.
All 73 startup PostgreSQL cases passed.

The exact clean `502d5e589a0dc84321c095173b7034479dbffafe` run
`20261121T110324Z-e57eaa833c2347d886401e7c4f213e8e` passed all 37 stages
in 2,678.151 seconds, including 1,092 Rust PostgreSQL tests. The candidate
is staged under `rust-plan-e8gqumqz`. Native and dashboard startup timed out
on two cutovers. The second attempt captured the Rust process waiting in the
system loader and a matching macOS Desktop-folder consent request for its
executable. A restart of the candidate process also stayed unready. The
rollback restored nine exact definitions and twenty references from
`rust-preinstall-m4v4yhix`. The restored LaunchAgents also timed out on the
second attempt. The previous release `c4329d1` then recovered through its
ordinary local service commands under a temporary supervisor. Runtime health,
readiness, STOP control, and dashboard login returned HTTP 200. All 19
retained state comparisons matched.

A local probe linked against the optimized `502d5e5` library and called
the startup search handler with its default dashboard filters. It used one
live PostgreSQL connection with read-only transactions enforced. The probe
returned two distinct 12-company pages, both reporting 1,221 eligible
companies. It measured 16.015 seconds for page one and 10.968 seconds for
page two. The probe used the query handler directly. Persistent LaunchAgent
startup and HTTP verification through the installed dashboard remain pending.

Observation resumed on the two verified `c4329d1` processes under their
temporary local launch. The observer checks each process's release path and
start time and stops if either process changes. Its first sample returned
HTTP 200 for health, readiness, control and dashboard login. The full
24-hour observation is in progress.

## Earlier release evidence

The clean checkout at `e84bf06d4514dfb1ce0fdcaf9154420482051370` passed
all 37 local fixture stages in 2,833.159 seconds. The run retained the
same clean Git SHA from start to finish. The exact run ID is
`20261120T193224Z-61feab7d407c4287812c544502b34ba6`.

| Checks | Result | Evidence |
| --- | --- | --- |
| Combined fixture and release build at `e84bf06` | PASS | 37 of 37 stages, including the optimized build and artifact inventory. |
| Unit and integration suites | PASS | 435 Rust workspace tests, 1,090 Rust PostgreSQL tests, 3,433 Python tests with one skipped, 420 frontend tests, and 406 extension tests. |
| Browser fixtures | PASS | 21 frontend UI journeys, 31 frontend browser journeys, one frontend extension journey, two frontend Naukri journeys, 48 backend browser cases, and the isolated Brave extension suites. The 44 Naukri execution cases and 32 queue cases made zero live Naukri requests. |
| Installed baseline `d7d0484` | OBSERVED | 70 observations through `2026-11-20T20:18:00Z` returned HTTP 200 from all four readiness endpoints. Screen state was unlocked in 61, locked in five, and unknown in four. The 24-hour observation is still in progress. |
| Normal Jobs page on `d7d0484` | FAIL | The exact default Jobs request exceeded a 25-second read timeout with 3,018 saved jobs. The existing search reads full descriptions and discovery metadata before applying pagination. |
| Page projection comparison | PASS | A read-only SQL comparison returned identical filter inputs for 3,018 rows and identical details for all 20 first-page rows. Estimated JSON text transfer was 21,432,549 bytes for the previous projection and 3,994,312 bytes for the revised projection and first-page details combined. |
| Follow-up HTTP at `cb7bd4f868b576067fbdcf2dcea40cd9e7acd5f5` | PASS | The disposable PostgreSQL HTTP fixture verified pagination, display metadata and descriptions, source observations, profile keyword exclusions and ranked fit. Rust formatting and Git diff checks passed. |
| Follow-up combined acceptance at `df3ba53` | FAIL | Run `20261120T202325Z-f0b409557a734e118b5626e45d033ef8` finished with 36 of 37 stages passing in 3,111.874 seconds. The optimized build and artifact inventory passed. One Brave fixture timed out while waiting for the inactive Naukri settings tab to initialize. The installer declined this run. |
| Retained Naukri form fixture correction | PASS | The corrected fixture passed from the tracked source in 34.650 seconds. It verified the inactive alarm, same-tab reload, STOP heartbeat, and both cleanup decisions. It made zero live Naukri requests. |
| Combined gate at `e53517e` | PASS | All 37 stages passed in 2,380.001 seconds in exact run `20261120T211643Z-884441da39424c8fb0195e2352080ab8`. |
| Reviewed installation and live Jobs timing | FAIL | The first install detected a focus change and restored `d7d0484`. The retry preserved foreground, window order, and screen state through activation, then restored `d7d0484` after the legacy Automation status route failed. Plan `rust-plan-eei04q2e` and comparison against rollback `rust-preinstall-bed0eimp` verified the old release. The live Jobs timing is pending. |
| Retained Automation dashboard reads | PASS in fixtures | Live PostgreSQL contains the retained tables with zero schedules, executions, or matches. Two disposable PostgreSQL HTTP fixtures passed. They checked owner authentication, default empty state, execution history filtering, match ordering and stale profile rejection. A missing schedule remains absent during reads. Live verification awaits the revised release. |
| Combined gate at `95c724c` | FAIL | Run `20261120T222143Z-58e1f028774243eb9e99765ae3548cbc` finished with 36 of 37 stages passing in 3,800.167 seconds, including the optimized build and artifact inventory. The 1,091 Rust PostgreSQL cases and all 48 backend browser cases passed. One of 420 frontend tests timed out while the Gmail account list still showed its loading state. The installer declined this run. |
| Gmail account-list fixture correction | PASS in isolation | Nine cases passed in the isolated fixture with React Query notifications scheduled as microtasks. The test restores React Query's default scheduler after each case. The corrected source awaits a clean combined run. |
| Live platform acceptance | PENDING | Brave remains windowless in the dedicated automation profile. The Naukri sign-in, exact account and resume checks, fourth supervised admission, and first strict submission receipt remain pending. |

The local rollback inventory `rust-preinstall-bed0eimp` matched nine
installed definitions and twenty retained references. The local installer
checks the exact candidate, dashboard reads, unchanged browser extension
identity, the normal Jobs page and macOS focus. Its readiness and error
checks passed in 11 isolated cases. Installation awaits the revised
release.

An independent read of the installed baseline matched prior queue
and application records, including 3,018 jobs, 35 packets, three
quarantined outcomes, and three reserved admissions. All execution
controls reported STOPPED.

The retained-form fixture now polls readiness and the resolved alarm count
from the Playwright driver. It still uses the real Brave alarm and reloads
the same inactive tab. The earlier asynchronous poll could resolve on its
promise before confirming a second run. The fixture continues to check
STOP and preserves pending questionnaires.

```sh
uv run --no-project --python .venv/bin/python python scripts/run_acceptance.py --run --keep-going
uv run --no-project --python .venv/bin/python python rust/scripts/run_postgres_tests.py --filter dashboard_legacy_and_jobs_search
uv run --no-project python -m rust.scripts.local_rollback verify rust-preinstall-bed0eimp --compare-installed
```
