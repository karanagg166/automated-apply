# Local Rust Runtime Migration, Whole-Family Cutover, and Live Operational Verification — 2026-11-20

## Scope and Branch Identity

- **Repository**: `/Users/karanagg/Desktop/Projects/automated-apply`
- **Branch**: `feat/rust-agent-runtime` (local only — no GitHub push, PR update, remote report publication, hosted Actions, or merge per owner direction)
- **Installed & verified implementation commit**: `74a7f25df0ab63c16ee0bc9fd6c8675afcd685f6` (`fix(runtime): support legacy live records, batch packet reads, and serve overview`)
- **Preceding local milestone commits in this cutover sequence**:
  - `e6ce7d413a97786f7210251065012be48cc9d7f1` (`fix(runtime): grant temporary schema create for non-superuser Rust migration`)
  - `796ca0b415d7a5797f5df2290b5a44db463e3aff` (`fix(runtime): store LaunchAgent logs under Library/Logs outside Desktop TCC`)
- **Clean 36-stage combined acceptance run**: `20261119T212316Z-0a0e1fa3e5dc4e6682a994f9f0731ef9` (`36/36` stages `PASS` in `2530.912s`, `clean_commit_fixture_pass: true`, clean working tree before and after)
- **Staged & installed immutable release**: `.local/runtime-support/releases/rust-74a7f25df0ab63c16ee0bc9fd6c8675afcd685f6`
- **Active installation plan**: `rust-plan-11ybx67o` (`logs_directory: /Users/karanagg/Library/Logs/Automated Apply`)
- **Verified rollback archives**:
  - `rust-preinstall-248445k7` (pre-cutover Python `api-8e985c9` + `execution` + `frontend` stack: `9` definitions saved, `16` references checked, `0` missing, live rollback drill proven)
  - `rust-preinstall-jrnecug8` (pre-upgrade `rust-e6ce7d4` stack: `9` definitions saved, `20` references checked, `0` missing, live rollback drill proven)

---

## Summary of Fixes Delivered During Live Cutover

1. **Hosted Supabase non-superuser DDL ownership transfer (`e6ce7d4`)**:
   - Hosted Supabase runs migrations as a non-superuser `postgres` database owner, and `001_phase1_public.sql` revoked `CREATE ON SCHEMA public` from `job_agent_owner`. `ALTER TABLE public.rust_agent_runs OWNER TO job_agent_owner` therefore failed with PostgreSQL `42501`.
   - Updated `rust/agent-runtime/sql/005_backend_access.sql` to temporarily `GRANT CREATE ON SCHEMA public TO job_agent_owner;` immediately before the six `ALTER TABLE ... OWNER TO job_agent_owner` statements and `REVOKE CREATE ON SCHEMA public FROM job_agent_owner;` immediately after in the same atomic transaction.
   - Regenerated `supabase/runtime/001_rust_agent_runtime.review.sql` (raw file SHA-256 `9ddab3b3ff3db54d215f240e9656096356e058f00a48f08160397bc4dc82c969`, content digest `0ead8c2e40feb0248c8448c3fff38fc44e1680de869175e3dad08e17990b045d`) and `backend/app/operations/rust_schema_manifest.json` (catalog SHA-256 unchanged at `ea94a97e49331041610d20821c2a479abeea7d58f10717e317606f73d2f2b46a`, preserving Python rollback recognizer compatibility).
   - Hardened `rust/scripts/verify_live_migration.py` to execute the migration rehearsal as a non-superuser `postgres` database owner and assert `NOT has_schema_privilege('job_agent_owner', 'public', 'CREATE')`.
2. **macOS LaunchAgent Desktop TCC log path (`796ca0b`)**:
   - `xpcproxy` refused to spawn `com.automated-apply.rust` with `EX_CONFIG` (`78`) when `StandardOutPath`/`StandardErrorPath` resolved inside `~/Desktop`.
   - Updated `rust/scripts/local_install_plan.py` and `tests/test_local_rust_release.py` to precreate private `0600` log files under `~/Library/Logs/Automated Apply/{rust,frontend}.{out,err}.log` (`0700` directory, `O_NOFOLLOW`, `st_nlink == 1`).
3. **Production Supabase live-record compatibility, N+1 batching, and homepage read parity (`74a7f25`)**:
   - `rust/agent-runtime/src/platform_sessions.rs`: accepted legacy `"owner_authorized_browser_dom_indicator"` portal rows (`portal_instahyre`, `portal_internshala`, `portal_wellfound`) with `browser_scope: null` as `"unscoped"` while keeping new extension observation writes strict (`"extension_gesture_dom_indicator"`). Fixed `503 invalid_saved_platform_session` on `GET /api/v1/local-agent/platforms` and `GET /api/v1/local-agent/connections`.
   - `rust/agent-runtime/src/answer_context.rs` & `rust/agent-runtime/src/missing_store.rs`: added `Stamp::load_batch_in` and allowed already-persisted `needs_input:*` records with legacy `job_description` lengths up to `200,000` characters (`11,071` chars in 7 live rows) to validate and compute exact context digests on read while keeping `answer_contract::normalize` at `10,000` chars for new API writes. Fixed `422 invalid_missing_input_record` on `GET /api/v1/application-answers/missing`.
   - `rust/agent-runtime/src/packet_context.rs` & `rust/agent-runtime/src/packet_service.rs`: added batched `packet_context::load_batch_in` and `packet_service::list_in` using `= ANY($1)` inside the `REPEATABLE READ` transaction with `FOR SHARE` on selected `application_packets` rows and shared `assemble_read`. Reduced `GET /api/v1/application-packets?limit=100` across 35 live packets from ~421 sequential SQL queries (`>25s` timeout) to ~11 queries (`5.61s` over remote Supabase RTT).
   - `rust/agent-runtime/src/server/{boundary.rs,owner_http.rs,errors.rs}`: added owner-authenticated `GET /api/v1/dashboard/runtime` and `GET /api/v1/dashboard/overview` matching legacy dashboard counts in one read-only snapshot query.

---

## Staged Release Artifact Checksums (`rust-74a7f25df0ab63c16ee0bc9fd6c8675afcd685f6`)

| Artifact | Files | Bytes | Content Digest (SHA-256) |
| --- | ---: | ---: | --- |
| `bin/automated-apply-agents` | 1 | 27,525,264 | `618f359ffec39b4e62d09737102593133fbd5c7e379e90d6aaef18539d13da8d` |
| `bin/automated-apply-native` | 1 | 9,842,192 | `01f52314c399b318dac43c7527edb20bbd4c4aac88303d3407768b25867b0514` |
| `bin/automated-apply-documents` | 1 | 2,186,720 | `21d070195f2d4552f1c2d0b3fe7bb6ae89bfbfd31808f08240c988bb596349a6` |
| `bin/automated-apply-tools` | 1 | 12,370,160 | `40f184e7aef462c6e3a5ff16f12d2f1d0976be9a51b265fabd4e64bc12efe7d5` |
| `frontend/.next/standalone` | 1,346 | 39,385,615 | `a7b45df7a310ed8a030a95edea8a79ecc5af2a9edad24a279a7cc445566e3c42` |
| `frontend/run-local-rust.mjs` | 1 | 4,817 | `8cc62b922fd7de5b6a7aa011e4acc3e6c3eb3eeeeae3decbaff03ac17279a1b3` |
| `extension/brave` (`gdjbmkffcpicbpiikcohlmokkmcpipgp` v1.3.41) | 27 | 355,475 | `574a1810f5ad781bd6988337ea7a1b33bbb19149a45de270b676b7d585a4abff` |
| `extension/edge` (`gdjbmkffcpicbpiikcohlmokkmcpipgp` v1.3.41) | 27 | 355,466 | `174a89cc5cb63f4e179a4af1d2d96ab87a113d9b57d1451d4ae8c0429d43f727` |
| `schema/001_rust_agent_runtime.review.sql` | 1 | 9,034 | `0ead8c2e40feb0248c8448c3fff38fc44e1680de869175e3dad08e17990b045d` |

---

## Clean 36-Stage Combined Acceptance Counts (`20261119T212316Z-0a0e1fa3e5dc4e6682a994f9f0731ef9`)

- **Total stages**: `36 / 36 PASS` (`2530.912s`, `clean_commit_fixture_pass: true`)
- **Contract & lint gates (11 stages)**: `policy-drift`, `native-field-order`, `execution-contracts`, `gmail-contracts`, `contact-contracts`, `rust-format`, `outreach-contracts`, `startup-contracts`, `people-contracts`, `apify-contracts`, `rust-clippy` (`--all-targets -- -D warnings`) — all `PASS`.
- **`rust-tests`**: `427 passed, 0 failed, 1,083 ignored` (across workspace test binaries; `27.331s`).
- **`rust-postgres` (disposable native PostgreSQL 17 + headless Brave bridge)**: `1,083 passed, 0 failed` (`244.123s`), including the 4 new regression tests (`portal_legacy_owner_authorized_evidence_reads_and_transitions_cleanly`, `missing_input_reads_legacy_long_job_description_in_batch_while_keeping_write_bound`, `packet_flow_batched_list_matches_individual_reads_before_and_after_profile_drift`, `dashboard_runtime_and_overview_project_saved_counts_and_enforce_owner_boundaries`).
- **`rust-migration-catalog`**: `12 / 12` checks `PASS` (`2.542s`).
- **`backend` (pytest)**: `3,433 passed, 1 skipped, 0 failed` (`789.302s`).
- **`frontend-tests` (Vitest)**: `57 test files, 413 passed, 0 failed` (`31.579s`), plus `frontend-types` (`PASS`), `frontend-format` (`PASS`), `frontend-build` (`PASS`), `frontend-cutover-bundle` (`PASS`), `frontend-cutover-e2e` (`1 passed`).
- **`extension-tests` (Node test runner)**: `406 passed, 0 failed` (`10.105s`), plus `extension-edge` (`PASS`) and `extension-brave-final` (`PASS`).
- **Browser & E2E fixture stages**:
  - `frontend-e2e`: `21 passed` (`57.068s`)
  - `frontend-browser-e2e`: `31 passed` (`86.638s`)
  - `frontend-extension-e2e`: `1 passed` (`4.759s`)
  - `frontend-naukri-e2e`: `2 passed` (`4.420s`)
  - `extension-browser-e2e`: `26 / 26` fixture programs `PASS` (`440.767s`, `live_naukri_requests: 0`, `submitted: false`)
  - `extension-stack-e2e`: `21` verified unique correlations / `22` history rows `PASS` (`32.737s`, `all_submitted_false: true`)
  - `backend-browser-e2e`: `48 passed` (`452.533s`)
- **Guards, tooling & release packaging**: `browser-guards` (`4 passed`), `tooling` (`40 passed`), `diff` (`PASS`), `rust-release-build` (`PASS`, `328.971s`), `release-artifacts` (`PASS`).

---

## Measured Mac Resource, Latency, and Database Session Comparison (Legacy Python vs Installed Rust `74a7f25`)

| Metric | Legacy Python Stack (`api-8e985c9` + `execution` + `frontend`) | Installed Rust Stack (`rust-74a7f25` + standalone `next-server`) | Delta / Observation |
| --- | --- | --- | --- |
| **Managed service processes** | `5` (`api` uvicorn, `execution` worker, bash/node launcher, `next-server v16.4.2`) | `2` (`automated-apply-agents serve`, standalone `next-server v16.4.5`) | `-3` processes (`com.automated-apply.api` and `com.automated-apply.execution` retired into single Rust daemon) |
| **Settled idle RSS** | `~74.6 MB` (`api` `45.1 MB` + `execution` `26.9 MB` + `frontend` `~2.6 MB`) | `~7.6 MB – 15.3 MB` (`rust` `5.0–9.6 MB` + `frontend` `2.6–5.7 MB`; `13.3 MB` + `86.9 MB` immediately after cold kickstart before settling) | **4.9x – 9.8x lower** settled memory footprint |
| **Idle CPU %** | `< 0.5%` | `0.0% – 0.1%` | Negligible idle CPU |
| **`GET /health` latency** | `9.4 ms` (loopback TCP) | `0.5 – 1.5 ms` (private Unix socket) | **6x – 18x faster** |
| **`GET /ready` latency** | `2,452 ms` (remote Supabase check) | `706 – 756 ms` (remote Supabase check over private Unix socket) | **3.2x – 3.5x faster** |
| **Dashboard `GET /login` latency** | `166 ms` | `5.4 – 99.5 ms` (`5.4 ms` warm after kickstart) | **1.7x – 30x faster** |
| **Active `job_agent_runtime` DB sessions** | `2` (of `rolconnlimit = 5`) | `2` (`1` owner API + `1` execution worker; peak budget `<= 3` of `rolconnlimit = 5`) | Within `rolconnlimit = 5`; `0` leaked sessions across stop/start/kickstart |

---

## Live Operational Verification Evidence on Installed `rust-74a7f25`

### 1. Transport Security & Owner Authentication Boundary
- Plaintext TCP `GET http://127.0.0.1:8011/ready` with valid bearer token -> `426 Upgrade Required` (`{"error":"owner_api_tls_required"}`).
- Private Unix socket (`.local/rust-cfg-r15n3_f6/agent.sock`) with `Host: evil.example:8011` -> `403 Forbidden` (`{"error":"owner_host_denied"}`).
- Private Unix socket without bearer token -> `401 Unauthorized` (`{"error":"owner_authentication_required"}`).
- Dashboard Next.js gateway `GET http://127.0.0.1:3000/api/backend/dashboard/overview` without session cookie -> `401 Unauthorized` (`{"detail":"Sign in to your private workspace"}`).

### 2. Live Authenticated Route Probes Against Production Supabase (`luvdmwnlwaqgvfwlmlom`)
All 31 probed read-only endpoints returned `HTTP 200` over the private Unix socket:
- `/health` (`1.5 ms`), `/ready` (`756.3 ms`), `/api/v1/rust-agent/control` (`154.9 ms`, `{"mode":"STOPPED","revision":1,"worker_online":true}`), `/api/v1/rust-agent/capabilities` (`1.5 ms`).
- **Fixed & newly added routes**:
  - `GET /api/v1/local-agent/platforms` -> `200` (`307.4 ms`): `naukri`, `wellfound`, `instahyre`, `internshala` (`state="browser_session_observed"`, `session_evidence="unscoped"`), `work_at_a_startup` (`state="manual_only"`, `session_evidence=null`).
  - `GET /api/v1/local-agent/connections` -> `200` (`3,755.1 ms`): `29` connection rows cleanly projected.
  - `GET /api/v1/application-answers/missing` -> `200` (`4,197.2 ms`): all `14` saved `needs_input:*` rows (including the 7 rows with `11,071`-char `job_description`) validated and projected with exact `stale` status.
  - `GET /api/v1/application-packets?limit=100` -> `200` (`5,610.7 ms`): all `35` saved application packets loaded in one batched repeatable-read transaction (down from `>25s` timeout).
  - `GET /api/v1/dashboard/runtime` -> `200` (`4.7 ms`): `{"demo_mode":false,"external_notifications_enabled":false}`.
  - `GET /api/v1/dashboard/overview` -> `200` (`1,263.5 ms`): `{"applications_prepared":35,"applications_provider_confirmed":0,"applications_reported_submitted":0,"approved_gmail_messages":0,"not_yet_applied":3017,"outstanding_reviews":2,"relevant_jobs":0,"saved_jobs":3018,"shortlisted":0,"startups_discovered":1222}`.
  - `GET /api/v1/startups/search?source=himalayas&limit=5` -> `200` (`1,947.8 ms`); `GET /api/v1/startups/shortlist` -> `200` (`1,043.8 ms`). (Note: unfiltered `GET /api/v1/startups/search` across all `1,222` companies returns `503 startup_catalog_company_limit` by design, matching the 500-company unfiltered cap enforced in both legacy Python and Rust `startup_search_pg.rs`).
- **Core ported routes**: `/api/v1/profile` (`156.0 ms`), `/api/v1/jobs?limit=5` (`453.9 ms`), `/api/v1/execution/queue` (`1,684.6 ms`), `/api/v1/execution/naukri` (`4,552.5 ms`), `/api/v1/execution/naukri/jobs` (`2,155.4 ms`), `/api/v1/execution/questions` (`1,043.8 ms`, `4` items), `/api/v1/browser/plans` (`1,113.8 ms`, `16` items), `/api/v1/browser/chrome-profiles` (`789.0 ms`, `4` profiles), `/api/v1/dashboard/notifications` (`456.3 ms`, `12` items), `/api/v1/dashboard/notification-preferences` (`1,097.4 ms`), `/api/v1/dashboard/resumes` (`3,580.6 ms`), `/api/v1/dashboard/resume-sync` (`1,697.9 ms`), `/api/v1/local-agent/policy` (`445.9 ms`), `/api/v1/local-agent/search-preferences` (`446.0 ms`), `/api/v1/local-agent/history` (`1,516.7 ms`, `50` items), `/api/v1/integrations/gmail/status` (`1,340.9 ms`), `/api/v1/outreach/drafts?limit=5` (`1,343.4 ms`), `/api/v1/discovery/sources` (`5.2 ms`), `/api/v1/startups/sources` (`0.7 ms`).
- **Provider check**: `automated-apply-agents provider-status` exited `0` (`{"provider":"cohere","model":"command-a-plus-05-2026","key_authenticated":true,"model_available":true,"model_deprecated":null,"generation_flags_enabled":false,"candidate_data_authorized":true,"generation_performed":false}`).

### 3. Live Database, Policy, Quota, and Quarantine Parity Against Pre-DDL Baseline
Read-only inspection of `luvdmwnlwaqgvfwlmlom` after the `74a7f25` cutover confirmed zero drift against `.local/runtime-support/upgrade-backups/pre-rust-ddl-20261119/pre-ddl-state.private.json`:
- **Schema & privileges**: `53` public base tables (`47` legacy + `6` `rust_*` owned by `job_agent_owner` with `relrowsecurity = true` and `relforcerowsecurity = true`), `has_schema_privilege('job_agent_owner', 'public', 'CREATE') = false`.
- **Row counts**: `companies = 1222`, `jobs = 3018`, `job_source_observations = 3016`, `application_packets = 35`, `candidate_profiles = 1`, `private_resumes = 2`, `connected_accounts = 1` (Gmail connected, read + draft only), `owner_preferences = 27228`, `startup_shortlist_entries = 0`, `approved_outreach = 0`.
- **Queue & Naukri controls**:
  - `application_queue_policy`: `state = "STOPPED"`, `revision = 162`, `supervised_submission_cap = 4`, `hourly_submission_cap = 1`, `skill_match_mode = "any"`, `global_limits = {max_job_age_days: 14, applicant_limit: 1000, minimum_match_score: 50}`.
  - `naukri_automation`: `state = "STOPPED"`, `revision = 100`.
  - `rust_agent_control`: `key = "primary"`, `mode = "STOPPED"`, `revision = 1`, `has_heartbeat = true`.
- **Naukri admissions & quarantined jobs**:
  - `apply_budget:naukri:2026-11-04 = 1`, `2026-11-05 = 1`, `2026-11-06 = 1` (`3` consumed admissions; `1` fourth supervised admission remaining under cap `4`).
  - `apply_work:*`: `complete = 3430`, `waiting = 1079`, `unknown = 3` (all 3 uncertain jobs remain strictly quarantined).

### 4. Focus Preservation, Rollback Drills, Restart Recovery, and Passive Brave Native Bridge
- **First cutover attempt & rollback drill (`04:13–04:17 IST`)**: During an initial `74a7f25` swap where the pre-cutover focus snapshot was taken 3.5 minutes earlier, `window_order_unchanged` remained `true` (`4` Chrome windows `[128, 127, 148, 124]` untouched), but `foreground_pid` at compare time was macOS `UserNotificationCenter` (PID `97136`, process started Nov 10) while the owner was also actively switching between Chrome and VS Code. Following the strict rollback-on-focus-mismatch rule, we immediately rolled back to `rust-preinstall-jrnecug8`, verified `local_rollback verify rust-preinstall-jrnecug8 --compare-installed` passed, and confirmed `/ready` `200` and `/login` `200`.
- **Tight STOP-only cutover (`04:19 IST`, `focus-before-cutover-4.private.json`)**: Re-ran the cutover with an immediate before/after snapshot across `bootout` -> `cutover-preflight` -> install -> `bootstrap` -> readiness check. `scripts/macos_focus_snapshot.py --compare` returned `0` (`{"status":"PASS","foreground_unchanged":true,"window_order_unchanged":true,"active_browser_tabs_checked":false}`).
- **Restart recovery (`04:38 IST`, `focus-before-restart.private.json`)**: Executed `launchctl kickstart -k` on both `com.automated-apply.rust` (PID `62294 -> 63313`) and `com.automated-apply.frontend` (PID `62296 -> 63315`). Both services recovered within 3 seconds (`/health` `200` in `0.5 ms`, `/ready` `200` in `706.2 ms`, `/login` `200` in `5.4 ms`), and `scripts/macos_focus_snapshot.py --compare` returned `0` (`{"status":"PASS","foreground_unchanged":true,"window_order_unchanged":true,"active_browser_tabs_checked":false}`).
- **Passive Brave native bridge inspection**: Brave (PID `28567`, `.local/browser-profiles/brave-automation`, DevTools port `55599`, extension `05bb8478` v1.3.41) automatically spawned the new release's `rust-74a7f25.../bin/automated-apply-native` upon manifest update without restarting Brave. Passive DevTools inspection (`GET http://127.0.0.1:55599/json/list`) showed only `[{"type":"service_worker","url_scheme":"chrome-extension"}]` (`0` page targets, `window_id: null`). No browser window or tab was opened or activated.

---

## Acceptance Matrix

| Gate / Requirement | Status | Evidence |
| --- | --- | --- |
| Non-superuser Supabase Rust migration rehearsal & live DDL execution | **PASS** | `verify_live_migration` `12/12 PASS`; `001_rust_agent_runtime.review.sql` (`9ddab3b3...`) applied once to `luvdmwnlwaqgvfwlmlom`; `53` public tables, `6` `rust_*` tables with `job_agent_owner` + RLS + `FORCE RLS`, `owner_has_public_create = false`. |
| Clean 36-stage combined acceptance gate on `74a7f25` | **PASS** (`fixture`) | Run `20261119T212316Z-0a0e1fa3e5dc4e6682a994f9f0731ef9`: `36/36 PASS` in `2530.912s` (`427` Rust unit, `1,083` Rust PG, `3,433` backend, `413` frontend, `406` extension, all browser E2E suites). |
| Immutable release staging & rollback archive verification | **PASS** | `rust-74a7f25df0ab63c16ee0bc9fd6c8675afcd685f6` staged and verified; `rust-preinstall-248445k7` (Python) and `rust-preinstall-jrnecug8` (`e6ce7d4`) verified and proven live-restorable. |
| STOP-only whole-family LaunchAgent & native host cutover | **PASS** | `com.automated-apply.rust` and `com.automated-apply.frontend` active on `rust-74a7f25`; legacy Python `api`/`execution` disabled; `com.automated-apply.codex-history` untouched; `focus --compare` `PASS`. |
| Live auth, TLS, Host, and 31 owner API + frontend read probes | **PASS** | TCP plaintext `426`, wrong Host `403`, unauth `401`, frontend unauth `401`; all 31 authenticated GET routes returned `200` including fixed `platforms`, `connections`, `missing` (`4.2s`), `application-packets?limit=100` (`5.6s`), `dashboard/runtime`, and `dashboard/overview`. |
| Live DB data, policy, quota, and quarantine preservation | **PASS** | Exact match with pre-DDL snapshot: `3,018` jobs, `35` packets, `STOPPED` rev `162`, `naukri_automation STOPPED` rev `100`, `rust_agent_control STOPPED` rev `1`, cap `4` / hourly `1`, `3` reservations, `3` `unknown` quarantined jobs, `2 <= 5` DB sessions. |
| LaunchAgent restart recovery & focus preservation | **PASS** | `launchctl kickstart -k` on `rust` and `frontend` recovered to `200` with `focus --compare` `PASS`. |
| Passive Brave native bridge binary handoff | **PASS** (bridge) / **BLOCKED** (window) | Brave spawned `rust-74a7f25.../bin/automated-apply-native` passively; Brave remains windowless (`0` page targets, `window_id: null`). |
| Unported legacy dashboard endpoints in Rust | **NOT TESTED / UNPORTED** | `dashboard/presets`, `dashboard/connections`, `dashboard/onboarding/manifest`, `dashboard/candidate-context/*`, `dashboard/automation`, `integrations`, `jobs/search`, `browser/submissions`, `browser-applications/*`, `agent/status`, `agent/campaigns` return `404`/`422` on Rust and remain unported. |
| Live Naukri 4th supervised submission & first strict worker receipt | **BLOCKED** | Blocked on windowless Brave automation profile (`0` page targets) and owner sign-in in a visible Brave window (automatic `chrome.windows.create` is suspended per `AGENTS.md`). |
| Recurring Naukri `AUTOMATIC` mode | **BLOCKED** | Blocked on the first strict worker receipt prerequisite. |
| Instahyre, Wellfound, YC Work at a Startup, Internshala live submission adapters | **BLOCKED / NOT TESTED** | Packet preparation, manual handoff, and session observation are active; live automated submission adapters remain queued behind Naukri's first strict receipt. |
| 24-hour awake/locked runtime soak on `rust-74a7f25` | **IN PROGRESS** | Installed `rust-74a7f25` is running cleanly under LaunchAgents; the 24-hour observation window has started and has not yet elapsed. |

---

## Reproduction and Verification Commands

```sh
# 1. Verify clean combined acceptance and staged release inventory
uv run --no-project python scripts/run_acceptance.py --run --keep-going
uv run --no-project python -m rust.scripts.local_release stage --acceptance-run 20261119T212316Z-0a0e1fa3e5dc4e6682a994f9f0731ef9

# 2. Verify both rollback archives (non-destructive)
uv run --no-project python -m rust.scripts.local_rollback verify rust-preinstall-248445k7
uv run --no-project python -m rust.scripts.local_rollback verify rust-preinstall-jrnecug8

# 3. Verify read-only cutover preflight and provider status against live private config
/Users/karanagg/Desktop/Projects/automated-apply/.local/runtime-support/releases/rust-74a7f25df0ab63c16ee0bc9fd6c8675afcd685f6/bin/automated-apply-agents cutover-preflight --config /Users/karanagg/Desktop/Projects/automated-apply/.local/rust-cfg-r15n3_f6/runtime.private.env
/Users/karanagg/Desktop/Projects/automated-apply/.local/runtime-support/releases/rust-74a7f25df0ab63c16ee0bc9fd6c8675afcd685f6/bin/automated-apply-agents provider-status --config /Users/karanagg/Desktop/Projects/automated-apply/.local/rust-cfg-r15n3_f6/runtime.private.env
```

---

## Next Actions

1. **Owner-gated Naukri live receipt**: Open a visible ordinary window in the dedicated Brave automation profile (`.local/browser-profiles/brave-automation`), confirm Naukri sign-in and extension profile selection (`window_id != null`), and run the single authorized 4th supervised Naukri attempt (`supervised_submission_cap = 4`, `hourly_submission_cap = 1`, keeping the 3 `unknown` jobs quarantined) to capture the first strict worker receipt.
2. **24-hour stability check**: Observe `com.automated-apply.rust` and `com.automated-apply.frontend` across awake/locked intervals via `~/Library/Logs/Automated Apply/{rust,frontend}.{out,err}.log`.
3. **Remaining dashboard & platform adapters**: Port remaining legacy dashboard routes if required for UI parity and validate Instahyre, Wellfound, YC Work at a Startup, and Internshala live adapters individually after Naukri's first strict receipt.
