# Local dashboard release validation

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
