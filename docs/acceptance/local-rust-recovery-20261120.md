# Local Rust update and recovery, 2026-11-20

Branch `feat/rust-agent-runtime` now runs Gemini's `d7d04845d290a205aeffcfebcbc2b0a517b072d0` locally. This follows [Gemini's initial Rust cutover](local-rust-cutover-20261120.md). The approved database migration stayed in place. The Rust coordinator, application queue and legacy preparation stayed STOPPED. The installation left GitHub untouched.

## Recovery and installation

- The previous release `74a7f25df0ab63c16ee0bc9fd6c8675afcd685f6` returned HTTP 200 from `/health` while database-backed requests exceeded six seconds and the worker heartbeat went stale. A fresh read-only database preflight succeeded. A Rust-only LaunchAgent restart restored `/ready` to HTTP 200 in about 0.8 seconds and restored the worker heartbeat. The macOS foreground process and visible window ordering stayed the same. This ended the previous release's stability observation with a recorded failure.
- The new release bounds liveness probes on idle database sessions and bounds worker heartbeat and wait steps. Its seven new reads cover saved job search, dashboard connections, onboarding, presets, integrations, startup integration status and browser assets policy. The exact clean commit passed all 36 combined local fixture stages in 2,812.558 seconds. The checkout SHA and clean status matched at the beginning and end.
- Activation used `rust-plan-pl_ecsw6` and rollback snapshot `rust-preinstall-d1s1mcdl`. The snapshot verified nine installed definitions and 20 references with zero missing. The first activation stopped the dashboard and the installer misread launchd's asynchronous exit as a failure. The old dashboard was restarted and verified from its original definition. The retry waited for launchd to finish unloading the services. It verified zero other runtime-role database sessions before starting the new family.
- The retry activated only the Rust and dashboard services and redirected both existing Brave native-host registrations to the new immutable release while preserving the extension ID. The macOS foreground process and visible window ordering matched before and after activation. Browser tabs were outside the desktop snapshot's scope. The dedicated Brave target inventory read made no browser commands.
- Before and after read-only database snapshots agreed on 3,018 jobs, 35 application packets, six Rust tables, zero leases in flight, three quarantined unknown outcomes and three reserved Naukri Apply admissions. Saved queue policy and quarantine and reservation digests also matched. Queue revision `162` retained supervised cap 4, hourly cap 1, age 14 days, applicant limit 1,000, score 50, and at least one verified job skill. Independent preflight observed role limit 5 and two existing role sessions with the previous family active.

## Evidence

| Check | Result | Scope |
| --- | --- | --- |
| Clean combined run `20261120T154756Z-1d1a335a7ed94992abaf1bd1da2f61b0` | PASS | 435 Rust workspace tests, 1,084 Rust disposable PostgreSQL tests, 3,433 backend tests and one skip, 413 frontend unit tests, 406 extension unit tests. Frontend browser suites passed 21, 31, 1 and 2 cases. All 26 extension browser fixtures and 48 backend browser cases passed. |
| Installed runtime and dashboard | PASS | Both LaunchAgents point to `d7d0484`. API health, authenticated readiness, STOPPED control with live heartbeat, queue policy, dashboard login and all seven new reads passed. Unauthenticated readiness and dashboard proxy access returned 401. |
| Timing and resources | OBSERVED | Direct `/ready` took 0.862 s during installation validation. `jobs/search?limit=5` took 7.896 s. First observer sample saw 5,088 KiB Rust RSS and 4,192 KiB dashboard RSS, compared with 8,096 KiB and 2,304 KiB from a single post-restart sample on the previous release. These are point-in-time process observations. |
| Project MCP, 25 tools | PASS for read probes | Project configuration initialized over stdio. Runtime, browser readiness, Naukri saved jobs, Instahyre saved jobs, Telegram status and Apify status answered. Telegram delivery is disabled and Apify live actor execution was unverified. The existing Apify MCP registration remains enabled. |
| Dedicated Brave and Naukri receipt | BLOCKED | The owned profile exposed one extension worker and zero page targets. Live account and resume validation, the fourth supervised Apply and the first strict worker receipt are pending. No new application was admitted. |
| Remaining dashboard route coverage | FAIL | The installed server returned 404 for discovery automation status/history/matches, candidate-context configuration, submission review, legacy agent status/campaigns and the saved-packet browser assistant read. The native connection report and execution queue returned 200 in the same probe. |
| 24-hour runtime observation | IN PROGRESS | Private sampling began at `2026-11-20T16:39:45Z`. The first unlocked sample had HTTP 200 from health, readiness, control and dashboard. Locked and elapsed 24-hour evidence is pending. |
| Additional live portals and browsers | NOT TESTED | Instahyre was checked through saved-data MCP only. Edge was packaged. The other live portal and browser workflows still require their own acceptance. |

Gemini used a second installation plan and a restart check on the same release. Both installed LaunchAgent files matched both plans byte for byte. The observer recorded the changed PIDs and healthy samples after the restarts. The follow-up also found that the local Gmail mailbox needs reauthorization. [Gemini's verification](local-rust-cutover-20261120.md#upgrade-update--d7d04845d290a205aeffcfebcbc2b0a517b072d0-2026-11-20-2214-ist)

An additional owner-only preflight read returned an approved saved Naukri account binding and a confirmed local profile. The API still marks live profile sync unaccepted. The native discovery schedule returned HTTP 200 with zero sources enabled. No preparation or application was started.

## Discover page follow-up

The next source revision connects the Discover page to the existing Rust public feed discovery and schedule controls. The runtime selection uses server-side socket configuration. The Python compatibility deployment retains its original automation panel. Both Rust entry points use the same authenticated workflow HTTP client. Twelve focused frontend tests, the production build, TypeScript and the private-socket launch fixture passed. The latter verified the rendered Discover page and that schedule requests use the configured Unix socket. This follow-up awaits the next combined source gate and local installation. The currently installed launch definitions still point to `d7d0484`.

The project continues with the remaining native dashboard coverage, the dedicated Brave sign-in and the first strict Naukri worker receipt. Other portal submissions follow their own acceptance after Naukri. The account-independent continuity backup retains nine available transcripts out of 107 indexed. No alternate file or snapshot matched the other 98 threads in the inspected local Codex transcript roots and private backup.

```sh
uv run --no-project python scripts/run_acceptance.py --run --keep-going
uv run --no-project python -m rust.scripts.local_release stage --acceptance-run 20261120T154756Z-1d1a335a7ed94992abaf1bd1da2f61b0
uv run --no-project python -m rust.scripts.local_rollback verify rust-preinstall-d1s1mcdl
uv run --no-project python scripts/project_continuity.py verify
codex mcp list
```

Live checks, observer output and preserved rollback definitions are in ignored owner-only storage. The current release bundle is an exact match for the clean combined run.
