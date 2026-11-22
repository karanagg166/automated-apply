# Local dashboard release validation

## November 22 public-feed release follow-up

The clean combined run `20261122T115033Z-f6870d23db26458e817c3096dee1edfc`
passed all 37 stages on `4dab75e736fa229ac8a138bac2933b204bf82941`.
The stage durations totaled 2,764.526 seconds. Coverage included 1,096 Rust
PostgreSQL cases, 3,433 backend tests with one skip, 48 backend browser cases,
the Brave extension stack, and checks on the optimized release artifacts.
The commit shortens public-feed ingestion ledger keys to fit the live column.

| Local check | Result | Evidence |
| --- | --- | --- |
| Exact immutable release | PASS | `rust-plan-lhj2z6tk` staged the accepted release using the existing config and verified rollback inventory `rust-preinstall-pqbxseh3`. |
| First cutover | Rolled back | Candidate readiness and retained data passed. The foreground app and window order matched. The screen reading changed from unknown to unlocked, so the installer restored `12666f3` and verified its health and retained state. |
| Direct-process cutover retry | PASS | The preflight required two matching, known screen observations. Runtime, readiness, control, Telegram status and dashboard returned HTTP 200. The worker was online at STOPPED. All retained checks matched. |
| Live Himalayas MCP discovery and ingest | PASS | Twenty public jobs inserted, zero duplicates and zero expired. The saved Himalayas count increased from zero to 20. All other retained checks matched, including the STOPPED application queue, three reservations, three uncertain jobs, confirmed profile and resume. |
| Live We Work Remotely MCP discovery and ingest | PASS | The official RSS feed produced 20 saved jobs, with zero duplicates and zero expired rows. Protected state and both STOPPED controls matched. The account-registration route remains a separate live gate. [Official RSS feed](https://weworkremotely.com/remote-job-rss-feed) |
| Saved-job MCP requests | PASS | All eight installed platform tools replied with their saved-only scope and dispatch disabled. At a 20-row limit, Naukri, Himalayas and We Work Remotely each returned 20 rows. The other five tools returned empty lists. The MCP exposed 26 tools. |
| Cached Apify and Gmail readiness | PASS for status | Live Apify status showed no local token, no saved inspection, no run authority and zero calls from the status read. Gmail's legacy account status reported a saved connection. Read sync is off, three workspace slots need setup, and both APIs reported sending disabled. |
| Live deterministic saved review and Telegram | PASS | The original verification wait expired. A read-only reconciliation found the same run completed with ten decisions, five tool calls, zero model calls, zero reserved tokens and one Telegram Bot API receipt. The coordinator returned to STOPPED. Protected state matched and zero job applications were dispatched. |
| Local runtime observer | Running | All 17 health samples and 16 of 17 readiness samples passed during the first two hours. In one recorded maintenance wake, health and the frontend stayed at HTTP 200 while database readiness timed out and control returned HTTP 503. The next sample was fully ready on the same process IDs. Both later locked-screen samples were ready. These observations give no precise recovery latency across sleep. |
| LaunchAgent access | Pending owner run | The updated Desktop-access launcher validated both exact staged definitions. The live services are running as local direct processes. |
| LaunchAgent adoption preflight | PASS | The installer accepted the exact live direct processes as the rollback baseline for the same release. The private-socket and loopback readiness check returned three HTTP 200 responses and confirmed both listener owners. No LaunchAgent definitions were replaced. |

The ready `4dab75e` sample recorded 5,232 KiB of Rust RSS and 3,840 KiB of
dashboard RSS. The last ready `12666f3` sample recorded 8,752 KiB and 2,848
KiB. The samples were taken at different uptimes.

## Microsoft Edge browser fixtures

Microsoft Edge Stable `158.0.4370.33` is installed on the Mac. The installer
matched the SHA-256 published by Microsoft's release API and Apple's Gatekeeper
accepted the extracted app as notarized by Microsoft. The tests used isolated
headless profiles and disposable data. [Microsoft's release endpoint documentation](https://learn.microsoft.com/en-us/mem/configmgr/core/plan-design/network/internet-endpoints)

| Check | Result | Evidence |
| --- | --- | --- |
| Original 26-program Edge browser run | 23 PASS, 3 FAIL | Three native cases loaded the Brave bundle and failed the existing browser identity check. This run took 498.914 seconds. |
| Shared fixture bundle selection at `dcea3aed1646e2f895390d4dde823325cd137dc3` | PASS | Edge now reads `dist-edge`, and Brave reads `dist`. The end-to-end build uses the corresponding output. Both builds and all 406 extension unit tests passed. |
| Affected Edge and Brave cases | 10 PASS | Five cases per browser passed, including all three original setup failures, the network guard and the complete native FastAPI/PostgreSQL stack. The 21 correlated native stack checks passed per browser. |
| macOS focus observations | Partial | Both snapshots matched in two Edge and all five Brave reruns. Three Edge reruns observed a foreground change, and one also observed a window-order change. The before-and-after checks do not identify the cause. Live focus acceptance for Edge is open. |
| Live Edge portal and submission | NOT TESTED | The live runtime still selects Brave. The Edge cases used fictional accounts, forms and employer data. |

Reproduce the Edge fixture batch from the local checkout with
`pnpm -C extension build --browser=edge --output=dist-edge` followed by
`AUTOMATED_APPLY_TEST_BROWSER=edge node extension/tests/run-browser-fixtures.mjs`
in the sanitized fixture environment. The combined 37-stage result above
belongs to the earlier installed release.

The Naukri owner launcher also verified one existing dedicated Brave tab.
Its check selects the release from the installed native definitions and
matching local acceptance evidence. The owner launcher can identify an
existing tab while leaving its window, selection and contents in place.

## Private login and production performance checks

The installed `4dab75e` release returned HTTP 200 from the Rust health and
dashboard login routes. The ten-second, 20-connection loopback load samples
had zero non-2xx responses, errors or timeouts. The health route averaged
70,069 requests per second with 1 ms p99 latency. The login route averaged
4,429 requests per second with 19 ms p99 latency. These samples cover public
loopback routes and make no claim about database-backed throughput.

Source `e01661413d969339b2e20f74e9b8ffe14eff4511` adds `/robots.txt`, improves
dark-theme headline contrast, and loads query and tooltip providers in the
authenticated workspace. Two Playwright cases and the isolated standalone
production readback passed. Anonymous workspace access still redirects to
sign-in. The crawler policy disallows all routes and keeps private pages out
of search. Both local builds sent the four expected security headers and
omitted `X-Powered-By`.

| Lighthouse result | Installed mobile | Candidate mobile | Installed desktop | Candidate desktop |
| --- | ---: | ---: | ---: | ---: |
| Performance | 91 | 81 | 100 | 100 |
| Accessibility | 96 | 100 | 96 | 100 |
| Best practices | 100 | 100 | 100 | 100 |
| SEO | 54 | 63 | 54 | 63 |
| Largest Contentful Paint | 979 ms | 795 ms | 312 ms | 289 ms |
| Cumulative Layout Shift | 0 | 0 | 0 | 0 |
| Total Blocking Time | 371 ms | 782 ms | 9.5 ms | 15.5 ms |

The mobile sample transferred 23,116 fewer script bytes in the candidate.
Mobile performance and Total Blocking Time missed their targets in both
samples. Lighthouse's crawlability item remains disabled by the app's private
indexing policy. Comparison settings used Edge headlessly with `pnpm dlx
lighthouse` against loopback production builds.

Combined run `20261122T151318Z-43524e2717764e5680344f100936ac76` recorded a
native transport fixture failure. The test could attempt to send a frame
after the rejected origin had already closed its input. The narrow test fix
at `be4fe0aef8cb06ba605e4fa174c9cc6aed8c6bf5` passed all 16 transport cases.
New release installation awaits the clean combined gate.

## Clean `--allow-telegram` release `ccdf57e` and live direct cutover (2026-11-22)

Local commits `db3d582` and `ccdf57e` wired explicit `--allow-telegram` opt-in across `rust/agent-runtime` (`prepare-native-config`, retaining `initial_cutover_requires_telegram_disabled` by default) and `rust/scripts/local_install_plan.py` (verifying `com.automated-apply.telegram.plist` is absent). Pre-commit checks passed (`cargo fmt --all -- --check`, `13/13` `host` tests, `cargo clippy --workspace --all-targets -- -D warnings`, `9/9` release Python tests, and `ruff`).

An initial acceptance run (`20261121T170221Z-5ac45bc360144758a845f8b274251eb2`) passed `35/35` stages before a host restart interrupted stage `36` (`rust-release-build`), and the next run (`20261121T220540Z-45298efbd01a4e0fa8218f1732f3b10a`) passed `36/37` stages with one transient 60s Chromium launch timeout in `backend` (`test_browser_navigation.py::test_page_review_rejects_changed_form_url_or_same_url_document[form]`; isolated `Stage` env rerun passed `12/12` in `32.54s`). The subsequent clean run `20261121T224854Z-8a683d7e5bf443449a2520fbbbd86306` on clean `ccdf57ed7b8ffd36ed1075903579cc86ed9f4192` passed **all `37 / 37` stages** in `2,230.467` seconds (`436` Rust unit tests with `1,096` PG-reserved ignored, `1,096` Rust PostgreSQL tests, `3,433` backend tests with `1` skipped, `420` frontend unit tests, `406` extension tests, `48` backend browser E2E, `21` frontend UI E2E, `31` frontend browser E2E, `1` frontend extension E2E, `2` frontend Naukri E2E, `27` Brave extension browser fixture suites (including `44` `naukri-execution` and `32` `naukri-queue` cases), and `21` correlated extension-stack checks), and staged `.local/runtime-support/releases/rust-ccdf57ed7b8ffd36ed1075903579cc86ed9f4192`.

Guarded direct-process cutover then upgraded live services from `c4329d1` to `ccdf57e` with `RUST_TELEGRAM_ENABLED="true"` under rollback `rust-preinstall-pqbxseh3` (`9` definitions, `20` references, `0` missing) and cutover plan `rust-plan-gtu8r87i` (`telegram_enabled: true`). LaunchAgent plists and native messaging host manifests remain unchanged (`rust-preinstall-m4v4yhix` preserved) because persistent `launchd` Desktop-Folder consent has not been granted yet. Three earlier cutover attempts automatically rolled back cleanly to `c4329d1` (`ppid == 1` spawner check, `25s` Telegram long-poll window vs `4s` wait, and `26`-tool MCP count including `telegram_notify_run` when Telegram is enabled); the final cutover verified all live checks:

| Gate / Live Check | Status | Observed Evidence |
| --- | --- | --- |
| Clean `ccdf57e` combined gate (`20261121T224854Z-8a683d7e5bf443449a2520fbbbd86306`) | PASS | `37 / 37` stages PASS (`clean_commit_fixture_pass: true`), `2,230.467s`; immutable release `rust-ccdf57e` staged. |
| Direct-process cutover & macOS focus | PASS | Quiesced `c4329d1`, preflight `other_visible_role_sessions: 0`, spawned `rust-ccdf57e` (`PID 75651`, `ppid=1`) ready in `12.69s` and `frontend-ccdf57e` (`PID 75728`, `ppid=1`) ready + `verify_pair` in `0.70s`; `macos_focus_snapshot.py --compare` PASS (`foreground_unchanged: true`, `window_order_unchanged: true`). |
| Retained DB state & execution fences | PASS | `check-retained.py --cutover-fingerprints --compare` exited `0` with `changed_checks: []`: `3,036` jobs, `35` packets, `6` Rust tables, `rust_mode: STOPPED`, `application_queue_policy` `STOPPED` rev `162`, `naukri_automation` `STOPPED` rev `100`, `3` quarantines, `3` reservations, `0` in-flight. |
| Live Rust Telegram bot (`@automated_apply_agent_bot`) | PASS | `GET /api/v1/rust-agent/telegram` `200` (`enabled: true`, `recipient: configured_owner_only`); read-only DB confirmed `rust_telegram_runtime` binding `73675bce7557...` and `agent_telegram_state` (`bot_id: 8842646800`, `evidence_type: live_poll`, `last_error: NULL`, `last_poll_at: 2026-11-21T23:54:31Z`). |
| Live batched Startup Explorer (`502d5e5`) | PASS | `POST /api/v1/startups/search` returned HTTP `200` on `page=1` (`28.839s`) and `page=2` (`18.232s`) across `total: 1,239` eligible companies (`12+12` disjoint `company_id`s, `evidence_basis: saved_local_records`). |
| Live Jobs, Dashboard, Auth & 26-tool MCP | PASS | All `21` authenticated owner API endpoints returned `200` (unfiltered Jobs `total: 3,036` in `8.619s`; 14-day/score ≥ 50 Jobs `total: 9` in `2.76s`), unauth `/ready` `401`, `:3000/login` `200`, unauth `:3000/api/backend/dashboard/overview` `401`; `automated-apply-tools` exposed `26` tools (`25` base + `telegram_notify_run`) with `telegram_status.enabled: true`. |
| Free public discovery runs (`c4329d1` before cutover) | PARTIAL / PASS | Completed retained `hacker_news` run `24c01f23-b3ef-4ed8-82bd-214a3fbc48f1` (`POST .../complete` `200` in `79.19s`, `18` inserted, `0` extra provider calls -> `9` fresh 14d/score ≥ 50 matches scoring `50–95`); `remotive` returned `429 public_job_source_rate_limited`; `arbeitnow` (`7aeb6a92-5184-40db-be6f-f52a0aca39b0`) returned `503 execution_database_error` (`GET` retained `status: running`, left un-replayed). |
| Direct process observer (`PID 75892`) | IN PROGRESS | `observe-direct-release.py` writing `0600` JSONL (`observer-ccdf57e-direct-20261122.private.jsonl`); sample #1 (`13.3 MiB` Rust, `3.2 MiB` Frontend) returned HTTP `200` on `/health`, `/ready`, `/control`, `/telegram` (`enabled: true`), and `:3000/login`. |
| LaunchAgent cutover (`com.automated-apply.{rust,frontend}`) | BLOCKED (OS) | Awaits interactive owner approval of macOS Desktop-Folder consent via `check-catalog-desktop-access.command`. |
| Naukri pin replacement & 4th supervised submission | BLOCKED (Owner/Auth) | Awaits visible owner Naukri sign-in in `brave-automation` (email recovery `HTTP 403`, Google blocked, mobile OTP declined) before `replace-fixed-brave-profile` and first strict worker receipt. |

## Earlier `c4329d1` baseline validation

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

The installed `c4329d1` owner MCP also returned all 25 catalog entries and
answered 15 of 15 live local saved-data reads. These covered all eight
saved-job adapters, runtime and browser status, application history,
Telegram and Apify status, and both discovery-source inventories.
Naukri returned two saved entries in the bounded read. The other seven
adapter reads returned empty lists. The tools for external submissions,
email sending, Telegram delivery, paid Apify actions and discovery
execution were absent from this installation's catalog.

The narrower public-feed probes used the installed MCP with a limit of
two jobs. Himalayas returned two attributed jobs. We Work Remotely
returned a retained attempt error. The feed request was left for
reconciliation. Both probes used only feed discovery.

## Desktop access before cutover

The local access launcher in
`.local/runtime-recovery-20261120.RyE1Do/check-catalog-desktop-access.command`
prepares four one-shot LaunchAgents for the current and staged releases.
They use the exact installed or staged working directories and reviewed
configuration. The two Rust commands run read-only PostgreSQL checks for
STOPPED controls and the connection budget. The two dashboard commands
validate local configuration and the built bundle, then exit. The live
application LaunchAgents and their files stay untouched during the probe.

| Check | Result | Evidence |
| --- | --- | --- |
| Release, rollback, probe definitions | PASS | The launcher’s `--check` mode verified the exact staged artifact inventory, restored rollback inventory, configuration stamps and four LaunchAgent plists. The existing frontend configuration path resolves through the recorded Application Support alias to its private file. |
| One-shot launchd path | PASS | A system no-op ran once, exited zero and was unloaded under a separate label. macOS foreground and window order matched before and after. |
| Four exact commands launched directly | PASS | Current Rust and dashboard checks took 4.687 and 0.295 seconds. Staged Rust and dashboard checks took 4.882 and 0.141 seconds. Both read-only database checks returned STOPPED revisions 162 and 100 and a connection limit of five. |
| Exact commands under launchd | PENDING | The owner can run the launcher while present to respond to the macOS Desktop Folder prompt. The result needs a separate check before service activation. |

A successful probe establishes that the one-shot commands can run through
launchd. Persistent activation still needs its own readiness, focus, startup
catalog, policy, and retained application-state checks. The current dashboard
continues to serve from the two locally launched `c4329d1` processes.

The local installer now accepts the verified pair of direct baseline process
IDs during the reviewed handoff. Its no-activation check passed against the
two running processes, the exact staged release, and rollback
`rust-preinstall-m4v4yhix`. Both services own their exact loopback listeners.
An OrbStack wildcard also occupies port 3000. Readiness requires the exact
loopback owner to be the expected process, and the OrbStack process stays
outside the handoff. Six focused guard checks covered ambiguous or absent
loopback ownership, a changed process identity, and the required access
result. Actual activation and restoration on this path remain pending.

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
