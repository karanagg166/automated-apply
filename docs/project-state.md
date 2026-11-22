## Latest local acceptance, 2026-11-22

The clean combined gate passed all 37 stages at `4dab75e`. The exact release
is running locally with the worker online and the application queue stopped.
The installed MCP saved 20 Himalayas jobs and 20 We Work Remotely jobs. All
eight saved-job MCP tools returned their platform responses. One deterministic
saved-review run completed with zero model calls and one verified Telegram delivery.
The coordinator is back at STOPPED. The three Naukri quarantines, three
reservations, confirmed profile and resume checks matched their retained
state. The launchd Desktop-access report is still pending. See the
[local release report](acceptance/local-dashboard-release-20261121.md#november-22-public-feed-release-follow-up).

Two of eight portal sessions are verified. Wellfound retained the confirmed
city, role preferences, biography and education. Instahyre accepted the
fresher choice, salary and location preferences, portfolio-backed internship
and final profile fields. It advanced to mobile verification. AGY can reuse
the owner-confirmed facts from the private `portal_candidate_facts_v1`
database record. Naukri remains at email-only sign-in, so the fourth
supervised attempt and the first strict receipt are still pending. See the
[portal report](acceptance/local-brave-portal-accounts-20261121.md#november-22-profile-follow-up).

Microsoft Edge is installed and its five affected browser fixtures passed
after correcting the fixture bundle selection. All five Brave regression
cases passed. Several Edge focus comparisons changed, so Edge live focus
and portal acceptance are still open. The active release continues on Brave.
See the [Edge fixture report](acceptance/local-dashboard-release-20261121.md#microsoft-edge-browser-fixtures).

## Earlier local work, 2026-11-22

Local `--allow-telegram` support (`db3d582`, `ccdf57e`) is committed locally on `feat/rust-agent-runtime` (ownership transferred in `.git/automated-apply/worktree-ownership.json` after Codex paused; `.worktrees/antigravity-completion-20261121` retained cleanly awaiting separate cleanup approval). Clean combined acceptance run `20261121T224854Z-8a683d7e5bf443449a2520fbbbd86306` on `ccdf57ed7b8ffd36ed1075903579cc86ed9f4192` passed **all `37 / 37` stages** in `2,230.467s` (following an interrupted `35/37` run and a `36/37` transient Brave launch flake that passed `12/12` in isolation) and staged immutable release `rust-ccdf57e`. Guarded direct-process cutover then upgraded live local services from `c4329d1` to `ccdf57e` (`PID 75651` rust / `75728` next-server / `75892` direct observer, rollback `rust-preinstall-pqbxseh3`, cutover plan `rust-plan-gtu8r87i` with `--allow-telegram`), keeping `~/Library/LaunchAgents/*.plist` untouched (`rust-preinstall-m4v4yhix` preserved) while macOS Desktop-Folder consent remains pending. Verified live: macOS focus `PASS`, `check-retained.py --cutover-fingerprints` `changed_checks: []` (`3,036` jobs, `35` packets, `STOPPED` rev `162`/`100`/`1`), live Telegram (`enabled: true`, `bot_id: 8842646800`, `live_poll` `last_poll_at: 2026-11-21T23:54:31Z`), batched Startup Explorer HTTP `200` on `total: 1,239` companies (`28.839s` / `18.232s`), all `21` owner API endpoints `200` + `401` auth boundaries, `26`-tool local MCP (`telegram_notify_run` included), and Hacker News local completion (`+18` jobs -> `9` fresh 14-day / score ≥ 50 matches; `remotive` `429`, `arbeitnow` `503` retained). On Instahyre (`brave-automation`), verified `20` skills, Step 2 preferences, education `5693636`, and canonical v5 PDF `4826702` (`cfc0d859...`, `100,198` bytes) with macOS focus `PASS`, paused honestly on Step 3 required current-employment input. Remaining owner/OS gates: Naukri visible sign-in for Brave pin migration (`063e153`) and 4th supervised receipt, interactive macOS Desktop consent (`check-catalog-desktop-access.command`), truthful personal facts (Instahyre current employment, Wellfound location & graduation month), and anti-bot/CAPTCHA-blocked portals. See [the dashboard release report](acceptance/local-dashboard-release-20261121.md) and [the Brave portal report](acceptance/local-brave-portal-accounts-20261121.md).

## Current local work, 2026-11-21

The new local Brave pin replacement command passed six disposable PostgreSQL checks and rejected an invalid review at its normal CLI entry point. It archives the previous mapping and uses the existing owner lock and selector. The local account and STOP controls remain in place. An actual pin change requires the signed-in Brave identity and matching canonical resume review. See the [portal report](acceptance/local-brave-portal-accounts-20261121.md).

The fixed browser pin and approved Naukri account both still identify the old Chrome binding. The dedicated Brave connection is live, and the sole retained extension task is paused under global STOP with no plan. Naukri offers the same recovery route already attempted, and the local recipient-matched mail check found zero recent recovery messages. Its browser and account binding migration awaits fresh authenticated identity and resume evidence. Public Apify documentation search and HiringCafe job search both passed live on their official MCP endpoints. See the [portal report](acceptance/local-brave-portal-accounts-20261121.md) and [MCP checks](agent/mcp-and-browsers.md#apify).

The catalog installation dry run now accepts the current verified direct-process baseline. It passed the exact release, rollback, loopback-owner and STOP checks. Six focused handoff guards passed. The exact launchd access result is still pending. A saved Naukri search returned zero jobs within the 14-day published-date and score-50 filters. Wellfound's missing LinkedIn field remained empty after one unconfirmed save intent. Exact current location and graduation month evidence are still needed for its remaining profile fields. See the [access probe](acceptance/local-dashboard-release-20261121.md#desktop-access-before-cutover) and [portal report](acceptance/local-brave-portal-accounts-20261121.md).

The staged catalog release and its rollback now have a one-shot macOS Desktop access launcher. All four exact commands passed when run directly, and a launchd no-op verified the launcher lifecycle with foreground and window order preserved. Running the four exact commands through launchd awaits the owner's Desktop consent window. The baseline worker is still serving with STOPPED controls. Separately, the dedicated Brave binding is live and matches its current browser session, while the selected binding is a different offline profile. The Naukri tab still shows sign-in. See the [access probe](acceptance/local-dashboard-release-20261121.md#desktop-access-before-cutover) and the [Brave account report](acceptance/local-brave-portal-accounts-20261121.md).

Wellfound's saved credential matched the latest owner choice in a local Keychain check. Instahyre retained its verified session, and its password change still needs access to the current credential or a reachable recovery form. Himalayas reported no account for the selected email, and its signup control stayed disabled after form validation. Two of eight portal sessions are verified. The installed `c4329d1` MCP passed all 15 saved-data calls in a live local check. See the [Brave account report](acceptance/local-brave-portal-accounts-20261121.md) and [dashboard release report](acceptance/local-dashboard-release-20261121.md).

Instahyre was recovered with its authenticated email and signed in within the existing dedicated Brave automation profile. Candidate account settings showed the owner-selected address after reload. Wellfound also restored its previous session in the separate dedicated portal profile. The private AGY handoff now identifies both sessions. Naukri remains blocked on email-only sign-in. See the [Brave account report](acceptance/local-brave-portal-accounts-20261121.md).

Source `502d5e5` passed all 37 combined stages and staged the catalog release. Its optimized startup search handler returned two distinct 12-company pages from 1,221 eligible companies in a read-only check against the actual saved catalog. macOS requested Desktop-folder consent for the new service binary, and both local cutovers timed out. The previous release `c4329d1` is serving the dashboard under a temporary local launch. All 19 retained state checks matched. A process-bound observer recorded HTTP 200 on all four readiness checks in its first sample. Persistent launch and HTTP verification through the installed dashboard await the Mac prompt. See the [startup catalog report](acceptance/local-dashboard-release-20261121.md#startup-catalog).

The dedicated Brave window is open with the verified extension, and the Naukri login form has the owner-selected email entered. Naukri's email recovery returned HTTP 403. Google also blocked the sign-in attempt. The selected browser binding and Naukri account identity still need live confirmation after the owner enters their credentials. The queue remains STOPPED with three quarantines and one supervised admission remaining. See the [Brave account report](acceptance/local-brave-portal-accounts-20261121.md).

AGY passed all 37 clean gates on `c4329d1`, installed it locally, and verified restart and macOS window order. The installed default Jobs page returned HTTP 200 in 3.918 seconds. All ten owner dashboard reads and the 25-tool MCP catalog passed readback. All 19 retained state checks matched the previous snapshot. The initial 24-hour observer ended during the catalog cutover. The owner launcher in `.local/browser-profiles/open-brave-naukri-automation.command` passed preflight while the dedicated profile was windowless. See the [dashboard release report](acceptance/local-dashboard-release-20261121.md).

The startup catalog follow-up batches saved reads while preserving full ranking and totals before pagination. The installed catalog has 1,222 companies. All 73 focused startup PostgreSQL cases passed, including two distinct pages covering the same total in a 1,222-company fixture. See the [startup catalog section](acceptance/local-dashboard-release-20261121.md#startup-catalog).

Apple Mail delivered the Wellfound recovery email for the owner-selected account. The dedicated portal profile restored that account after Brave reopened, and Wellfound retained the confirmed profile version 5 PDF after reloading. The Wellfound profile editor still shows required fields. AGY can read the local observation record in `.local/browser-profiles/portal-status.private.json`. See the [Brave account report](acceptance/local-brave-portal-accounts-20261121.md).

The clean checkout at `95c724c` passed 36 of 37 combined stages, including all 1,091 Rust PostgreSQL cases and 48 backend browser cases. One Gmail UI test timed out at the loading state. The isolated fixture passed all nine cases with the notification scheduler corrected. The installed `d7d0484` baseline returned HTTP 200 from all four readiness checks and its worker reported STOPPED. The corrected checkout needs its own clean combined release gate. See the [dashboard release report](acceptance/local-dashboard-release-20261121.md).

The exact checkout at `e53517e` passed all 37 combined checks and staged a checksummed local release. The first install rolled back after a focus change. The second preserved focus through service activation and rolled back when the legacy Automation status endpoint failed. The prior release is running with the rollback inventory verified. Three restored Automation reads passed the focused PostgreSQL HTTP fixtures. The revised source needs its own combined gate and live read checks. See the [dashboard release report](acceptance/local-dashboard-release-20261121.md).

The Jobs search release at `df3ba53` finished with 36 of 37 local stages passing. The single failure was a readiness timeout in the Brave retained-form fixture. The correction polls from the Playwright driver, measures the actual alarm count, and passed the isolated Brave fixture in 34.650 seconds. Installation awaits a clean combined result on the corrected source. An independent installed-data read matched the 3,018 jobs, 35 packets, three quarantined outcomes, three admissions and STOPPED controls. See the [dashboard release report](acceptance/local-dashboard-release-20261121.md).

Clean source `e84bf06d4514dfb1ce0fdcaf9154420482051370` passed all 37 local acceptance stages. A live read of `d7d0484` reproduced a 25-second timeout on the normal Jobs page. Source `cb7bd4f868b576067fbdcf2dcea40cd9e7acd5f5` limits full display reads to the selected page in the same database snapshot. A read-only SQL comparison matched filter input for all 3,018 jobs and the details of all 20 first-page jobs, with projected JSON text reduced from 21.4 MB to 4.0 MB. The focused PostgreSQL HTTP fixture passed, including ranking and exclusion checks. The revised release awaits combined validation before installation. See the [dashboard release report](acceptance/local-dashboard-release-20261121.md).

Source `bb05b2bd377976b345b5ab2f8ebc1ccc68f10698` restores owner commands on the Rust Agent page for saved job discovery, selection and packet preparation. Dashboard commands commit the local draft, isolated selection and replay receipt together. All 13 focused PostgreSQL checks and 12 focused frontend checks passed, along with TypeScript, Rust formatting, strict Clippy and HTTP policy drift checks. The installed release still awaits the updated combined gate. All four endpoints returned HTTP 200 in each of the 54 runtime observations through `2026-11-20T19:29:29Z`. The dedicated Brave profile still exposed zero page targets. See the [dashboard command report](acceptance/native-dashboard-commands-20261121.md).

Source `37c8acaceeb7edd252beb2d312bc41df2ff36b58` connects both dashboard URL forms to native packet preparation. Two PostgreSQL HTTP fixtures, 50 focused frontend tests, TypeScript and strict Clippy passed. Concurrent requests converged on one draft and preserved submission authority. A fresh read of the installed `d7d0484` database matched the earlier queue, quarantine, reservations, jobs and packets. The new source awaits combined validation and installation. See the [URL intake report](acceptance/packet-url-intake-20261121.md).

Source `265de1925bd94abeaad03e07cdf3f681b7c98cfb` restores six saved campaign, submission and browser review reads on Rust. The Agent page now links to the native workflow and distinguishes its worker from legacy campaign execution. One disposable PostgreSQL HTTP regression, 18 focused frontend cases, TypeScript, strict Clippy and contract drift checks passed. The installed `d7d0484` release remains in place during the 24-hour observation. All 47 samples checked through `2026-11-20T19:08:17Z` were healthy, and an independent read matched the previous queue, reservations and quarantine state. The dedicated Brave profile remains windowless. See the [saved review report](acceptance/legacy-review-dashboard-20261121.md).

Source `56317e0512d4650be9b6922c9a3ec312288f56a3` restores the Rust dashboard Build action for authorized local templates and pinned Git checkouts. It builds pending evidence and rechecks configuration and project revisions before saving. Three disposable PostgreSQL HTTP fixtures and strict Clippy passed, including a concurrent configuration change while the build waited to save. The installed release still needs configured sources and the next combined gate before live Build verification. Eleven unlocked readiness observations on the installed release were healthy through `2026-11-20T17:19:19Z`. See the [project evidence build report](acceptance/candidate-context-build-20261120.md).

Source `26b555f7cb78661aeeb6af622ac523db6b235859` restores candidate-context configuration reads and saves, project list and detail, explicit review of stored project evidence and an approved-evidence answer preview. The disposable PostgreSQL HTTP fixture and strict Clippy passed. This source and the earlier Discover repair await the next combined release gate. The current installed release returned six healthy observations through `2026-11-20T17:04:11Z`. Brave still had zero page targets. See the [candidate-context report](acceptance/candidate-context-dashboard-20261120.md).

Gemini's `d7d04845d290a205aeffcfebcbc2b0a517b072d0` passed all 36 combined local stages and is now installed on this Mac under `com.automated-apply.rust` and `com.automated-apply.frontend`. The previous release stalled on database-backed routes. A STOP-only restart restored it before the tested update. The new local cutover plan is `rust-plan-pl_ecsw6` with verified rollback `rust-preinstall-d1s1mcdl`. macOS foreground and window order matched across the cutover. The seven new API reads, authenticated readiness, dashboard login, and six read-only tools on the project-scoped MCP were verified live. Database comparison preserved the 3,018 jobs, 35 packets, queue policy, three admissions and three quarantined outcomes. The queue stays STOPPED at revision `162` with one supervised Naukri admission available. See the [exact update and recovery report](acceptance/local-rust-recovery-20261120.md).

The owned Brave profile still exposes zero page targets. The remaining supervised Naukri application and first strict worker receipt await a visible signed-in window in that profile. The one-shot 24-hour observation started at `2026-11-20T16:49:02Z` with healthy runtime and dashboard reads. Eight legacy dashboard reads still returned 404. Native workflow and the execution queue remain available. The continuity backup preserved nine of 107 indexed transcripts. The remaining 98 files were absent from both known local transcript directories and private snapshots. See the [completion plan](plans/completion-execution-20261116.md).

The Discover page source now uses the existing Rust public feed and discovery schedule controls when the installed socket is configured. Twelve focused frontend tests and the private-socket launch fixture passed, as did the production build and TypeScript. This source change awaits the next combined acceptance and local install. Gemini independently restarted and verified the same installed `d7d0484` release. The observer recorded healthy readings after its PID changes. Local Gmail reauthorization remains pending. See the [Discover verification](acceptance/local-rust-recovery-20261120.md#discover-page-follow-up) and [Gemini's cutover report](acceptance/local-rust-cutover-20261120.md).

## Initial local Rust cutover, 2026-11-20

The active goal limits delivery to the owner’s laptop. GitHub pushes, pull requests, remote reports, hosted Actions and merges remain suspended until the owner reauthorizes them. Finish source and fixtures, run combined validation, then install and verify locally. See the [completion plan](plans/completion-execution-20261116.md).

The live Supabase additive Rust schema migration (`supabase/runtime/001_rust_agent_runtime.review.sql`, raw SHA-256 `9ddab3b3ff3db54d215f240e9656096356e058f00a48f08160397bc4dc82c969`, catalog SHA-256 `ea94a97e49331041610d20821c2a479abeea7d58f10717e317606f73d2f2b46a`) is applied and verified on `luvdmwnlwaqgvfwlmlom` (`53` public tables, `6` `rust_*` tables owned by `job_agent_owner` with RLS and `FORCE RLS`, `owner_has_public_create = false`, `rust_agent_control = STOPPED` revision `1`). Local commit `e6ce7d4` fixed non-superuser schema ownership transfer; local commit `796ca0b` moved LaunchAgent logs to `~/Library/Logs/Automated Apply/` outside `~/Desktop` TCC restrictions; local commit `74a7f25df0ab63c16ee0bc9fd6c8675afcd685f6` fixed legacy `"owner_authorized_browser_dom_indicator"` portal evidence reads, allowed legacy persisted `>10k`-char `needs_input:*` job descriptions on read with batched `Stamp::load_batch_in`, batched `GET /api/v1/application-packets` list reads (`5.6s` for all 35 live packets vs `>25s` timeout), and added owner-only `GET /api/v1/dashboard/runtime` and `GET /api/v1/dashboard/overview`.

Clean combined acceptance run `20261119T212316Z-0a0e1fa3e5dc4e6682a994f9f0731ef9` at `74a7f25df0ab63c16ee0bc9fd6c8675afcd685f6` passed all 36 stages in `2530.912s` (`427` Rust unit, `1,083` Rust PostgreSQL, `3,433` backend, `413` frontend unit, `406` extension unit, and all browser E2E stages). Immutable release `rust-74a7f25df0ab63c16ee0bc9fd6c8675afcd685f6` is staged and active under LaunchAgents `com.automated-apply.rust` and `com.automated-apply.frontend` via verified plan `rust-plan-11ybx67o` (~7.6–15.3 MB settled RSS across 2 processes vs ~74.6 MB across 5 legacy Python/Node processes, `2` active `job_agent_runtime` DB sessions of `rolconnlimit = 5`). Both rollback archives `rust-preinstall-248445k7` (Python stack) and `rust-preinstall-jrnecug8` (`rust-e6ce7d4`) are verified and proven live-restorable. Tight cutover and `launchctl kickstart -k` restart recovery both passed `scripts/macos_focus_snapshot.py --compare`. All 31 probed live endpoints returned HTTP 200, and all existing data (`3,018` jobs, `35` packets), STOPPED queue policy (revision `162`, cap `4`, hourly `1`, `skill_match_mode = any`), `3` Naukri reservations, and `3` `unknown` quarantined jobs remain intact. The engineering estimate is now 72% complete and 28% remaining: the dedicated Brave automation profile remains windowless (`0` page targets), so the fourth supervised Naukri submission and first strict worker receipt remain blocked on owner sign-in in a visible Brave window. See the [local Rust cutover report](acceptance/local-rust-cutover-20261120.md).

## Previous local work, 2026-11-19

The clean combined run at `6337de745594e26e09c77c48e951d9dc90d9bfb5` passed all 36 stages in 45 minutes. The matching release is staged. Inactive cutover plan `rust-plan-szfg9cky` and rollback snapshot `rust-preinstall-248445k7` passed verification. The existing application is still healthy. Direct read-only inspection found zero of six required Rust tables, a restricted database role without CREATE, a STOPPED application queue at revision 162, and STOPPED legacy preparation. The optimized candidate refused cutover on the required schema check. The exact reviewed SQL package awaits owner backup confirmation and execution in the existing Supabase project. The previously requested dedicated Brave sign-in step and strict fourth supervised Naukri receipt remain pending. See the [exact combined results](acceptance/local-combined-backend-20261118.md#clean-release-candidate-at-6337de7).

Local source `b1789dd` repaired the Rust contract and workspace test failures. Local source `cc18359` cleared strict Clippy. A clean combined run at `cc18359` passed 12 of 36 stages and stopped at backend. Rust reported 427 passes, zero failures and 1,079 ignored database cases reserved for the separate PostgreSQL stage. Backend reported 3,410 passes, 21 failures and one skip. The failures exposed gaps in the disposable database and browser fixture setup. See the [current combined validation report](acceptance/local-combined-backend-20261118.md).

The clean combined run at `9e3956c` finished with 23 passing stages, six failures and seven unmet prerequisites. Local commit `2dbf61f` restores both production builds and the private-socket dashboard launch fixture. PostgreSQL isolation improved the separate database run to 939 of 1,079. A later repair batch passed 146 of 154 selected cases. The remaining work includes the clean combined run, actual Mac browser acceptance, local release cutover and the strict Naukri receipt. The documented Brave test profile was disconnected by its exact revision. The installed selection and the other profile connection states were verified afterward. See the [local results and recovery evidence](acceptance/local-combined-backend-20261118.md).

The next PostgreSQL run passed 1,037 of 1,079 cases, including the native Rust bridge in an isolated Brave profile, all 16 browser form cases and the Gmail draft-only loopback workflow. The first targeted rerun cleared 31 of the 42 original failures, and the next cleared nine of the remaining 11. The rebuilt dashboard passed all 31 dedicated Brave cases. Both separate Naukri dashboard cases passed. The two-profile Brave fixture verified inactive tab reuse, one retained field receipt and restart recovery on fictional data. Combined validation and live installation acceptance are still pending. The [local combined report](acceptance/local-combined-backend-20261118.md) records the scope of each run.

Local source `aa82936` restored UUID-bound discovery on the Python compatibility API and filtered owner reads in Rust. The six-case Rust HTTP batch cleared the final two cases from the earlier targeted run. All eight focused owner dashboard journeys and all 21 Python discovery tests passed. The exact clean-commit combined run still needs to verify the integrated candidate. Installed loopback API health and the dashboard login route independently returned HTTP 200.

Local source `6cc1edb` restored the Brave reload cases for the isolated maintenance and legacy native stacks. The main extension browser run passed 25 of 26 fixture programs. The remaining maintenance program passed on its focused rerun. The legacy full-stack fixture passed 23 cases, and the bound Prepare case verified unchanged foreground windows and tabs in the fixture. Both installation and actual Naukri acceptance remain open.

Private continuity snapshot `22c026fdc9def3555bdaab0dd44014bd9ec33c4e01f3b8433b936aa3ee3f6608` at `2026-11-19T09:49:23.064686+00:00` captured nine available local transcripts from 107 project threads. Ninety-eight transcripts remain unavailable in the local Codex transcript directories. The integrity check verified 3,640 saved transcript references across the existing snapshots.

Focused checks have now passed for the 21 backend failures across the repair batches. The disposable database uses a per-run password. Signed browser routes share the operation's database session after it takes the browser lock. Named cancellation can interrupt browser I/O before acquiring a database connection for reconciliation. Isolated Brave fixtures passed the pre-dispatch cancellation, post-dispatch unknown-outcome, signed review, and mock receipt paths using one database connection. The next complete run must pass on a clean commit before release staging.

The combined rerun at `8cf1537` cleared all 21 earlier backend failures. It passed 12 stages and the backend suite reported 3,426 passes, five failures and one skip. The five remaining failures were an outdated approval-dependency audit and four reliability fixtures assuming PostgreSQL trust authentication. All 14 cases in the two affected modules passed after the fixture repairs. See the [updated combined report](acceptance/local-combined-backend-20261118.md).

The clean combined run at `667290a` passed 13 stages. Backend finished with 3,431 passes and one skip. The frontend stage reported 409 passes and four test fixture/assertion failures. The two affected files passed all 14 tests after repair, formatting passed, and 26 runner and release tests passed. Use `--run --keep-going` to collect independent results together while preserving the complete clean-commit release gate. See the [combined report](acceptance/local-combined-backend-20261118.md).

The first 36-stage combined run at `8d0bc72` passed 10 stages and stopped at Rust compilation. Local repair `615f981` restored compilation and ran the Rust workspace tests. The result was 403 passing, 24 failing and 1,079 ignored. The first run left 25 stages untested. Continue targeted repairs from the private logs before the next combined run. The offline cutover planner is implemented. Installation and live verification remain pending. Report actual gate outcomes in place of the older rough estimate. See the [combined validation baseline](acceptance/local-combined-baseline-20261118.md).

Private continuity snapshot `df649153ddf8004fbebdd23b1d8e3a74a36e7816e420d3c0d5f6f13715c58cfa` at `2026-11-17T22:03:58.751943+00:00` preserved six available transcripts from 104 indexed threads. The other 98 transcripts remain missing.

Local source `5d47c49` ties Rust release staging to the checksums of a clean combined run and retains separate Brave and Edge packages. The 36-stage plan adds the optimized build and checksum inventory. A private rollback snapshot preserved nine installed definitions and verified 16 referenced paths. Release build, staging and restore acceptance remain pending. See the [local release checkpoint](acceptance/rust-release-package-local-source-20261118.md).

Private continuity snapshot `e5a45cf1da7108d3c942f60a826d94a367e9c9ab6c6905fc285868160ed9852c` at `2026-11-17T21:57:27.290496+00:00` preserved six available transcripts from 104 indexed threads. The other 98 transcripts remain missing.

Local source `23ceb62` adds a Node launcher for the dashboard's standalone Rust release and a fixture for both authenticated dashboard API routes through one private Unix socket. The combined plan now has 35 stages. A passive launchd inventory confirmed that the installed API, execution service and dashboard still use Python launchers. The new dashboard launch fixture awaits the combined run. See the [dashboard cutover checkpoint](acceptance/frontend-rust-cutover-local-source-20261118.md).

Private continuity snapshot `9d057f2fb134e05fef9562adec41ca4aba5200603a636a2040240672c3ccdb12` at `2026-11-17T21:37:39.916304+00:00` preserved six available transcripts from 104 indexed threads. The other 98 transcripts remain missing.

Local source `be597e9` adds a read-only Rust cutover command for the saved STOPPED controls and role session counts. The reviewed migration now also checks any saved legacy Naukri preparation control. Both PostgreSQL checks await the combined run. The pooler and rollback inventories still need independent verification. See the [cutover preflight checkpoint](acceptance/rust-cutover-preflight-local-source-20261118.md).

Private continuity snapshot `f2088bb4d15842f7fd547e0ab449eb068ca988fe0995a5d8c194723fba4ef8ad` at `2026-11-17T21:32:46.642997+00:00` preserved six available transcripts from 104 indexed threads. The other 98 transcripts remain missing.

Local source `398e250` adds the reviewed Rust migration rehearsal to the 33-stage combined plan. The private report records starting and ending Git state and identifies a clean commit that passed all stages. Only the plan and source checks have run. See the [local migration rehearsal checkpoint](acceptance/rust-migration-rehearsal-local-source-20261118.md).

Private continuity snapshot `45b2a6502efc77ff4b1ac0e29923351af1cda027c871a940dc3f0968eef67cba` at `2026-11-17T21:28:52.111832+00:00` preserved six available transcripts from 104 indexed threads. The other 98 transcripts remain missing.

Local source `b8180c6` adds the real Brave extension, Rust native host, Rust HTTP API and disposable PostgreSQL journey to the combined gates. The 32-stage plan includes the fixture after the Brave build. The fixture has not executed. See the [Brave Rust fixture checkpoint](acceptance/brave-rust-stack-fixture-local-source-20261118.md).

Private continuity snapshot `a40e68e3401b3bb42d39eb3ee8f41fb4929e5f1e14f39220b66451b763a40463` at `2026-11-17T21:25:00.574244+00:00` preserved six available transcripts from 104 indexed threads. The other 98 transcripts remain missing.

Local source `898692e` advances a closed original Naukri questionnaire with the exact Applied observation into independent history verification. It preserves the original document and admission checks. Two extension cases and one PostgreSQL case await the combined run. See the [questionnaire completion checkpoint](acceptance/naukri-questionnaire-completion-local-source-20261118.md).

Private continuity snapshot `d6aac7136893ccc0d07fcc5cb771550b8f6c447c0e02a692d707315cd2f3297e` at `2026-11-17T21:21:16.719437+00:00` preserved six available transcripts from 104 indexed threads. The other 98 transcripts remain missing.

Local source `579be22` ties the Naukri first worker receipt to the admitted Apply and authenticated browser acknowledgment, independent history, and immutable packet evidence. Admission-only outcomes remain eligible for read-only history reconciliation. The new and revised fixtures await the combined run. See the [Naukri receipt checkpoint](acceptance/naukri-worker-dispatch-proof-local-source-20261118.md).

Private continuity snapshot `d99d91b4281efaa334bae099d4fa52039e6086d903bb728080ac2e35df36f148` at `2026-11-17T21:17:06.610057+00:00` preserved six available transcripts from 104 indexed threads. The other 98 transcripts remain missing.

Local source `67a06d2` links approved HiringCafe imports to supported employer application pages when the saved posting and employer vacancy identities agree. The packet retains the original listing and flags changed employer evidence as stale. One new dashboard case and one PostgreSQL case await the combined run. See the [employer handoff checkpoint](acceptance/hiringcafe-employer-handoff-local-source-20261118.md).

Private continuity snapshot `7ac5e3c6ac244a778f113fac3fbde7198cbbab1f7065d31f8cefae4a2b89cfe2` at `2026-11-17T21:11:57.409968+00:00` preserved six available transcripts from 104 indexed threads. The other 98 transcripts remain missing.

Local source `4161b16` registers HiringCafe's official project MCP and accepts the attributed job links it returns in owner-reviewed imports. Legacy bare-ID and updated-slug links reuse retained posting identity. Two fixtures await the combined run. Recent public MCP research verified the provider link shape. Installed workflow, employer form and receipt acceptance remain pending. See the [HiringCafe checkpoint](acceptance/hiringcafe-connector-local-source-20261118.md).

Private continuity snapshot `f84192786975c6cd4723310151a4d87561c19452cedd172624d035fd306f9211` at `2026-11-17T21:08:27.576890+00:00` preserved six available transcripts from 104 indexed threads. The other 98 transcripts remain missing.

Local source `b74e107` keeps worker scheduling available during the configured Cohere planner's HTTP wait. Run and monthly provider reservations commit before the request. One new actual-process PostgreSQL fixture awaits the combined run. The estimate remains 58% complete. See the [model worker checkpoint](acceptance/model-worker-local-source-20261118.md).

Private continuity snapshot `4f5a1334608ff278c39f284ce427dadc4db7cdbfbfa3c9542cb71fff6b70f836` at `2026-11-17T20:58:44.624861+00:00` preserved six available transcripts from 104 indexed threads. The other 98 transcripts remain missing.

Local source `adca6e9` separates scheduled feed HTTPS work from the application worker's PostgreSQL connection. Intake now checks both saved control revisions and can reuse a valid cache after Resume. One new PostgreSQL fixture and the existing worker cancellation cases await the combined run. The estimate remains 58% complete. See the [scheduled feed worker checkpoint](acceptance/scheduled-feed-worker-local-source-20261118.md).

Private continuity snapshot `12c3c6e6397d38a89f87593cc9334a7188409724a00864616beaaf89d3f43fe1` at `2026-11-17T20:53:37.041840+00:00` preserved six available transcripts from 104 indexed threads. The other 98 transcripts remain missing.

Local source `51a20ee` binds new portal observations to the selected ordinary browser session and marks stale and legacy unscoped evidence in Connections. One PostgreSQL and one extension fixture await the combined run. Applicant identity and submission still require provider-specific evidence. The estimate remains 58% complete. See the [portal observation checkpoint](acceptance/portal-observation-scope-local-source-20261118.md).

Private continuity snapshot `37d6a08edaf5c39f39b392d3e1235863a069da8dd5acd62bc81a7daa3c9ee532` at `2026-11-17T20:47:42.446946+00:00` preserved six available transcripts from 104 indexed threads. The other 98 transcripts remain missing.

The latest local source `60d05a6` restores owner-approved listing imports in the Rust service and dashboard, including Internshala and HiringCafe. Two disposable PostgreSQL fixtures and one frontend fixture await the combined run. The estimate remains 58% complete. Continue platform account evidence and authorized discovery adapters. See the [manual discovery checkpoint](acceptance/manual-listing-import-local-source-20261118.md).

The private continuity snapshot `4ee5aa4d185fe8b02c04f9338d0234036f7237a53c01472ddbb782c2160301a2` at `2026-11-17T20:40:03.634655+00:00` preserved the six locally available transcripts from 104 indexed threads. The remaining 98 transcripts were missing.

The latest local source `8e946a2` adds packet preparation for Instahyre, Wellfound, YC Work at a Startup, Internshala, HiringCafe, Himalayas and We Work Remotely. Feed preparation keeps the exact link and the original provider attribution. Four standard fixtures and one disposable PostgreSQL fixture await the combined run. The estimate remains 58% complete. Continue the remaining platform discovery and account adapters. See the [expanded packet checkpoint](acceptance/expanded-packets-local-source-20261118.md).

The private continuity snapshot `5f8b663bb2aef82e2f248aed9ec4eb5a9ab84b984ef50fcb30bccbafa9912e07` at `2026-11-17T20:28:41.971019+00:00` indexed 104 threads and preserved the six available transcripts. The other 98 transcripts remain missing.

The latest local source `437e7a1` serves owner commands, operation history, and authenticated extension preview and connection commands. Two new disposable PostgreSQL fixtures await the combined run. The estimate remains at 58% complete. Next, fix the platform packet selection gap and implement the remaining adapters. See the [owner command checkpoint](acceptance/owner-commands-local-source-20261118.md).

The private continuity snapshot `acf57ec4fe8ed4ab543bfb682faf519796b0cfec62d78425e59c1f2ab10c63d3` at `2026-11-17T20:19:12.340320+00:00` indexed 104 threads and preserved the six available transcripts. The other 98 transcripts remain missing.

The latest local source `8d6acf3` serves the dashboard's connections route with a read-only evidence snapshot. It includes version-bound profile and local PDF checks, saved portal and Gmail evidence, Telegram binding evidence and optional private CLI/MCP receipts. Two disposable PostgreSQL fixtures await the combined run. The estimate remains 58% complete. Next, port the owner command and history routes and reconcile platform adapter coverage. See the [connection report checkpoint](acceptance/connection-report-local-source-20261118.md).

The private continuity snapshot `e288216fc222d13d6b5d86799fce42c05acb2bf79ca2c9a500220d74db6b13b4` at `2026-11-17T20:11:36.071986+00:00` indexed 104 threads and preserved the six transcripts available locally. The other 98 transcripts remain missing.

The latest local source `efb52e0` and `3da66f2` adds the dashboard platform policy, versioned history, manual portal controls and native gesture observations. The four new disposable PostgreSQL fixtures are awaiting the combined run. Next, connect the dashboard status report to the saved portal projection and reconcile the remaining owner command and history routes. See the [platform controls checkpoint](acceptance/platform-controls-local-source-20261118.md).

The private continuity snapshot `1d5081c80a7ba88f85f6247d0bbeb33d3e096e46e3c8f31a01862dc01f3abc5a` at `2026-11-17T20:00:37.840534+00:00` indexed 104 threads and preserved the six available transcripts. The other 98 transcripts remain missing.

The latest source commits `86d438f` and `d7fddf9` port cached filters, route dashboard search preferences to the Rust service, and wire private Telegram saved-job search, selection rechecks and packet preparation. The four new native fixtures are awaiting the combined run. The estimate remains 58% complete based on the last validated baseline. Next, finish the remaining tool and platform source and inventory all test gates. See the [local source report](acceptance/conversation-saved-jobs-local-source-20261118.md).

The private continuity snapshot `1495f77a45289a8500da9e4d95d675510701f66031c39dc5af2c29619311332d` at `2026-11-17T19:49:46.904063+00:00` indexed 104 threads and preserved the six transcripts present locally. The other 98 transcripts remain missing.

Latest LOCAL approved-project conversation source `3ef9dd7f05affc0d8b774819fdfa6ae36bc944ac` projects only current
revision/configuration/ID-bound approvable facts, preserving priority/rank/names/topic/
personal/relevance and pinned evidence with bounded reviewable compaction.192 fictional
legacy reference cases generated;3 native declarations UNRUN. Snapshot helper only;
conversation transport composition is next. See [local project conversation report](acceptance/project-conversation-local-source-20261117.md).
Continue cached search/preferences and native response/replay wiring, then remaining tools/
platforms and final source inventory/contracts/types/fixtures before combined tests/live.
Current source untested/uninstalled;58/42/prior455 held; LOCAL ONLY, no remote publication.
Private continuity snapshotabf49edcda016ca91a02a7cb34e362eccb3b863abd01ea0f67fdc035cdc6df2d
at2026-11-17T15:48:08.595156+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or missing transcript recovery claim.

Latest LOCAL conversation memory source `4ee520509821b39e5aaa8c9a5840fd688b6fcf9b` reuses owner-hash selection key,
eight-entry/ten-job/ten-minute bounds, exact saved expectations, identity/explicit reset
and post-trigger ACK. Expired load proposes fresh context without rewriting the saved row;
malformed/oversized rows refuse overwrite. Four pure+six PG declarations UNRUN. Caller
binding/rollback remains required; no dispatch composed yet. See [local memory report](acceptance/conversation-memory-local-source-20261117.md).
LOCAL ONLY: no pushes/PR/publication/hosted Actions/merge. Continue conversation responses/
operation replay/Telegram binding, remaining tools/platform source, then final inventory/
contracts/types/fixtures and combined gates.58/42/prior455 held; current source untested/
uninstalled, no actual production/provider/browser/message/install operation.
Private continuity snapshotefae55e185b0bd55fdf7558a01898e37b7bf72f516938742e22d33137ac9e3ef
at2026-11-17T15:42:29.101412+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or missing transcript recovery claim.

LOCAL-ONLY checkpoint `0ff4ad43b4fe811eb6e1e9ced62d458f17522ea4`: closed conversation intent contract/compositional parser,
128 fictional legacy oracle cases generated and six new standard declarations UNRUN.
Interpretation proposes previews; unsafe/approval text grants no dispatch. Fixed Unicode/
regex/defaults/public URL/coherence reused; recursion cap64. Parser not yet wired into
conversation memory/API/classifier/response dispatch. See [local intent report](acceptance/conversation-intent-local-source-20261117.md).
NO PUSH/PR/REMOTE PUBLICATION/MERGE under current owner direction; active goal remains local
completion. Continue conversation memory/owner+Telegram services/tools/platform source,
then final inventory/contracts/types/fixtures and combined gates. Current source untested/
uninstalled;58/42/prior455 held. No actual model/provider/browser/production/install.
Private continuity snapshot51aa65edbba401a41e540276b0cfca26bdd66dcb00390172149628aa582c2bfe
at2026-11-17T15:35:18.896942+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or missing transcript recovery claim.

CURRENT OWNER DIRECTION2026-11-17: LOCAL COMPLETION ONLY. Owner said “do not push my code on github for now” and “focus on completing this project on my laptop only locally.” No further pushes, PR updates/publication, hosted Actions or merges until reauthorized. Keep local commits/reports/snapshots and continue the saved completion plan locally. Existing published checkpoints are historical; no remote deletion/rewriting requested. Source phase still applies: finish remaining source/fixtures before combined tests/build/check/live/install. Current uncommitted intent parser/schema/128 generated fictional oracle cases must be preserved and completed. Last validated455 are prior only;58/42 held. Active project goal records local-only delivery and existing operational safeguards.

Latest local-answer v1 source `dfb7afdb071a4ddbb8e604e1af02eb70e33b4972` adopts deterministic resolution in native answer
preparation and adds immutable provenance plus transient max8 rewrite flights in the library.
Only network-only callbacks may be cancelled; production service configures none here.
One waiter cancellation preserves others; last nonce-bound waiter removes/aborts its flight.
Seven standard+two PG declarations UNRUN. General CLI/sentence branches are explicit native
extensions of legacy service refusals, with all flags and Cohere-only questionnaire retained.
See [qualified local v1 report](acceptance/local-answer-v1-source-20261117.md). Continue conversation/tools/platform source,
then final inventory/contracts/types/fixtures and combined/live gates. Current source
untested/uninstalled;58/42/prior455 held; no actual model/provider/production/install.
Private continuity snapshot40839f0fa7bfdcc8de89000b22cc8310a8544e490266f74f5dbc59d65288a4f5
at2026-11-17T15:24:32.867543+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or missing transcript recovery claim.

Latest approved-sentence provider source `065bf87f9dd77917141e06651165380bddbffe72` restores the separate explicit
OLLAMA_GENERATION_AUTHORIZED branch, bounded local chat with permitted variants only,
local reconstruction/coverage and shared metadata/ledger/gate/deadline/context fences.
Six standard+four PG declarations UNRUN. Generic drafting remains distinct; internal
LocalAnswerEngine v1 provenance/coalescing still requires parity integration. See [qualified sentence report](acceptance/sentence-rearranger-source-20261117.md).
Continue internal local engine/conversation/tools/platform source, then final inventory/
contracts/types/fixture alignment and combined gates. Current source untested/uninstalled;
58/42/prior455 held; no actual daemon/provider/production/browser/install operation.
Private continuity snapshot1b38c9b138890ea888012c65461662ac3a7451cd093f6fbfcf0709228060243d
at2026-11-17T15:15:00.343183+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or missing transcript recovery claim.

Latest local fallback source `7c20bb796d9e3b02dd5cd50fd7b5959ea6c5f99f` preserves original primary/local consumed ledgers,
actual selected model/usage, shared transport deadline and unsafe/unknown failure stops.
Cloud deadlines keep per-provider caps and never cancel ledger COMMITs. Questionnaire
forces fallback off. MCP source arrays now use object structured results. Four standard+
six PG declarations UNRUN; existing framed assertion aligned. See [qualified fallback report](acceptance/local-fallback-source-20261117.md).
Continue sentence rearranger/local conversation/tools/platform source, then final API/
contracts/types/fixture alignment and combined gates. Current source untested/uninstalled;
58/42/prior455 held; no actual provider/daemon/production/browser/install operation.
Private continuity snapshotb90d0761e190875ba92f6385405e8aa31dba1367015f39cd23947cbc9263f56b
at2026-11-17T15:08:16.307982+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or missing transcript recovery claim.

Latest explicit CLI writer source `9608a0ab85deed11b7bac56e3d86cd69170d86f0` reuses AGY monthly counts/shared provider
gate and answer grounding/stamps. Exact private profiles, trusted workspace/no-overage
settings, fixed argv/selected environment, pre-prompt empty-tool init, bounded frames/
pipes/deadline and owned-group cleanup are source only. Twelve standard+five PG declarations
UNRUN. Literal legacy profile frozen; no-import exporter check deferred. See [qualified CLI report](acceptance/cli-answer-writer-source-20261117.md).
Continue local fallback/rearranger/conversation, remaining tools/platform source, then
final inventory/contracts/types/fixture alignment and combined tests. Current code untested/
uninstalled;58/42/prior455 held. No installed CLI/model/provider/private-owner-policy/live operation.
Private continuity snapshot03211d39d7e8050e83d5ea94dd5a2aac9cbdc676cda9e187c640679f6b522047
at2026-11-17T14:59:44.964385+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or missing transcript recovery claim.

Latest MCP discovery composition source `75b4f9ebad7cf6ea5ae4feb8303c5e1b64464786` adds eight default saved-read/preview,
six optional original discovery/read/local-completion and two separately optional metadata
tools through the existing owner API. Direct-call default-off flags, strict consent/
UUIDs, bounded deadlines and private error context preserve original reservation/recovery
rules. Nine standard+four PG/framed declarations UNRUN. See [qualified MCP report](acceptance/mcp-discovery-composition-source-20261117.md).
Continue native provider/CLI/local conversation, remaining tool/platform source, then
final inventory/contracts/types/fixture alignment and combined tests. Current code is
untested/uninstalled;58/42/prior455 held. No actual MCP/provider/browser/production/install.
Private continuity snapshotd4b48e80483409db786c8f05071821b13bfd26ce7d680ffe5dffda46d1873ced
at2026-11-17T14:44:24.210142+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest durable startup dashboard source `3833f23eb112a8ddc081bb442bf3512eea049529` isolates job-led controls,
persists UUID/source before PUT, uses GET-only reload and empty local completion,
locks unresolved criteria and releases only reviewed terminal pointers. Native source/
paid preview/consent gates and guarded original child handoff are in source. Ten helper+
four component+one browser declarations UNRUN. See [qualified startup dashboard report](acceptance/startup-durable-dashboard-source-20261117.md).
Continue remaining agreed native provider/tool/conversation/runtime/platform source,
then final inventory/OpenAPI/types/fixture alignment and combined tests. Earlier
phase2 UI fixtures still expect legacy public POST and need UUID alignment at that
source gate. No current tests/build/check/native live/install or estimate increase;
58/42/prior455 held; no actual provider/recovery/production/browser operations.
Private continuity snapshot6c46d85fb4b4a9cbc80bd90c2c725281b1a3368ed8bfd8e08112049e43027c00
at2026-11-17T14:31:39.950317+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest durable startup owner source `dcbaadf48ea8271377e653f67a4aac62d256b5f7` adds UUID PUT and empty local
completion POST alongside saved GET. Body/source/method checks precede the existing
request slot; local completion cannot dispatch providers and unknown child stays
saved. Preview separates effective provider query/company filters and actual paid
query caps/readiness. HTTP policy copies generated. One standard+five PG/HTTP+one
gateway declarations UNRUN. See [qualified startup UUID report](acceptance/startup-uuid-owner-source-20261117.md).
Continue startup durable dashboard/consent/recovery and remaining agreed runtime/
provider/tool/platform source before combined tests. Full API inventory/types pending.
No current tests/build/check/native live/install or estimate increase;58/42/prior455
held; no actual provider/recovery/production/browser operations.
Private continuity snapshot7941f92ae7633dcd9dad5e4d2e99a4a1b6e0d3b3501d95de55c6883073255d97
at2026-11-17T14:25:57.389096+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest startup paid-child source `8a465ecce61e4fe09b0932040a64a96ddf009e31` composes Wellfound/Work at a Startup
through typed original paid job children, admitting parent/child/intent/reservation
atomically. Nested admission ACKs and final exact monthly snapshot accompany existing
profile/configuration/frozen company attribution/catalog checks. Replay never acquires
another provider grant and completed reads need no current token/profile. One standard+
eight PG/loopback declarations UNRUN. See [qualified startup paid-child report](acceptance/startup-paid-job-led-source-20261117.md).
Continue startup UUID PUT/local completion/durable dashboard and remaining agreed
runtime/provider/tool/platform source before combined gates. No current tests/build/
check/native live/install or percentage increase;58/42/prior455 held. No actual
provider/recovery/production/browser operations.
Private continuity snapshotacf85c442029c7d9015d575582e1c9ed543c0238e56a23362201209af1edc78e
at2026-11-17T14:22:22.824556+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest durable acknowledged-read dashboard source `bcc1b182e2d32810dfd12d637b02e6030e6a3742` retains opaque
parent/read UUIDs under original Web Lock, requires separate new-read consent and
uses GET-only saved inspection/restoration. Complete pages finish locally, then the
original job result; reviewed expired reads may prepare another UUID without dispatch.
Unknown starts/reads and corrupt accounting preserve pointers. Ten helper+two component+
one browser declarations are UNRUN. See [qualified read-dashboard report](acceptance/apify-acknowledged-read-dashboard-source-20261117.md).
Continue remaining startup job-led/paid orchestration and durable UI, then remaining
agreed runtime/provider/tool/platform source before combined gates. No current tests/
build/check/native live/install or percentage increase;58/42 and prior455 held. No
actual provider/recovery/production/browser operations.
Private continuity snapshot96b4d108ae0844c580989a3e7adb219d6ae03327bf05dc7ffb9eb14f31c3f8ec
at2026-11-17T14:17:20.608594+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest explicit owner read-resource source `f67fc0233f86c8725f07eb9df7ec2655827e68eb` exposes distinct parent/
read UUID GET/PUT and empty local-complete POST. Requires retained native paid parent;
GET stays saved-only, PUT can consume only bounded GET authority and POST only combines
saved pages. Paid parent usage exposes original read count/last UUID/next time. Shared
permit/connection and auth/CSRF remain. HTTP policy copies generated; one standard,
six PG/HTTP and two gateway declarations are UNRUN.
See [qualified owner read-resource report](acceptance/apify-acknowledged-read-owner-source-20261117.md).
Continue durable dashboard read UUID/consent/recovery, then remaining agreed startup/
runtime/provider/tool/platform source before combined gates. Full API inventory/types
still pending. No current tests/build/check/native live/install or estimate increase;
58/42 and prior455 held; no actual provider/recovery/production/browser operations.
Private continuity snapshotafca959b9d8b5dadf16fbfec8f953a0fca762025740a2924ebec05a444125485
at2026-11-17T13:20:37.477015+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest GET-only acknowledged-read lifecycle source `ed77d2e3b74a207c1aba83b1aeb5cf56435f9cec` consumes separate
read claims, admits4GET/45seconds with durable checkpoints, preserves original paid
start/HTTP evidence and CASes new selected run status. All selected pages/hash/time
survive failed finalization; local-only finish reconstructs the full finding without
new provider reads/time refresh and blocks unnecessary fresh rounds. Shared dataset
selection and monotonic cooldown are in source. One standard+twelve PG declarations
are UNRUN. See [qualified read transport report](acceptance/apify-acknowledged-read-transport-source-20261117.md).
Continue explicit keyed owner recovery GET/PUT/local-complete and durable dashboard
read pointer, then remaining agreed startup/runtime/provider/tool/platform source
before combined gates. Ordinary GET/local-complete cannot dispatch recovery yet.
No current tests/build/check/native live/install or percentage increase;58/42 and
prior455 held. No actual recovery/paid/production/browser operations.
Private continuity snapshot003bf3cba32c0ca053733c69f5092868045ff8b848642d997416bc6429fd3d2f
at2026-11-17T13:13:28.387663+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest separate acknowledged-read admission source `86831f52e3adedf60630160148229e3cfb17dbe9` binds read UUID,
original journal lifetime allowance (3 rounds),4GET/45seconds,5-minute spacing and exact
reservation/month/context/cooldown ACKs. Replay cannot renew; deleted prior read records
cannot reset admissions. Status observation needs no current profile, while local
intake still requires its original pin. Eight PG/loopback declarations are UNRUN.
See [qualified read-admission report](acceptance/apify-acknowledged-read-admission-source-20261117.md).
Continue GET-only recovery operation checkpoints/transport, original finding CAS,
explicit owner recovery and durable UI, then remaining agreed source before combined
gates. No current tests/build/check/native live/install or estimate increase;58/42
and prior455 held. No actual recovery/paid/production/browser operations.
Private continuity snapshot1bad4b8cbd8ba0d8eab406f79b2189a681a81e7ecfda576c5e6661f229258687
at2026-11-17T12:50:00.814163+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest acknowledged read-context source `75132e923e22a06788ea8ec59484abb1ebd80680` retains closed original
run options, requires option/identity stability on later status, restores selected
actor/run evidence and offers only fixed GET targets. Original75-second expiry,
24-hour window and fresh successful status gate precede build/dataset targets. Six
standard declarations are UNRUN; this pure context grants no dispatch. Durable read
admission/transport/owner controls are still pending.
See [qualified acknowledged-read context report](acceptance/apify-acknowledged-read-context-source-20261117.md).
Continue separate bounded read admissions/checkpoints (3 rounds,4GET/45seconds,
5-minute spacing), original finding CAS and explicit owner recovery, then remaining
agreed startup/runtime/provider/tool/platform source before combined gates. No current
tests/build/check/native live/install or percentage increase;58/42 and prior455 held.
Private continuity snapshot88f48b45aa6b4b15e2a2edf4b8ad8dde98fa3bac14484cf751f627bfbc0f9f02
at2026-11-17T12:40:53.360117+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest paid dashboard source `ae755950d35e4f1026f2180a9863c331265dc590` adds saved-ready source selection,
separate paid/run consent, original preview cost/cap/blocker, retained full-cap view
and native accounting validation. Criteria edits clear consent; reload/unknown-start
pointers persist and retained findings complete locally without another PUT. Four
component+three helper+one browser declaration are UNRUN; no new browser/screenshot.
See [qualified paid dashboard report](acceptance/paid-discovery-dashboard-source-20261117.md).
Continue bounded acknowledged-run read recovery, startup/UI and remaining agreed
runtime/provider/tool/platform source before combined tests. No current tests/build/
check/native live/install or percentage increase;58/42 and prior455 held. No actual
production/paid/browser operations.
Private continuity snapshotdcf334582ca2cc3d3e4df1ae5b27e30379333d5c22b7db2225207a43dff2e730
at2026-11-17T12:33:01.705127+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest reviewed paid owner HTTP source `c9ab52784201505cf755805ea91bae4cd876cb2d` (implementation3c233ac) extends
existing authenticated discovery routes with separate paid original-key namespace,
saved native-kind reads/local completion, preview cost/cap/blocker and native registry
readiness. Legacy availability stays separate; invalid optional paid settings do not
hide public or saved terminal routes. One standard+seven PG/HTTP declarations and3
existing fixture updates are UNRUN. See [qualified paid HTTP report](acceptance/apify-owner-http-source-20261117.md).
Continue explicit paid dashboard consent/accounting, bounded acknowledged-run recovery,
startup/UI and remaining agreed source before combined gates. Full native inventory/
types still pending. No current tests/build/check/native live/install or estimate
increase;58/42 and prior455 held; no production/paid/browser operations.
Private continuity snapshot4f157e591d2e303d6b444f75a4fb2fa57a17419f66ca73e8949e6a9aa77ae196
at2026-11-17T12:28:12.143034+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest original paid owner-run/result source `3734a202436edcbcae8e44ab59efc9030bcb93c0` couples actual parent,
original paid child intent and full-cap reservation, with final child/month/profile/
plan/cooldown ACKs after parent triggers. Local terminal completion shares guarded
intake, bounded matcher/history suppression and final ranking/input ACKs. Replays never
renew remote authority; completed reads need no current token/profile. Sixteen new
PG/loopback declarations UNRUN; host/dashboard and acknowledged-run read recovery
remain. See [qualified owner paid-run report](acceptance/apify-owner-run-results-source-20261117.md).
Continue owner paid routes/controls, bounded read recovery, startup/UI and remaining
agreed source before combined tests. No current tests/build/check/native live/install
or estimate increase;58/42 and prior455 held. No production/paid/browser operations.
Private continuity snapshot9d0e203b00d5628300e0b5d3a93d0dfb3ac690e4e5591d886663bd412cb993e3
at2026-11-17T12:21:52.728728+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest retained Apify intake source `2d8a987fece0257006e250b7981ae8ef1b35ce2d` (batch implementation5498387) shares
history-preserving job/company/observation writes and closed immutable local receipts.
Fresh writes bind original run/finding/reservation/configuration/profile/TTL; final ACKs
check all rows and exact monthly numeric totals after receipt triggers. Saved replay
has no current credential/context or remote authority; source claims do not promote
curated facts. Eighteen new PG/loopback declarations are UNRUN; parent/owner/UI and
acknowledged-run read recovery follow. See [qualified paid intake report](acceptance/apify-local-job-intake-source-20261117.md).
Continue paid original owner-run/ranking/host integration and remaining agreed source
before combined tests. No current tests/build/check/native live/install or percentage
increase;58/42 and previous455 held; no production/paid/browser operations.
Private continuity snapshot90aa8c9d706586ddbf9d4cde10649071de0be01f2885a6eca30a4596b6135a54
at2026-11-17T12:13:27.863155+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

# Project resume record

Read this file, `AGENTS.md`, the ownership registry and the current branch diff before
continuing after an account switch. Source of truth: this repository and
`karanagg166/automated-apply`; private state stays in ignored `.local/` and the approved
online PostgreSQL database. A missing Codex sidebar entry does not establish deletion.

## Current work

Latest original Apify transport source `f729b4fdf6dee414ef0cd4b5e85dc8ca3a1427e1` checkpoints every fixed
operation, selected run/reservation attachment, bounded polling/build/dataset findings
and qualified original abort before separate local intake. Replays cannot reconstruct
sessions/start again; uncertain counters are minimum observed values and full caps stay
retained. One standard+eleven PG/HTTP declarations are UNRUN.
See [qualified original Apify transport report](acceptance/apify-original-transport-source-20261117.md).
Continue guarded paid finding-to-job local SQL/receipt/parent integration, owner routes/
dashboard, bounded known-run recovery and remaining source before combined gates.
No current tests/build/check/provider/production/install or estimate increase;58/42/
prior455 held. New native host uninstalled; paid local intake explicitly incomplete.
Private continuity snapshot 101d07e529c66a888dd0a74ec954dbf637757a62ee7b10bcacdbfaa6a2bd00dd
at2026-11-17T12:00:31.789635+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest original Apify USD source `0addb65d466628ee3338e2433cf0957791461fc2` atomically reserves the full
exact cap/monthly total and original request/profile/configuration/invocation/deadline.
Independent ACKs include exact numeric totals and global cooldown after journal triggers.
Saved replay cannot renew authority/refund and stays readable without current config.
Two standard+eleven PG declarations are UNRUN; paid transport/result/host integration
still follows. See [qualified original reservation report](acceptance/apify-original-reservation-source-20261117.md).
Continue fixed transport/durable run/status/build/dataset checkpoints and local results,
remaining agreed source before combined gates. No current tests/build/check/provider/
production/install or estimate increase;58/42/prior455 held. GitHub CLI publication
fallback is used while connected GitHub tools are unavailable.
Private continuity snapshot 5cd4176eb7fea341e58165e13123bb3bc6a9da7f3ee9b5aa57ea1b0b34ada980
at2026-11-17T11:47:41.949266+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest pure paid-discovery source `639e5484060092d4e4279ae44f4d5d688124a674` ports selected portal jobs,
exact six-decimal USD caps/conservative estimates, fixed official targets and closed
original actor/run/build evidence. Pinned opaque build/schema/input review precedes
start construction; personal founder/profile URLs and private metadata are excluded.
Eight standard declarations(49 actual/decimal comparisons plus guards) are UNRUN.
See [qualified Apify job plan report](acceptance/apify-job-plans-source-20261117.md).
Continue durable exact USD reservation/original intent, fixed transport/checkpoints,
dataset/result intake, startup/dashboard recovery and remaining agreed source before
combined gates. No current tests/build/check/provider/production/install or estimate
increase;58/42/prior455 held. Pure plans grant no authority; paid host remains unported.
Private continuity snapshot 51c5fa0b9556722981a39ada6b0dcecf71db2e6fac779e60cf349105fa80ab8a
at2026-11-17T11:22:33.745132+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest startup job-led source `586690b648a296fb8c759e1427083f25237f2872` admits real parent/original job
child atomically, rechecks nested scope/window/profile after parent triggers and keeps
lost invocations nonrenewable. Local company results bind original job-to-company IDs,
original filters/profile/context and a second selected-catalog ACK. Failed startup
finalization preserves completed child data for local-only recovery. One standard and
ten PG declarations plus2 existing fixture updates are UNRUN.
See [qualified startup job-led report](acceptance/startup-job-led-source-20261117.md).
Continue reviewed Apify execution/budget/dataset lifecycle, startup/dashboard recovery
and remaining agreed runtime/provider/tool/platform source before combined gates.
No current tests/build/check/native live/install or estimate increase;58/42/prior455 held.
Private continuity snapshot 409ab6d517f29d752d2f74cc7e7d243d3a71826b7308bea13b4934a1b6ec9f5f
at2026-11-17T11:03:20.359526+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest owner API/dashboard source `39be30083d6840315bbeb3519c43731ae542161e` connects public preview,
stable keyed POST and UUID PUT/GET plus local-only completion through the existing
transient slot. Legacy GETs are qualified saved history without native adoption.
Dashboard retains UUID/source across reload/response loss and uses Web Locks; mount
reads GET only. Twenty-two new declarations(3 standard/7 PG/12 UI), plus9 existing UI
updates are UNRUN. HTTP policy copies generated; full native API inventory/types remain
final-gate work. See [qualified owner dashboard report](acceptance/public-owner-dashboard-source-20261117.md).
Continue startup job-led orchestration, reviewed Apify execution and remaining agreed
source before combined gates. No current tests/build/check/native live/install or
estimate increase;58/42 and prior455 held. New host remains uninstalled.
Private continuity snapshot fc89296d5b5ca4ccb3bd8b7214e15155f08a90a0e66cb01bcb98f749d0953379
at2026-11-17T10:51:43.294401+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest owner result source `35a1a302e06cd16bda88e2110d534f7e2b5dfeca` composes original acquisition and
atomic local employer/job/observation/receipt plus terminal parent/ranking completion.
Uses existing native matcher and bounded reviewed local history; confirmed prior
applications are omitted from rankings without rewriting decisions. Completed replay
returns original result; pending parents expose saved local receipts honestly. Eleven
new PG declarations and one earlier assertion update are UNRUN.
See [qualified owner results report](acceptance/public-owner-results-source-20261117.md).
Continue owner discovery API/dashboard recovery, startup child orchestration, reviewed
Apify execution and remaining agreed source before combined gates. No current tests/
build/check/native live/install or estimate increase;58/42 and prior455 held.
Private continuity snapshot a7fc2d7ac445c064caf57489aa6f74eb4c6636d79ccc5ab61c9560c2c08c7176
at2026-11-17T10:37:55.610440+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest local SQL intake source `92c43479d35d3b449193e78dd26f2a1b49bf4865` validates original finding/scope,
current configuration/profile and24-hour TTL before owner-fenced atomic employer/job/
source-observation/immutable receipt writes. Complete bounded legacy URL identity,
full-row history preservation, actual PG type coercion and final post-trigger ACKs are
in source. Fifteen PG/loopback declarations are UNRUN. Parent finalization/rankings are
still separate. See [qualified local SQL intake report](acceptance/public-job-sql-intake-source-20261117.md).
Continue parent result/ranking integration, startup orchestration/owner dashboard,
reviewed Apify execution and remaining agreed source before combined gates. No current
tests/build/check/native live/install or estimate increase;58/42 and prior455 held.
Private continuity snapshot c008763b7f6ba30494951b912c2d4eabaf8b3a632895146b149b1f4ef7a855b0
at2026-11-17T10:28:30.830175+00:00 preserves104 indexed/6 available/98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest original owner-run admission source `da0ca27ce351e7f35fe5e22bfa032d78dd594085` couples the actual
run row, private profile/query scope and original child/source window in one owner-first
transaction with final independent ACKs. Saved reads/replays never renew authority;
original acquisition retains findings while SQL local intake remains explicitly pending.
Shorter configured deadlines cap child lifetime. Twelve PG declarations are UNRUN.
See [qualified owner-run admission report](acceptance/public-owner-run-admission-source-20261117.md).
Continue atomic SQL job/company/observation/receipt intake, parent local completion,
startup/owner dashboard orchestration, reviewed Apify execution and remaining source
before combined gates. No current tests/build/check/native live/install or estimate
increase; 58/42 and prior455 held. Full host uninstalled; domain not host-connected.
Private continuity snapshot 797ace215fc088ca0c6e15c123cb1aa0ad379beb1458599e34c5745b733ee70a
at 2026-11-17T10:16:53.933988+00:00 preserves104 indexed /6 available /98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest owner-run scope source `1e8734c4e213d9d2feaaa53d8dcb3c92a5bd946b` freezes
actual RunRequest/defaults/hash, explicit versus effective query expansion and private
profile UUID/version/content pin. Public scope refuses manual/unsupported records and
copies no raw candidate facts into plans. Four standard declarations (72 actual
comparisons plus pin/size/privacy guards) are UNRUN.
See [qualified owner-run scope report](acceptance/public-owner-run-scope-source-20261117.md).
Continue parent/child original scope admission, atomic SQL job/company/observation/
receipt intake with current context/TTL/history preservation, startup orchestration,
owner dashboard, reviewed Apify execution and remaining agreed source before combined
gates. No current tests/build/check/native live/install or estimate increase; 58/42
and prior455 held. Full host uninstalled; new domain source is not host connected.
Private continuity snapshot f0c7456b621a084b5418e52ead4ab6437f18e53d718987fe96651be2c709a1c8
at 2026-11-17T09:50:07.192024+00:00 preserves104 indexed /6 available /98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest local intake rules source `a1da12b32e5bb7131782baed958c84fc46b20f4f`
ports actual source/board/ID/URL keys, conservative content identity and explicit versus
profile-expanded discovery filtering. Unknown evidence stays visible without becoming
Apply eligibility; title similarity never merges jobs. Three standard declarations
(84 actual comparisons plus untyped provenance refusal) are UNRUN.
See [qualified intake rules report](acceptance/public-job-intake-rules-source-20261117.md).
Continue atomic SQL job/company/source-observation/receipt intake with current context,
TTL and bounded legacy identity checks, then startup orchestration/owner dashboard,
reviewed Apify execution and remaining agreed source before combined gates. No current
tests/build/check/native live/install or estimate increase; 58/42 and prior455 held.
Private continuity snapshot ed400893182191cd7139eaf1d9c8235372ce8d079edea1fa02ccc82baf079591
at 2026-11-17T09:38:35.868555+00:00 preserves104 indexed /6 available /98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest public transport/finding source `bf03a79cec97f33f9850f4210bafef2993094623`
consumes original grants through fixed no-proxy/cookie/auth/retry/redirect GETs and
bounded complete/partial traversal. Conflicting identities are removed, incomplete
cursors suppressed and final provisional cursors cleared. Selected findings/terminal
journal and monotonic rate windows commit before separate local ingestion. One standard
and twelve PG/loopback declarations are UNRUN. See [qualified transport report](acceptance/public-job-transport-source-20261117.md).
Continue guarded job/company/startup ingestion, owner discovery/dashboard recovery,
startup job-led orchestration, reviewed Apify execution and remaining agreed full source
before combined gates. No current tests/build/check/native live/install or estimate
increase; 58/42 and prior455 held. Domain controller has no owner-host route yet.
Private continuity snapshot 937a91c46aac8684a4c1213487ade36fca3ed98b9826f8c25bc52b99f267c831
at 2026-11-17T09:28:09.031178+00:00 preserves104 indexed /6 available /98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest public batch admission source `8cd8e4e707f89804fff60a132b9e09a42ccc40bd`
commits original UUID/query/source/context/invocation/deadline and shared provider
windows atomically under the owner fence, independently ACKs both and never reconstructs
grants on read/replay. Expired lost work remains unknown; missing current configuration
does not hide saved history. Eight PG declarations are UNRUN.
See [qualified admission report](acceptance/public-job-admission-source-20261117.md).
Continue fixed original-grant transport/pagination/dedup/retained findings, separate
startup/job ingestion, reviewed Apify execution and remaining agreed full source before
combined gates. No current tests/build/check/native live/install or estimate increase;
58/42 and prior455 held. Host uninstalled; unused transport fields await the next slice.
Private continuity snapshot f081a1dbf11810de39a5993c230b5d0a378615cb7e727dd1df87e1adea131a88
at 2026-11-17T09:01:51.553527+00:00 preserves104 indexed /6 available /98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest public request-plan source `5feb33e9e2b89620e6013b553945d45620587b42`
binds seven fixed origins, reviewed sorted board/employer snapshots, region/context and
bounded HN/SmartRecruiters continuation IDs. Three standard declarations are UNRUN.
See [qualified target plan report](acceptance/public-job-targets-source-20261117.md).
One official Arbeitnow public JSON was read through the web research tool; no native
admission, fixture/runtime run, ingestion or current provider acceptance is inferred.
Continue durable source-window/original invocation grants, fixed public HTTP/pagination/
retained findings/startup ingestion, reviewed Apify execution and remaining source before
combined gates. No current tests/build/check/install or estimate increase;58/42/prior455 held.
Private continuity snapshot 8b3b345cc4183401eb2a505469d1e8b3d485c0fa21640ccfc3580a64ef9a3ec5
at2026-11-17T08:56:38.182819+00:00 preserves104 indexed /6 available /98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest seven-provider record source `037a00698bb561788ed471789e3680c38091e14c`
adds pure Greenhouse/Lever/Ashby/SmartRecruiters/Remotive/Arbeitnow/HN parsers with
salary/workplace/date/hosted identity rules and bounded selected provenance. Arbitrary
vendor/source_fields are omitted; malformed IDs/structures fail conservatively.
Five standard declarations (216 actual comparisons plus bounds) are UNRUN.
See [qualified record parser report](acceptance/public-job-records-source-20261117.md).
Continue fixed-host public transport/pagination/pacing and startup job-led ingestion,
reviewed Apify execution and remaining agreed source before combined gates. No current
tests/build/check/live/install or estimate increase; 58/42 and prior455 held. Host uninstalled.
Private continuity snapshot 2bc82b0b8b48f01e7b197c3b36b88263b1528342d3c919105a1a79d3204f7af4
at 2026-11-17T08:49:56.809412+00:00 preserves104 indexed /6 available /98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest public job/query contract source `e4da98431b9471ef0e95b586589f1e37df6eaf74`
freezes actual DTOs and ports pure defaults/coercion, strict experience/salary evidence,
UTC dates, ATS canonical identity, unknown-company/remote rules and payload limits.
Three standard declarations (70 actual job +30 query comparisons plus bounds) are UNRUN.
See [qualified public job contract report](acceptance/public-job-contracts-source-20261117.md).
Continue seven provider normalizers/fixed GETs/pacing/startup orchestration, reviewed
Apify execution and remaining agreed full source before combined gates. No current
tests/build/check/live/install or estimate increase; 58/42 and prior 455 held.
Private continuity snapshot 0620df52ebdf3d4198d6971759da0acbde01f4228e8c3c54968b19d36ea6db2c
at 2026-11-17T08:35:36.360424+00:00 preserves 104 indexed /6 available /98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest owner Apify metadata source `27050a09624bbf4a7d8f3a7b3177a3327a9cd842` wires
the original three owner routes through the existing transient permit. Owner-first
durable ten-second pacing precedes GETs; cache completion rejects superseded claims.
Native credential/content-bound cache and legacy projection keep saved status read-only,
private and qualified. Two standard and eight PG/HTTP declarations are UNRUN.
See [qualified owner metadata report](acceptance/apify-owner-metadata-source-20261117.md).
Continue reviewed actor execution lifecycle, public job providers/startup orchestration
and remaining agreed full source before combined gates. No current tests/build/check/
live/install or estimate increase; 58/42 and prior 455 held. Full host uninstalled.
Private continuity snapshot 580c633335a7682b651ee5da51b649ef3ee9416d02806099dfbee2c795518f29
at 2026-11-17T08:28:54.727225+00:00 preserves 104 indexed /6 available /98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest Apify metadata source `e209b23c9f53bbaed10ec9df9a99646abb758af8` adds fixed
GET-only public actor/store and authenticated account inspection, bounded streaming/time,
no retry/redirect/proxy, actual frozen DTOs and inert local schema extraction/digests.
Closed account projection excludes unknown/daily/service blobs and rejects changed cycles.
Nine standard declarations (five sync/four async; 20 extractor +8 inspect comparisons)
are UNRUN. See [qualified metadata report](acceptance/apify-metadata-source-20261117.md).
Continue owner inspection pacing/cache/routes, startup provider orchestration and remaining
agreed full source before combined gates. No current tests/build/check/live/install or
estimate increase; 58/42 and prior 455 held. Full host remains uninstalled.
Private continuity snapshot 2e8e1b1bb128814c0131226a44453908f2ae496a1b62786903719ba4da0b0ec8
at 2026-11-17T08:19:22.346398+00:00 preserves 104 indexed /6 available /98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest owner/dashboard source `4b2c67632d36171e4c9a2d930605fc216a8cf8ca` connects
native UUID research PUT/GET/status, unkeyed 428, original company binding, shared transient
budget and exact BFF policy. Dashboard Web Locks/UUID-only pointers preserve response-loss
recovery; new paid work needs fresh explicit approval if no durable admission exists.
Only retained findings can retry local completion. New searches need reviewed terminal
GET and exact pointer comparison. UI qualifies held/unknown results without raw JSON.
One Rust standard, six PG/HTTP, fourteen frontend unit and one browser declarations are
UNRUN. See [qualified owner/dashboard report](acceptance/people-research-owner-dashboard-source-20261117.md).
Continue startup job-led/provider orchestration, Apify runtime and remaining dashboard/
registry/provider/CLI/conversation/eight-platform full source before combined gates.
No current tests/build/check/live/install or estimate increase; 58/42 and prior 455 held.
Full host uninstalled; no actual provider/budget operation or owner browser action occurred.
Private continuity snapshot 59d8b1a6bf8ad734d06f19ad93a4c816c96c733326b1dc7581f1b1776f37b767
at 2026-11-17T00:36:43Z preserves 104 indexed / 6 available / 98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest paid local completion source `9977246db53abf0795650b22e6fff3d4b9f1a282`
checks original input/current configuration/rights/company/finding age before a second
atomic local transaction. People/contact changes, local receipt and paid final journal
commit together; failed local work retains the earlier finding without another POST.
Explicit public_search provenance stays unconfirmed and observation time stays original.
Changed context is held; completed GETs are selected/read-only. Twelve PG/loopback
declarations are UNRUN. See [qualified local completion report](acceptance/people-search-completion-source-20261117.md).
Continue the native UUID owner endpoint/dashboard recovery, startup provider orchestration
and remaining agreed full source before combined gates. No current tests/build/check/live/
install or estimate increase; 58/42 and prior 455 held. Full host uninstalled; owner API
research endpoints are not yet wired, and no actual provider/budget operation occurred.
Private continuity snapshot 39a3fffeaf3bb04fb1e389bb3f84fb89750839dece496eae1510bfcf6e855856
at 2026-11-17T00:25:06Z preserves 104 indexed / 6 available / 98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest transport/finding source `5a43ac52f64be2fc667c6b1e0d3c413c92f603bf` consumes
original search grants through a fixed sensitive-header, no-proxy/retry/redirect POST,
15-second deadline and 1-MiB stream bound. Selected findings and exact original terminal
budget evidence commit before local persistence. GET/replay cannot renew authority;
response loss remains unknown and rate responses set cooldown. One standard and nine
PG/loopback declarations are UNRUN. See [qualified search transport report](acceptance/people-search-transport-source-20261117.md).
Continue paid finding-to-contact completion with current input/settings/company guards,
native UUID owner endpoint/dashboard recovery and remaining agreed full source before
combined gates. Paid controller results currently explicitly say not_imported; host routes
are not yet wired. No current tests/build/check/live/install or estimate increase; 58/42
and prior 455 held. Full host uninstalled; no actual provider/budget operation occurred.
Private continuity snapshot aed8565adcb1e0b9ac4af60989308444ee24c60d845525855766aa3c1222ad0e
at 2026-11-17T00:14:30Z preserves 104 indexed / 6 available / 98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest paid research admission source `b8b83b7577271a572408cfdcb213cc20efedf215`
adds saved credential/rights/domain/paid gates, original UUID intents/30-second opaque
grants and exact local search-request reservations. Replays/GET cannot rebuild grants;
expired unresolved reads stay unknown. Manual/paid mode changes conflict. Shared ledger
uses a separate serper/people_ namespace and post-trigger acknowledgments, never a
provider credit/dollar claim. Two standard and nine PG declarations are UNRUN.
See [qualified original research admission report](acceptance/people-search-admission-source-20261117.md).
Continue fixed Serper transport, retained parsed findings, conservative local completion,
native UUID owner endpoint/dashboard recovery and remaining agreed full source before
combined gates. No current tests/build/check/live/install or estimate increase; 58/42 and
prior 455 held. Full host uninstalled; no actual provider/budget operation occurred.

Latest manual people source `4418abc52f8ef78d4387c87bc3898b4a64195d9e` adds atomic
UUID receipts/public-person/contact ingestion, exact replay, domain/rights/identity
guards and retained privacy. Existing confirmed rows, suppression/corrections/review
conflicts remain protected. Shared identity writes now reread after triggers. The saved
company reader's earlier incorrect `discovered_people` table reference is corrected to
actual `discovered_company_people`, whose fixture now uses the migration definition.
Fourteen PG declarations are UNRUN. See [qualified manual people report](acceptance/people-manual-ingestion-source-20261117.md).
Continue original paid research admissions/retained findings/owner controller, durable
dashboard recovery and remaining agreed full source before combined gates. No current
tests/build/check/live/install or estimate increase; 58/42 and prior 455 held. Full host
uninstalled; this manual domain service has not yet been wired to its owner API.
Private continuity snapshot 49edfdf7a380ea1b0445557348c90a03d5f4dade07b263145a1d0158cc01242b
at 2026-11-16T23:53:52Z preserves 104 indexed / 6 available / 98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest public research rules source `3834099421594938700bd132812f29b4df92579c`
ports actual search-index queries, fixed role aliases, Unicode/name/word rules, exact
official company attribution and canonical URL/name ambiguity handling. Raw snippets
are excluded; generated official results remain human_confirmed=false. Two standard
declarations (60 actual adapter/query +8 ambiguity cases, plus bounds) are UNRUN.
See [qualified professional research rules report](acceptance/public-research-rules-source-20261117.md).
Continue durable original research admission/retained findings/contact ingestion and
remaining agreed full source before combined gates. No current tests/build/check/live/
install or estimate increase; 58/42 and prior 455 held. Full Rust host uninstalled.

Latest startup owner/registry source `e97c210dc19b528ca030666d5950b09ddcf9498e`
connects saved source metadata, read-only snapshot preview, original manual POST and
retained run GET through the existing transient permit. Private deployment fields stay
private; saved prerequisites grant neither live verification nor dispatch authority.
Unported provider orchestration returns explicit 501 without admission. Exact original
hashes survive host normalization; manual requests require stable keys. Three standard
and eight PG/HTTP declarations are UNRUN. See [qualified owner registry report](acceptance/startup-owner-registry-source-20261117.md).
Continue durable public research/provider orchestration, startup dashboard recovery and
remaining agreed full source before combined gates. No current tests/build/check/live/
install or estimate increase; 58/42 and prior 455 held. Full Rust host uninstalled.
Private continuity snapshot d87718c68473ea7db3aa61b37c4b393347aaf6d404a21c1639890ed898e30dda
at 2026-11-16T23:39:10Z preserves 104 indexed / 6 available / 98 missing transcripts.
No account/session ownership rewrite or unavailable transcript recovery claim.

Latest Apify configuration source `a26d8006d85a70a6a6e85ad876ee4c4fa1dd1149` freezes
the actual actor DTO, pinned build, bounded fixed input mapping and collection guards.
Saved review/cost preflight grants neither live verification nor dispatch authority.
The startup score default now retains exact omitted/explicit numeric serialization.
Three standard declarations (100 actual comparison cases plus bounds) are UNRUN.
See [qualified actor configuration report](acceptance/apify-actor-configuration-source-20261117.md).
Continue native source registry/startup owner endpoints, durable public research/providers
and remaining agreed full source before combined gates. No current tests/build/check/live/
install or estimate increase; 58/42 and prior 455 remain held. Full Rust host uninstalled.

Latest manual startup run sourcea3c977d retains original discovery_runs requests/hashes,
opaque180-second invocation, atomic permission-confirmed company evidence/scoped saved
ranking/finalization and no-replay retained reads. Failed completion rolls back data while
preserving the claim; expired GETs qualify recovery without writes. One standard declaration
(16 actual claim hash cases) +10 PG declarations are UNRUN. See [qualified manual run report](acceptance/startup-manual-runs-source-20261117.md).
Continue source registry/owner startup endpoints/provider status, durable public research and
remaining dashboard/registry/provider/CLI/conversation/eight-platform full source before
combined gates. No current tests/build/check/live/install or estimate increase;58/42/prior455
held. Manual runs remain a domain service awaiting registry/host integration; no provider
or operational completion claim; full Rust host uninstalled.

Latest company ingestion source987d64b preserves exact source/domain/URL identity and actual
content hashes, conservative canonical company facts, missing-domain review guards and
immutable observation replay with complete ACK/rollback. One standard declaration (20
actual identity/hash cases) +10 PG declarations are UNRUN. See [qualified ingestion report](acceptance/company-identity-ingestion-source-20261117.md).
Continue owner manual startup-run orchestration, durable public research/provider status and
remaining dashboard/registry/provider/CLI/conversation/eight-platform full source before
combined gates. No current tests/build/check/live/install or estimate increase;58/42/prior455
held. Ingestion is currently a domain service, not a live provider/installation claim.

Latest research contract sourcef3f3d6f freezes actual company observations/startup runs and
public/official/manual people inputs with exact count/band, public URL, domain, aware time,
email publication and manual permission rules. Two standard declarations (160 actual DTO
cases plus boundary/bounds/no transport assertions) are UNRUN. See [qualified research input report](acceptance/research-input-contracts-source-20261117.md).
Continue canonical company/manual evidence ingestion, durable public research/provider
status and remaining dashboard/registry/provider/CLI/conversation/eight-platform full source
before combined gates. No current tests/build/check/live/install or estimate gain;58/42/
prior455 held. Frozen inputs confer no provider execution authority; full host uninstalled.
Private continuity snapshote077c3a3638ebeed136d434902006c98f9c41af40578768e971517e99e3b9037
at2026-11-16T23:11:45Z preserves104 indexed/6 available/98 missing transcripts; no sidebar/
account/session ownership rewrite or unavailable transcript recovery claim.

Latest catalog sourceab7d8cb connects GET/POST filtered/ranked saved search, complete bounded
application-state evidence, original shortlist snapshots/notes/run/ACK/privacy and actual
detail shortlist state. One standard declaration (140 actual status cases+multiple-packet
regression) +12 PG/HTTP declarations are UNRUN. See [qualified catalog report](acceptance/startup-catalog-shortlist-source-20261117.md).
Continue public research/discovery/provider status and remaining dashboard/registry/provider/
CLI/conversation/eight-platform full source before combined gates. No current tests/build/
check/live/install or estimate increase;58/42/prior455 held. Source company shortlist never
grants application authority; full Rust host remains uninstalled.

Latest startup detail sourcefe0e7c2 connects owner GET to coherent saved company observations,
qualified size/hiring, bounded complete professional counters and relevance, without private
profile/contact/vendor data. Actual output DTO schemas are frozen. Nine PG/HTTP declarations
including actual StartupRead validation are UNRUN. See [qualified detail report](acceptance/startup-saved-detail-source-20261117.md).
Continue filtered catalog/search and shortlist persistence (including replacing the detail
shortlist flag placeholder with saved state), public discovery and remaining dashboard/
registry/provider/CLI/conversation/eight-platform full source before combined gates.
No current tests/build/check/live/install or estimate gain;58/42/prior455 held. Full Rust host
remains uninstalled; owner browser/production state unchanged.

Latest relevance ranking sourced3c5af0 reuses the existing deterministic domain job matcher
and ports actual company weights/reasons/missing facts/exclusions/profile version with
bounded inputs. No score establishes factual or application authority. Two standard
declarations (32 actual ranking comparisons and inventory/no authority regression) are
UNRUN. See [qualified relevance report](acceptance/startup-relevance-ranking-source-20261117.md).
Continue snapshot-backed derived startup detail/search/shortlist persistence, public research
and remaining dashboard/registry/provider/CLI/conversation/eight-platform source before
combined gates. No current tests/build/check/live/install or estimate gain;58/42/prior455
held. Pure ranking is not yet a wired catalog; full Rust host remains uninstalled.
Private continuity snapshot3a1a08dff910edaa8d4469422a070620f354078b64d5f0a4ef8d8ebd051f0a92
at2026-11-16T22:26:31Z preserves104 indexed/6 available/98 missing transcripts; no sidebar/
account/session ownership rewrite or unavailable transcript recovery claim.

Latest startup intelligence source84538f1 ports source-identity size selection, human
confirmation priority, exact/range conflicts and saved job/board/company hiring qualification.
Future observations and unsupported negative hiring statements do not establish current
facts. Three standard declarations (24 actual size+26 actual hiring and separate conservative
regressions) are UNRUN. See [qualified intelligence report](acceptance/startup-intelligence-source-20261117.md).
Continue relevance ranking/derived catalog/shortlists/public discovery and remaining
dashboard/registry/provider/CLI/conversation/eight-platform full source before combined gates.
No current tests/build/check/live/install or estimate increase;58/42/prior455 held. Pure
intelligence is not yet a wired catalog, full Rust host remains uninstalled.

Latest startup filter source6101f3c freezes actual filters/shortlist DTOs and ports explicit
size/exact-range/role/location/industry rules, bounded GET parsing and schema drift stage.
Three standard declarations (68 actual DTO+110 actual normalizer cases and GET bounds) are
UNRUN. No PG/frontend additions. See [qualified startup filter report](acceptance/startup-filter-contracts-source-20261117.md).
Continue actual company size/hiring intelligence, ranking/catalog/shortlists/public discovery
and remaining dashboard/registry/provider/CLI/conversation/eight-platform source before
combined gates. No current tests/build/check/live/install or estimate gain;58/42/prior455
held. Early-stage remains explicit/default false; no owner restriction restored.

Latest saved company sourcec958651 adds owner-only coherent people/jobs/evidence GETs,
selected professional/normalized public fields, reused job DTO, stable bounded pages and
stale/future observation qualification. No provider IO, raw vendor payload or GET mutation.
Two standard +8 native PG/HTTP declarations are UNRUN. See [qualified company read report](acceptance/company-saved-reads-source-20261117.md).
Continue actual startup contracts/size/hiring/scoring/catalog/shortlists and public research,
then remaining dashboard/registry/provider/CLI/conversation/eight-platform source before
combined gates. No current tests/build/check/live/install or estimate gain;58/42/prior455
held. Full Rust host uninstalled; owner browser/production state unchanged.

Latest dashboard recovery source2606907 persists UUID-only local draft requests before POST,
reuses exact scope after response loss and uses GET once known. Reviewed replacement reads
the saved revision again, preserves old rows and recovers unresolved/newer pointers instead
of discarding them. Missing facts never navigate to an absent ID; legacy/uncertain send
history locks edits. Ten new frontend declarations are UNRUN. See [qualified recovery report](acceptance/outreach-dashboard-recovery-source-20261117.md).
Continue remaining public research/company/startup/dashboard/registry/provider/CLI/
conversation/eight-platform source then combined gates. No current tests/types/build/check/
live/install or estimate gain;58/42/prior455 held. Private continuity snapshot01674ef40635c8fe1889ca3af7e22fcce8c3c0b844cfe45b6f0d5b1b43c59eee
at2026-11-16T22:02:48Z preserves104 indexed/6 available/98 missing transcripts; no sidebar/
account identity rewrite or unavailable transcript recovery claim.

Latest outreach controller source720d9ea connects owner preview/create and local/MCP flow
over shared transient IO. Optional governed rewriting uses stable keys/original120-second
opaque admission, no locks over IO, separately retained finding and fresh context/ledger
finalization. Unknowns never redispatch; cross-mode keys and malformed retained payloads
fail closed. Fifteen native PG/loopback/HTTP declarations are UNRUN. See [qualified outreach controller report](acceptance/outreach-owner-controller-source-20261117.md).
Continue dashboard durable draft recovery and remaining research/company/dashboard/registry/
provider/CLI/conversation/eight-platform source before combined gates. No current tests/
build/check/live/install or estimate gain;58/42/prior455 held. Full Rust host uninstalled;
Gmail sending disabled; no owner browser/production action.

Latest local outreach ledger source2ebf118 preserves original outreach_logs idempotency,
current private snapshot, expected revisions, historical attempt immutability and exact
content/evidence approval. Owner read/edit/approve/reject routes are connected; unified
preview/create IO controller is next. Source review corrected actual guard timestamp/revision
ACK semantics; fixtures load the actual final SQL guard. Two standard declarations (20
sentence+14 hash actual cases) +12 PG/HTTP declarations are UNRUN. See [qualified ledger report](acceptance/outreach-local-ledger-source-20261117.md).
Continue durable optional writer/controller, all remaining full source then combined gates.
No current tests/build/check/live/install or estimate increase;58/42/prior455 held. Gmail
sending remains disabled; full Rust host remains uninstalled.

Latest grounded outreach source1a86221 binds exact current confirmed profile, complete
bounded candidate/contact evidence/resources, corrected saved job and approved local-project
digest. Pure copy uses only grounded contributions and safe saved public links, with current
employer/mailbox/suppression/freshness guards and provider-reported warning. Eleven native
PG declarations including7 actual composer cases are UNRUN. See [qualified context report](acceptance/outreach-grounded-context-source-20261117.md).
Continue durable generation/create/edit/approval/writer, remaining full source then combined
acceptance. No current tests/build/check/live/install or estimate gain;58/42/prior455 held.
Private continuity snapshotad99d5af6fb1d61bf99ce7f3133de3521ef8aef304bb4af146c3069db3311f65
at2026-11-16T21:37:07Z preserves104 indexed/6 available/98 missing transcripts; no account/
session/sidebar ownership rewrite or unavailable transcript recovery claim.

Latest outreach source504cf2c freezes actual draft input/edit/decision DTOs and adds bounded
owner-only saved history/send-attempt projections. Interrupted attempts are qualified
without GET writes/replay; private intent/context fields are excluded and saved acceptance
never proves delivery. Three standard declarations (70 actual DTO cases plus projection/
bounds) +8 native PG/HTTP declarations are UNRUN. See [qualified outreach history report](acceptance/outreach-history-contracts-source-20261117.md).
Continue grounded draft context/create/edit/exact approval and remaining full source before
combined gates. No current test/build/check/live/install or estimate increase;58/42/prior455
held. Gmail sending remains disabled; full Rust host remains uninstalled.

Latest owner controller sourcefc08727 connects local-first saved evidence, guarded fixed
provider calls/results/identity and exact finalization over shared transient host IO.
Dashboard request IDs persist before POST, recover retained requests and use GET history
after a run ID is known; no uncertain new-attempt reset. Candidate patterns stay unverified.
One standard (12 actual candidate cases) +10 PG/loopback/HTTP +6 frontend declarations are
UNRUN. See [qualified controller report](acceptance/contact-owner-controller-source-20261117.md).
Continue grounded local outreach, remaining public research/company/dashboard and full
registry/provider/CLI/conversation/eight-platform source before combined acceptance.
No current build/check/test/provider/live/install or percentage gain;58/42/prior455 held.
Controller implementation is separate from still-unverified runtime readiness.

Latest provider results source8f8f05b binds transport outcomes to consumed grants and
commits immutable finding/lookup/full-cap budget/usage before separate guarded identity
ingestion. Identical replay is retained-only; late/changed target results remain held.
Qualified explicit no-mailbox fallback survives first-pass strong-profile refresh.
Thirteen native PG/loopback declarations are UNRUN; no standard/frontend addition. See the
[qualified results report](acceptance/contact-provider-results-source-20261117.md).
Continue full local-first controller/host orchestration, grounded outreach and remaining
full source before final coordinated gates. No current-head build/check/test/live/provider/
install or percentage gain;58/42/prior455 held; public provider readiness false.

Latest identity reconciliation source12d2169 adds bounded saved mapping/profile/email
resolution, current owner-source support, preserved correction/suppression/tombstones,
conflict findings, complete ACK rollback and immutable per-observation receipts. One
standard declaration (10 actual keys+7 fold cases) +14 native PG declarations are UNRUN.
See [qualified identity report](acceptance/contact-identity-reconciliation-source-20261117.md).
Continue immutable provider-result finding/identity integration and owner controller,
grounded outreach and remaining full source before coordinated gates. No current-head
build/check/test/live/provider/install or percentage gain;58/42/prior455 held. Provider
public execution readiness false.

Latest fixed provider dispatch sourcecc1ab7d adds bounded fixed transports, opaque fresh
key/op/cost/eligibility-bound metadata, exact final target/ledger/pointer guards and one
committed POST admission/consumable grant. Unknown/async/timeout results never gain a retry.
Ten standard loopback +8 native PG/loopback declarations are UNRUN. See the
[qualified fixed-dispatch report](acceptance/contact-fixed-dispatch-source-20261117.md).
No actual provider request/install. Continue result identity ingestion/immutable findings,
controller/source integration, grounded outreach and remaining full plan before combined
gates. Current-head tests/build/check/live remain unrun;58/42/prior455 held; provider public
execution readiness false. Private continuity snapshotff9efdf2f660edb067a3890445972bfbece6fe051aeef19eec9e53b790243f5a
at2026-11-16T20:01:15Z preserves104 indexed/6 available/98 missing transcripts; no sidebar
recovery/account identity rewrite.

Latest provider projection source0c0c8a0 freezes actual PersonObservation/provider request
DTOs and ports company-bound professional identity/mailbox claims without raw vendor
personal fields. Conflicting profiles/mailboxes and redacted names are withheld; IDNA
business-host comparison is corrected. Four standard declarations (32+24 DTO /16+16 actual
provider method cases plus conservative assertions) are UNRUN; no PG/frontend addition.
See [qualified provider projection](acceptance/contact-provider-projection-source-20261117.md).
Continue fixed transport/fresh capability/one-time dispatch/result identity ingestion/
controller, grounded outreach and remaining full source before combined acceptance. No
current-head build/check/test/provider/live/install or percentage gain;58/42/prior455 held.
Provider execution readiness remains false.

Latest lookup preparation source42ce99b atomically binds original run/current target/
provider plan to unique legacy lookup, zero-POST private intent and positive credit reserve.
Expired unknown claims remain blocked; only known completed/not-found expired cache may
be replaced by a new explicit run, preserving old claims/intents/full charges. One standard
(14 actual profile URL cases plus domain assertions) +10 PG declarations are UNRUN. See the
[qualified lookup report](acceptance/contact-lookup-preparation-source-20261117.md).
Prepared claims confer no dispatch permission. Continue one-time final dispatch guard,
fixed provider IO/current capability/result identity ingestion, grounded outreach and all
remaining source before combined gates. No current-head tests/build/check/live/install or
percentage gain;58/42/prior455 held. Provider execution readiness remains false.

Latest contact run source970de71 adds atomic original run/native journal, actual ordered
request hashes, opaque180-second invocation, exact context guards and retained-only
idempotency replay. Public run root fields are whitelisted. One standard (14 actual hash
cases) +8 PG declarations are UNRUN. See the
[qualified run-admission report](acceptance/contact-run-admission-source-20261117.md).
No provider dispatch or budget grant is inferred. Continue per-target durable admission,
fixed provider IO/current capability/identity ingestion, grounded outreach and remaining
full source before combined gates. No current build/check/test/live/install or percentage
gain;58/42/prior455 held. Native provider execution readiness remains false.

Latest Apollo capability source4dd980a ports pure rate/pool/24-hour eligibility guards
and corrects the documented credit_usage_stats wrapper difference from the legacy parser.
Three standard declarations (24 rate +16 root pool +12 eligibility cases, wrapper and
preflight assertions) are UNRUN; no PG/frontend declaration added. See the
[qualified capability report](acceptance/apollo-capability-parser-source-20261117.md).
No provider key/account probe or entitlement claim. Continue fixed provider IO, durable
run/lookup admission and identity ingestion, grounded outreach, remaining full source and
final combined tests. No current-head build/check/test/live/install or percentage gain;
58/42/prior455 held. Native provider dispatch readiness remains false.

Latest contact credit ledger source7fdd777 adds atomic single-use reservation/monthly
increment, no-refund actual findings, exact ACK rollback and bounded monotonic cooldown.
Ten native PG declarations are UNRUN; no standard/frontend declaration added. See the
[qualified credit-ledger report](acceptance/contact-credit-ledger-source-20261117.md).
This ledger is not wired to provider dispatch and does not confer entitlement. Continue
durable run/lookup admission, current capability proof/provider IO/identity ingestion,
grounded outreach and remaining full source before combined acceptance. No new tests,
build/check/live/install or percentage gain;58/42/prior455 held.

Latest contact enrichment planning source175f63e adds read-only local-first preview,
saved provider/configuration/budget status and qualified retained runs/candidate patterns.
Two standard (29 DTO +12 role +12 lookup +48 fallback cases) +8 PG/HTTP declarations are
UNRUN. See [qualified preview report](acceptance/contact-enrichment-preview-source-20261117.md).
Public primary provider docs were refreshed; no private API/account action. Continue
durable lookup/credit admission, provider IO/identity ingestion, grounded outreach and
remaining registry/conversation/eight-platform source before combined gates. No current
test/build/check/live/install or percentage gain;58/42/prior455 held.
Private continuity snapshotfed847dc77c992e4321b8c6d44c7c30737254fe09283f4ef485f5290de1d7950
at2026-11-16T19:24:15Z preserves104 indexed/6 available/98 missing transcripts; no sidebar
recovery or session/account ownership rewrite.

Latest owner contact correction sourcee56651b adds actual frozen DTO, exact reviewed-row
precondition, shared owner/company/contact locks, current mailbox-proof guard, bounded
identity changes and complete update/evidence ACK rollback. The dashboard renders selected
evidence and requires reviewed corrections/current reload after every attempt. One standard
(36 actual DTO cases) +14 PG/HTTP +4 frontend declarations are UNRUN. See the
[qualified correction report](acceptance/contact-owner-correction-source-20261117.md).
Continue provider preview/research/budgets, grounded outreach and remaining saved company/
dashboard/registry/conversation/eight-platform source before combined acceptance. No new
test/build/check/live/install or percentage gain;58/42/prior455 held.

Latest saved contacts source1910d51 adds bounded read-only company contact/evidence and
job-recommendation routes, same-record provider/strength filters, full saved target-job
association, qualified mailbox/draft readiness and corrected identity badge wording.
Three standard +10 PG/HTTP +1 new frontend declarations are UNRUN;1 existing UI assertion
updated. See [qualified saved-contact report](acceptance/saved-contacts-source-20261117.md).
Continue owner correction/evidence, provider research/budgets and grounded local outreach,
then full registry/conversation/eight-platform source and final coordinated acceptance.
No current-head tests/build/check/live/install or percentage gain;58/42/prior455 held.

Latest outreach UI correction6d60fac removes legacy send-preview/send mutations and
confirmation modal under the owner's READ + CREATE DRAFT ONLY scope. Local draft approval,
history and locked uncertain attempts remain; useful historical fields replace raw JSON.
Three frontend declarations are UNRUN; no Rust/PG declaration added. See the
[qualified UI report](acceptance/outreach-draft-only-ui-source-20261117.md). Continue full
connector/provider/CLI/MCP/conversation, contacts/local outreach/startup/company/dashboard,
eight-platform source and final infrastructure before combined gates. No current-head
test/build/check/live/install or percentage gain;58/42/prior455 at9c4ace5 held.

Latest primary lifecycle sourcefe44efa (Asia/Kolkata2026-11-17) ports original unprefixed
OAuth, connected_accounts/oauth_states and token purposes, pinned compose upgrade,
consumed-before-exchange/current-context guards, durable non-replayed refresh, current
identity verify and configuration-independent local-first disconnect. One standard
(20 actual DTO comparisons) +15 PG/HTTP declarations are UNRUN. See the
[qualified primary lifecycle report](acceptance/gmail-primary-lifecycle-source-20261117.md).
Next full connector/provider/CLI/MCP/natural conversation parity, contacts/local outreach/
startup/company/dashboard, all eight platforms and final infrastructure before combined
tests and reviewed whole-family STOP migration/install/live evidence. No current-head
tests/build/check/provider/live/install or percentage gain;58/42/prior455 at9c4ace5 held.
Private continuity snapshotda5db51efd4c5cb7fff1a21c800f0aada2f390968119f6ac247a3eac1d86356e
at2026-11-16T18:45:52Z preserves104 indexed/6 available/98 missing; no missing-byte/sidebar
recovery or account/session identity rewrite. No partial final or100% claim.

Latest legacy-status source8e399d6 adds public-column-only primary Gmail saved status,
honest recorded-vs-current verification and explicit historical send/send-preview refusal
before account/token/body/database work, regardless of an older send flag. Two standard
(16 actual projection comparisons plus routes) +4 native PG/HTTP declarations are UNRUN.
See [qualified legacy-status report](acceptance/gmail-legacy-status-source-20261116.md).
Next original primary-account unprefixed OAuth/refresh/verify/local-first disconnect,
full conversation/registry/contacts/outreach/providers/eight-platform source and final
infrastructure, then combined tests and reviewed whole-family STOP installation/live proof.
No current-head tests/build/check/live/install/percentage gain;58/42/prior455 at9c4ace5 held.

Latest draft-dispatch source32720fe adds the existing explicit Gmail draft endpoint with
exact content/profile/account binding, one immutable POST admission, independent content/
marker readback and at most3 explicit GET-only reconciliations. Cancelled/unknown leases
and spent intent identities cannot gain another POST; late errors preserve newer proof.
The UI keeps uncertain drafts locked and offers a reviewed existing-draft check. Fourteen
native PG/HTTP +2 frontend declarations and expanded existing route assertions are UNRUN.
See [qualified draft-dispatch report](acceptance/gmail-workspace-dispatch-source-20261116.md).
Next remaining legacy integration/status/refusal parity, full conversation/registry/
outreach/providers/eight-platform source and final infrastructure, then combined tests,
reviewed whole-family STOP migration/install and actual per-platform/focus/resource proof.
No current-head test/build/check/provider/live/install or percentage gain;58/42/prior455
at9c4ace5 held. No partial final or100% claim; all existing external/owner-action gates stay.
Latest private continuity snapshotdd24c563039414dd4726b6a6d69cbffe56ea1e21c700bbe98c56d400d08685e4
at2026-11-16T18:25:08Z preserves104 indexed/6 available/98 missing; missing transcripts
and account-filtered sidebar entries are not recovered or rewritten.

Mailbox-owner correctiondabd37b puts older local lifecycle/read/draft guards under the
shared owner fence, adds the reverse outreach identity check after exchange and supplies
bootstrap timestamps without changing conversation JSON/messages/TTL. Three native PG
declarations are UNRUN. See [qualified correction](acceptance/gmail-mailbox-owner-fence-source-20261116.md).
Continue explicit reviewed Gmail draft dispatch, remaining integration/status/refusal,
conversation/registry/outreach/providers/eight-platform source and final combined gates.
No current-head tests/build/check/live/install/percentage gain;58/42/prior455 held.

Latest role-account sourcebe4c8df adds fixed read-slot identity reservation/connect,
original draft.* OAuth/token purposes, separate compose account, consumed-before-exchange
callbacks, durable non-replayed refresh intents and local-first disconnect on shared IO.
Ten PG/HTTP declarations and expanded existing route assertions are UNRUN. See the
[qualified account report](acceptance/gmail-workspace-account-source-20261116.md).
Next explicit reviewed Gmail draft dispatch and remaining legacy integration/status/refusal
source, full conversation/registry/outreach/providers/eight platforms, then combined gates.
No current-head build/check/test/provider/live/install or percentage gain;58/42/prior455
at9c4ace5 held. No partial final; preserve all external/owner-action and no-replay gates.

Latest workspace local source7ee8217 adds coherent fixed-role saved metadata and encrypted
local draft list/save/edit with original Python hashes/purposes, current reviewed profile,
exact CAS, immutable dispatched/unknown state and bounded read-only GETs. Three standard
(37 actual DTO/10 actual content/hash comparisons plus routes) +9 native PG/HTTP declarations
are UNRUN. See [qualified local-workspace report](acceptance/gmail-workspace-local-source-20261116.md).
Next read-slot connect and separate outreach compose OAuth/refresh/disconnect/explicit draft
dispatch; then remaining full source before final combined gate. No current test/build/
check/live/install or percentage gain;58/42/prior455 at9c4ace5 held. No partial final.

Latest local-alert source6053fe5 adds approved local-account policy/sync, receiving-domain
authentication before body, permanent message receipts, cross-account factual candidates,
spent/unknown-history quarantine, atomic ACKs and shared transient background scheduling.
GET/UI distinguishes configured alerts from paused processing. Three standard +16 native
PG/HTTP/worker +1 frontend declarations are UNRUN. See the [qualified alert report](acceptance/gmail-local-alerts-source-20261116.md).
No current-head tests/build/check/live/install or percentage gain; prior455 at9c4ace5 and
58/42 held. Next three-role workspace/outreach-account/drafts, remaining conversation/
registry/outreach/providers/eight-platform source, then final combined gates and reviewed
STOP-only installation/live proof. No partial final. Private continuity snapshot
5a2e4486ffb73b00a5278c58d05db40f5c4cbee650dda45531ced47d8124c6ea at
2026-11-16T17:57:35Z preserves104 indexed/6 available/98 missing; no sidebar recovery claim.

Development branch: `feat/rust-agent-runtime`, PR #50, base `chore/uv-python-tooling`
(PR #49). The Rust migration is incomplete. Installed legacy services and the extension
must not be mistaken for development. Resume this checkout and its current ownership;
PDF/document-worker and subsequent packet work are committed. No new worktrees or source copies.

Latest source checkpoint, 2026-11-16:42ddd19 adds complete local reviewed Gmail history
routes/CAS/evidence/expiry maintenance; Telegram browser/local commands and prompt delivery
reconciliation are also committed. All newer source since9c4ace5 is UNTESTED and uninstalled
as a whole. The owner's source-first method still defers all build/check/test suites to the
final combined gate. Prior validated9c4ace5 provides193 standard +262 dedicated native PG
passes,455 distinct; it does not validate this head. Estimate58% complete/42% remaining held.
Next: complete legacy Gmail read-account/OAuth/selection/sync, job alerts and draft workspace,
full natural conversation/registry, outreach/providers/platforms, then combined acceptance
and reviewed whole-family STOP-only installation/live proof. No partial final or100% claim.
Latest private continuity snapshot95fb05976f07df5e5fecb6a918e7101e28fbcb0d5ed7d129f18b31bb5c6d96a3
at2026-11-16T13:37:45Z retains104 indexed/6 available/98 missing; no identity rewrite or
missing-byte/sidebar recovery claim. See the latest [Gmail source report](acceptance/gmail-history-source-20261116.md).

Newer read-account source1fe3b37 ports local saved account/status/selection/evidence/leads
with batched public metadata, actual selection rules, version/owner fencing and private
envelope purpose checks. Three standard (47 actual DTO/8 lead comparisons plus page/routes)
and8 PG/HTTP declarations are UNRUN. See [qualified selection report](acceptance/gmail-read-selection-source-20261116.md).
Next: legacy Gmail connect/OAuth/refresh/verify/disconnect/sync and reviewed lead import,
alerts/draft workspace plus all remaining plan scope. No current-head test/install claim;
58/42 held and prior455 evidence remains9c4ace5.

Latest account IO sourcecf3b946 adds legacy read.* OAuth, exact original token/verifier
purposes, consumed-before-exchange callbacks, durable non-replayed refresh attempts,
generation/identity/scope/expiry checks and local-first disconnect with unconfirmed revoke
reporting. Existing mailbox.* handler stays separate; shared transient permit retained.
One standard +13 PG/loopback declarations are UNRUN. See [qualified OAuth report](acceptance/gmail-read-oauth-source-20261116.md).
Next: selected sync/history checkpoint/lead import, job alerts and three-role draft workspace,
then full remaining source. No check/build/test/live/install;58/42 held. Latest private
snapshot1bae3d7e69f68ff8dd4a44fc98d5ca8bb15ccfb54c4ea4fc2b411428cb90c672
at2026-11-16T17:17:07Z retains104 indexed/6 available/98 missing; no sidebar recovery claim.

Latest selected-sync source2137c9c ports explicit fixed GET batches, calendar windows/
folders/metadata rules, committed120s account/selection leases, guard-before-read, batched
deduplication and atomic evidence/checkpoints. Subject/body signals remain uncertain;
current identity/scopes/selection/expiry fence publication. Three standard (36 actual
window/query +14 subject comparisons plus cursor rules) and12 PG/HTTP declarations UNRUN.
See [qualified sync report](acceptance/gmail-selected-sync-source-20261116.md). No current
test/build/check/live/install or percentage gain. Next reviewed lead import, job alerts,
three-role draft workspace and all remaining plan scope before combined final gate.

Latest reviewed-lead source3b1ef35 wires exact selected account/evidence/link import,
unverified actual normalized projection, conservative source/URL/company identity,
human-decision preservation, similarity-only hints and atomic observation/message markers.
Two standard (18 actual constructor comparisons plus route) +10 PG/HTTP declarations UNRUN.
See [qualified lead report](acceptance/gmail-reviewed-lead-import-source-20261116.md).
Next job alerts, three-role account/draft workspace, full conversation/registry/outreach/
providers/platforms, then all final gates. No current-head check/build/test/install or
percentage gain; prior455 at9c4ace5 and58/42 held.

Local-mailbox refresh correction78f2df5 records immutable credential-free attempts and
requires reauthorization for abandoned, uncertain or expired late refresh outcomes. Older
local-slot transport failure can no longer permit an automatic second refresh. Two new PG
declarations and one updated existing case are UNRUN. See [qualified correction report](acceptance/local-mailbox-refresh-unknown-source-20261116.md).
Continue approved local Gmail alerts, three-role workspace/drafts and full remaining source;
no current-head build/check/test/install/percentage gain, prior455 at9c4ace5/58-42 held.

Latest operational gate: Brave native health and API health/readiness pass under
STOPPED162. A windowless native inactive/minimized window experiment failed focus
acceptance and exposed restored tabs, including an unloaded inactive Naukri login page.
Preserve those tabs and do not repeat that window-creation path. Guard implementation
`b9f4925e55ac57538b88aa3dce494e5fc53a8c90` reuses existing neutral windows only;
four Node tests pass, but actual setup safely refused and no successful login/DOM check
is claimed. See [the complete qualified finding](acceptance/brave-window-focus-and-login-20261115.md).
Naukri sign-in remains an owner step; do not reask or retry verification. Queue/quotas,
quarantine and first-receipt controls remain intact. Continue independent source ports.

Latest owner steering, 2026-11-15: complete agentic automation; provide Apify MCP and
Telegram tools; prefer Safari, Edge or Brave over Chrome. Existing quotas, first-receipt,
identity/resume, focus, budget and uncertain-action rules remain. Browser changes need
fresh account binding and actual focus/receipt validation. Never copy cookies or silently
fall back to Chrome.

Owner scope expansion in the current continuation: also deliver HiringCafe, Himalayas,
Wellfound, Y Combinator Work at a Startup (the owner's “y2 combinator”) and We Work Remotely.
Create missing accounts when necessary using verified saved facts; provide project MCP
tools/adapters as needed. This extends the existing Naukri/Instahyre/Internshala scope.
It does not waive provider budgets, truthful screening, focus preservation, deduplication,
review/approval, per-platform controls or the Naukri4/hourly1/first-receipt fences. Do not
claim a search feed, account or tracking entry as an actual application receipt. The owner
requests continued execution until full scope completion; current goal remains ACTIVE.

Expanded-platform/MCP source `4b9c05add5eb558b6c08408dc38c6b0c7e19ca9d` registers the official
Himalayas HTTP MCP in project VS Code config. Actual native HTTPS initialization,78-tool
catalog and one public Rust/India/entry-level search passed (three requests; five reported
jobs). No account token/write tool/application action. Runtime curation/ingestion and all
new account/form/receipt acceptance remain pending. See [the qualified report](acceptance/expanded-platforms-and-himalayas-mcp-20261115.md)
and [the delivery plan](plans/expanded-platforms-20261115.md). Pending packet-generation
source work remains separate; continue it without undoing the owner's added scope.

## Continuity

`uv run --no-project python scripts/project_continuity.py snapshot` preserves available
local project transcripts and metadata in owner-only `.local/codex-history/`. Immutable,
SHA256-checked 1MiB chunks share unchanged prefixes; snapshots never erase old history.
Auth, environment files and other projects are excluded. `verify` checks retained history.
`install-backup` installs a five-minute macOS background backup; it never launches a
browser or edits Codex's DB. `resume` displays this file. Backups are never uploaded.
`recover --thread-id THREAD_ID` reconstructs a private JSONL export from retained chunks
even if the source/index entry later disappears; it does not change account ownership
or make the app show a chat belonging to another account. Take a snapshot immediately
before switching accounts to cover the five-minute scheduling gap.

Local investigation: 133 indexed Codex threads, 101 for this project; three project
transcript files remain at their indexed paths. The account-filtered app listed two
active threads and no archived threads. The cause of missing files is unproven. Do not
rewrite account ownership or claim missing transcripts recovered. App-owned history
visibility cannot be repaired by changing this project's application.
Two available older transcripts were reconstructed privately under
`.local/codex-history/recovered/`; those exports do not restore Codex sidebar entries.

Implemented in this continuation: private scheduled backups/recovery, the official
four-tool public Apify MCP registration, a native Rust MCP tool bridge and fixed
owner-bound Telegram notice API, encrypted PDF/document-worker port, and explicit
Brave/Edge browser selection. Brave was installed and passed 44 execution plus 32 queue
checks on fictional provider pages. The four application LaunchAgents remain
unregistered as recorded during the earlier migration cleanup; port8000 is offline.
Do not mistake the independent history-backup LaunchAgent for a running application.
See [MCP and browser setup](agent/mcp-and-browsers.md) for actual tool scope and commands.
Implementation `7659dfd69e2438a70d649c0cbccdcfab7f98db49`; [published checkpoint](acceptance/agent-integrations-and-continuity-20261115.md)
records245 Rust tests,20 Python browser checks,ten continuity tests,397 extension unit
tests and76 Brave fixture cases. Full live acceptance remains incomplete.

Later operational continuation: API and execution services now run from immutable
`8e985c91c58588c9a9160a3e206e760426ac1bfc`; API health/readiness passed. Saved queue
remains STOPPED revision162, supervised4/hourly1, with three uncertain applications
quarantined and zero strict worker receipts. Do not infer unused admissions from today's
daily counter. The additional allowance is exactly the owner's fourth supervised attempt.

Rust native bridge `2e54eec15493f07aba8f112703ca8a4bdb4c3492` is installed for the distinct
Brave host, using direct executable launch and adjacent private config. Chrome's agent
registration was not changed. Native health, profile connection and27 installed file
hashes passed in actual Brave with commands disabled and no site grant. Current source
`1ec7995ff6b92d81eb1590fcdf97ae46690aae23` removes the unsuccessful automatic reload/repair
path and refuses disabled extensions or original portal tabs during setup. A failed reload
temporarily left DISABLE_RELOAD; subsequent cold-start verification restored the main
extension. The temporary helper was verified unregistered and retired. Do not replay any
consumed maintenance intent. Source127 standard Rust tests pass;121 PG tests remain the
previous unchanged baseline; two new setup-policy tests pass. Full maintenance/locked
focus and live application acceptance remain open.

Latest setup steering: the owner explicitly requested autonomous Playwright setup.
A single owned background headful Brave instance is in use; never launch a second process
against its profile or take over another browser. macOS reported the screen locked and
AXWindows hidden; one unlock request was sent. Later independent extension readback
confirmed Naukri permission granted and unrelated example.com denied; queue remains
STOPPED revision162. Verified Naukri identity was recovered privately by matching retained
actual profile UI evidence to the current approved hash. One ordinary email-verification
request failed with “Something went wrong”; delivery is unconfirmed, do not resend. The
matching project's Gmail account requires reauthorization on actual search (409), despite
its saved connected status. No password was changed.

Existing Chrome Profile8 is PROFILE_OFFLINE (heartbeat over52hours old; absent from saved
active profiles). A persisted connected flag is not a live connection. No inactive Chrome
profile document was available. Native setup helper3744b12 now permits only the approved
ordinary profile request and refuses Chrome WebUI; nine tests pass. Its actual invocation
failed PROFILE_OFFLINE before creating an intent/tab. The missing Chrome native-host
registration was restored to the same canonical immutable Rust2e54 executable used by
Brave; actual framed API health passed, but Chrome's extension reconnection is unaccepted.
The original registration was absent, so rollback removes only the new hash-matched
manifest. No Chrome extension was updated and no browser was launched or activated.
Actual sampled OS focus/window order and selected Chrome tab IDs remained unchanged.
See [the native profile/account report](acceptance/native-profile-setup-20261115.md).

The remaining physical step is owner unlock/opening the existing approved Chrome Profile8
once, or account sign-in in the owned Brave window. The existing launcher refuses startup
while another Chrome profile runs to preserve owner focus. Do not ask for terminal or
extension-configuration work again. Keep queue STOPPED, Brave commands disabled, all three
uncertain applications quarantined and all maintenance/verification intent metadata private.
Continue independent Rust ports while waiting; full migration is not complete.

Rust local-model milestone `06f9b4c7abe2e10fb6198886747ac5e1d2efcfb6` ports explicitly enabled
Ollama structured drafts. It preserves the legacy optional owner-preference ledger,
consumed quotas/cooldowns, locality checks before candidate text, bounded HTTP and the
shared generation permit. Fresh129 standard +131 disposable PostgreSQL tests pass (260
distinct); Clippy and formatting pass. No real model was started or downloaded. AGY,
local fallback and the separate rearranger remain pending. See
[the local-model report](acceptance/rust-ollama-20261115.md).

Rust notification milestone `8e35f7ad5a5ba845c516cb7622be1ecc6adb3da5` adds owner inbox,
mark-read and saved delivery-history routes on the existing connection. Fresh129 standard
+135 disposable PG tests pass (264 distinct); Clippy/formatting pass. Independent read-only
review found no blocking defect; stricter query/response caps are documented. No production
notification dispatch/data change or Rust runtime installation occurred. Notification
preferences/synchronization and the remaining services still need ports. See
[the notification report](acceptance/rust-notifications-20261115.md). Next independent
work is the complete saved-jobs listing/detail/match/shortlist flow while Profile8 remains
offline and the owner's physical browser step is pending.

Saved-job screen milestone `2195b4c8ac9b144138912eb9309171bace790a05` ports complete listing,
full17-field details, GET/POST matching and row-locked shortlisting. Fresh129 standard
+140 disposable PostgreSQL tests pass (269 distinct); Clippy/format/diff pass. No-op
timestamps, method-specific match lookup order, concurrent progression and suppressed
updates are covered; no production job write or application authority. See
[the job catalog report](acceptance/rust-job-catalog-20261115.md). Continue application
packet lifecycle/review/readiness and immutable snapshots next, preserving all legacy
queue/admission/quarantine constraints. Native Profile8 remains offline; the owner's
physical browser step is still pending and must not be inferred from “continue”.

Packet readiness foundation `367a70dce545b215d1197008bb44f18eadc51fe2` ports the pure rule
calculation with3,584 compact actual-Python-oracle comparisons inside one test. Fresh130
standard Rust tests pass; unchanged prior140 PG baseline retained (270 combined, not all
freshly executed). Read-only review, Clippy, oracle reproduction and formatting pass.
Legacy worker event history now accepts the DB's existing local_worker origin;30 Python
API tests pass, API types regenerated, TypeScript/Prettier pass. This source fix is not
installed into legacy8e985c9. See [the readiness/history report](acceptance/rust-packet-readiness-20261115.md).

Packet preparation foundation `0171faddbca9613c6390b125e9323ffae2869336` now ports strict
owner inputs, all ten existing destination adapters and local field mapping. AST-only
oracles compare237 requests,4,968 destinations and3,240 fields inside three tests. A new
transaction-safe factual resolver preserves enclosing packet rollback, including durable
missing questions, without inference or narrative draft creation. Fresh133 standard and142
native PostgreSQL tests pass (275 distinct); Clippy/format/oracles/Ruff pass. No new source
copy, dependency, production/browser/model action or installation. See
[the preparation foundation report](acceptance/rust-packet-preparation-foundation-20261115.md).
This is not a completed packet service or seven-route HTTP integration.

Packet preparation/inspection milestone `8befb06dd344cd81db18734f40fbe900c27c460b` now completes
the [seven-route slice](plans/application-packet-rust-slice.md): saved material context,
atomic packet/field/event creation, exact original-snapshot replay and shared-lock reads.
Fresh137 standard +150 native disposable PG tests pass (287 distinct), Clippy/format/diff
and three new oracle checks/Ruff pass. New oracles cover38 context fingerprints,135 saved
DTOs and832 actual service-read state combinations. Two new context PG tests and six
packet-flow PG tests cover real native IO/concurrency/rollback/guards. Pinned speedate0.18
with std preserves datetime parsing without nightly. Naive expiry fails closed. All
fictional; no owner data/browser/model call, production install, receipt or resource claim.
See [the API acceptance report](acceptance/rust-packet-preparation-api-20261115.md).

Packet edit milestone `2ffe01b8cee2bc5db032010b29321646941b2c4e` adds the three Rust owner
refresh/question-add/human-answer routes, prior revision archives, material write locks,
CAS and approval clearing. Explicit resume selection,100-field cap, exact choice/length,
stale/closed/foreign/upload fences and write acknowledgements are enforced. Fresh139
standard +158 native disposable PG tests pass (297 distinct); Clippy/format/diff,68 DTO
and four actual archive-expression oracle checks plus Ruff pass. Eight new native cases
cover HTTP readback, races, failed/suppressed writes, archive rollback, concurrent profile
corrections and real guard-validated approval clearing. No new dependency/production/model
action or runtime install. See [the edit report](acceptance/rust-packet-edits-20261115.md).

Explicit packet generation `7538875b9b0018e4b1095b589d2d7beeb6b85f88` now uses the bounded
generation connection outside packet claims, then rechecks revision/context/original
field under a fresh material claim. Saved drafts and consumed model requests survive
rejected packet updates; known packet rollbacks retry without another model call. Fresh141
standard +164 native disposable PG tests pass (305 distinct), Clippy/format/diff,7,128
builder and19 input oracle cases, existing3,240 preparation cases and Ruff pass. Six new
native cases include owner edit/STOP during loopback inference, stale profile rejection,
429 cooldown and post-model event failure/serialization. No real provider/key/browser/
owner DB action or installation. See [the generation report](acceptance/rust-packet-generation-20261115.md).

Owner notification preferences `1d8f25a7df5998d16e59ec220f3ab1e02000aeee` now port GET/PUT
with default reads, closed full replacement, disabled external channels, acknowledged
atomic writes, invalid saved-state repair and fail-closed commit handling. The pure
transaction-safe reader is ready for packet notices. Fresh142 standard +167 native
disposable PG tests pass (309 distinct); Clippy/format/diff/Ruff and738 actual DTO cases
including598 current-system timezone names pass. No dependency, live preference change
or delivery. System TZif validation intentionally has no arbitrary TZPATH/tzdata fallback;
scheduled synchronization remains pending. See [the preferences report](acceptance/rust-notification-preferences-20261115.md).

Human packet review/approval, manual handoff/outcomes and transactional execution/notice
coordination are ported in the later review checkpoint below. Browser intake/worker,
Gmail/Drive/legacy Telegram/CLI/fallback/rearranger/AGY and real platform/installed/resource
acceptance remain pending. List context batching still needs optimization/measurement.
The owner physical profile/account step remains pending; do not relaunch browsers or
reask the same question. Continue canonical source work; no duplicate builds/worktrees.

## Canonical review milestone

Implementation `2b6c4e1cc16452172627129e4cd761280b91f134`, byte-preserving fragment
correction `c57b7e4035d2d34f900821c3dd362cd8fda9ecc0`; see
[the qualified acceptance report](acceptance/runtime-review-and-boundaries-20261115.md).

Owner renewed the active goal: finish the full Rust, continuously operating agentic
project, fix relevant architectural findings and run live acceptance; report success
only at actual scope completion. Existing specific approval/quota/focus controls remain.
The source work after7ff1704 now includes exact packet review/approval/manual handoff,
transactional notice gates, manual submission/outcome tracking, attributed bounded public
Himalayas/WWR feeds and MCP tools, a shared generated HTTP security contract, cooperating
Python/shared versus Rust/exclusive writer-family leases, and runtime/UI/extension source
decomposition. No complete runtime installation or new application occurred.

Native evidence for this checkpoint:152 standard Rust tests and181 dedicated disposable
PostgreSQL tests pass (333 distinct), Clippy passes. Frontend305 tests/typecheck/build
and extension399 tests/build pass. The first full Python run had3357 passed,64 skipped
and6 failed in916.56s: a route-order regression introduced during decomposition caused
three search failures; a stale online-profile fixture omitted the now-required window ID;
two isolated dropdown cases failed under concurrent fixture load. Route ordering and
fixture were corrected; all six pass in an isolated10.10s rerun. The complete sequential
Python rerun then passed:3,364 passed,64 skipped,2 deprecation warnings in963.55s.
The95 boundary and32 policy/lock focused checks overlap that suite and are not additional
unique tests. Current Rust format/Clippy, policy-copy drift, review/tracking oracles and
changed-Python Ruff checks pass. Review oracles cover32 requests and45 actual notice
cases; tracking covers71 requests. No installed runtime cutover follows from these tests.

The expanded native feed uses fixed official endpoints, durable per-platform cooldowns,
source attribution and bounded parsing. It does not ingest jobs or verify application
eligibility/accounts/employer destinations. No provider request was made by the new code
in this milestone; the earlier three public Himalayas MCP requests remain separate evidence.
See the new writer ownership/connection-budget document underdocs/architecture and
ADRs006–008. The family fence is single-host source protection, not an installed or
distributed lock; older and standalone writers require an explicit stop/inventory at cutover.
Continue unported intake/browser/execution, discovery ingestion, account,
Gmail/Drive/provider/legacy command and production scheduling/install/resource/live work.

Latest owner reply confirms Brave's macOS file permission was enabled. A read-only check
of the already-running owned Brave instance passed native health through the extension;
Naukri permission is granted, and selected tabs stayed unchanged. API health/readiness200,
saved queue STOPPED162. No browser restart, navigation, new profile connection, site grant,
Apply, quota change or receipt was performed. An earlier whole-desktop snapshot compared
across the interruption first matched, then differed in foreground/window ordering over
the longer interval; do not attribute that difference or claim full focus acceptance.
This permission confirmation does not establish Naukri sign-in or Gmail reauthorization.

Latest public-feed correction `70a18eeb31c475aafaf11bcf415f5445d1a2b20d` preserves exact
provider application links separately from canonical source identities and distinguishes
Himalayas update time from unknown original posting time. Actual native Himalayas request
returned20 jobs. WWR's first native parse failed on a huge valid description; one bounded
diagnostic response was saved privately and the final bounded, explicitly marked preview
parser accepts it with20 results and no further request. No final fresh WWR transport
retest, ingestion, account verification or application is claimed. Fresh156 standard
+181 native fictional PostgreSQL tests pass (337 distinct), plus an overlapping final
nine-parser-case boundary rerun. See [exact live/fixture limits](acceptance/public-feed-live-and-links-20261115.md).
Fresh Brave inventory found no Naukri page; selected tabs stayed unchanged. Do not
repeat the pending physical login question or relaunch the owner's browser. Continue
independent source ports. Private history snapshot/verify also passed; absent source
transcripts remain absent, and no account/session ownership was rewritten.

## Remaining acceptance

Finish and test PDF, Rust service/API/browser/application/Gmail ports and integrations.
Validate every job platform with real account evidence. Complete STOP-mode installation,
rollback, focus, policy/history/identity/PDF integrity and CPU/RSS/latency measurements.
Fixture success does not count as a real application. No hosted Actions; merge only
after the owner's completion conditions hold.

Detailed plan: [Rust migration](plans/2026-11-14-rust-agent-migration.md). Publish each
milestone and exact test counts in `docs/acceptance/`, update the PR and this record,
and preserve the ownership handoff. Never publish private transcripts or credentials.

## Approved plan implementation — 2026-11-16

Owner requested implementation of the approved complete-source then combined-test plan.
Browser decision: Brave primary, Edge explicit alternative, Safari deferred. First new
slice7500f9a adds token-bound cached Himalayas/WWR ingestion, conservative durable source/
canonical deduplication, preserved owner decisions, expiry/partial-evidence guards and
explicit write-annotated MCP tools. No source platform ingest is an application receipt.
Runner correctiona56e512 adds bounded sequential fixture orchestration with private logs,
failures and NOT TESTED stages. Full combined run is deferred until remaining source work
is integrated.346 distinct Rust cases covered (158 standard;187 full PG plus one extra
HTTP case),4 runner tests pass after owned-process-group timeout correction3e8c340; initial MCP catalog failure is corrected and recorded.
See [the new report](acceptance/cached-feed-ingestion-20261116.md). No live DB/provider/
browser/install/submission action. Continue remaining discovery scheduling/filtering,
browser/execution/account/Gmail/Drive/provider/Telegram/CLI ports, then the combined
cycle and STOP-only whole-family cutover/live acceptance. Do not repeat owner login asks
or re-enable the failed Brave window-creation path. This is an active incomplete plan.

## Active completion continuation — scheduler/accounts

Owner explicitly requests no partial final reports: continue the complete plan and
report completion only after its acceptance; interrupt only for unavoidable genuinely
missing owner information/actions, without repeating the pending login request.
Implementation21bc50a adds opt-in revisioned public discovery on the existing worker,
STOP/policy transaction fences, fair source rotation/cooldowns, guarded dashboard controls,
and Python-compatible purpose-bound account token encryption with key rotation.
Evidence:159 full standard +196 full native PG +3 extra token cases (358 distinct Rust),
309 frontend tests/typecheck/build/format and Clippy pass. Actual headless Brave UI fixture
screenshot uses fictional requests/data and fixture styling, not live account acceptance.
See [the checkpoint](acceptance/discovery-schedule-and-token-parity-20261116.md).
No installed service/profile/provider or application action changed. New Gmail GET-only
transport source is now being implemented; preserve its uncommitted files and finish
its tests/consent/account-service wiring. Continue remaining ports and the final combined
cycle/cutover/live acceptance; the full plan remains ACTIVE and incomplete.

Google/Gmail protocol foundation7921916 is committed: fixed GET-only message transport,
closed Google OAuth endpoints, strict tokens/scopes/PKCE/identity and numeric-loopback
fixtures;8 focused native tests plus Python protocol/DTO comparisons and Clippy pass.
See [qualified evidence](acceptance/google-mail-transport-20261116.md). No account routes
or consent/refresh lifecycle is claimed working and no live Google call occurred.
A production blocker was identified in source: MCP uses HTTP while the host requires
TLS, so its production tools cannot currently work. Next implement private owner-only
Unix socket transport authenticated by kernel peer UID; preserve HTTP TLS/token/origin
policy and do not forge forwarded TLS headers. Current legacy/native installed paths
remain untouched. Then continue account service fencing and all remaining full-plan work.

Private transport fix `e841b7d0c9ab48e0504a41ac3f887046471bc034` adds owner-private Unix
IPC for MCP/native/Next.js while retaining ordinary TCP TLS/token/origin policy and the
existing API connection/permits.177 standard Rust +2 targeted native PG cases pass;
317 frontend cases/typecheck/build/format and Clippy pass. Initial macOS socket-mode and
fixture failures were corrected; no production install/account/profile/queue change.
See [qualified transport evidence](acceptance/private-runtime-transport-20261116.md).
Continue account consent/generation/refresh service ports now. Full plan remains ACTIVE;
no partial final report, fifth Naukri admission, unknown replay or automatic window creation.

Local Gmail lifecycle `01c3f6b0d8f283dffcc21f3b20e1fdc601debb41` now ports consent,
browser-bound one-use PKCE callback, strict identity/scopes/allowlist, encrypted access,
generation/refresh leases, verification and disconnect before revocation.181 standard
Rust +11 native fictional PG and17 legacy Python module tests pass; Clippy/format/Ruff
and private continuity snapshot/verify pass. A failing concurrent refresh regression
exposed expired-lease restoration; Rust and legacy Python source now remove those fields.
See [qualified account evidence](acceptance/gmail-account-lifecycle-20261116.md).
No actual account/provider/service/profile change or installation. Search/MIME/drafts,
alerts/Drive/legacy account variants and other full-plan ports remain next; alert status
marks the Rust poller unavailable instead of claiming its saved policy is active.
Continue without a partial final report, repeat login request, fifth admission or unknown replay.

Selected-message/MIME/reviewed-draft implementation `10f4bc62d39c57dcf557a22c995d705515602e5a`
now adds INBOX search/recent body consent, no raw body at rest, bounded hidden-HTML/link
parsing, exact content-hash reviewed drafts and self-test verification. Dispatch intent
precedes the one fixed POST; unknown writes reconcile without reposting, and disconnect
races fence results while retaining intent.186 standard Rust +19 related native fictional
PG tests pass; Clippy/format/diff pass. See [qualified mail evidence](acceptance/gmail-selected-read-and-drafts-20261116.md).
New pinned MIME/header/tokenizer libraries add4 packages with existing external locks
unchanged. No actual Google/mailbox/profile/application/installed change. Continue Drive,
legacy account/history/alerts and all remaining full-plan services, then combined/cutover/live
acceptance. User still requests no partial final report; pending login and quota/focus gates remain.

Saved resume-review implementation `d8c02569b4dff61465086a3f2e867ede12e42a15` ports the five
existing owner routes, source CAS/history and atomic profile/PDF/evidence activation with
strict review, rollback/ACK and reconnect-without-replay. Metadata history is batched in two
queries including older active/latest pointers, without loading ciphertext. Drive OAuth/
downloading remains intentionally deferred per current code/account plan; manual PDF upload
continues. A false availability literal is now in both API schema and generated UI types.
Fresh188 standard +225 complete native PG (413 distinct Rust),35 Python resume and317 UI
tests pass; typecheck/format/Clippy/Ruff pass. See [qualified resume evidence](acceptance/native-resume-review-20261116.md).
No actual owner PDF/account/provider/profile/browser/queue/install change occurred. Full
project remains ACTIVE/incomplete; continue legacy account/history/alerts and browser/
execution/provider/CLI/Telegram/platform ports, then final combined/cutover/live acceptance.
The owner's requested status estimate was explicitly rough:55% complete /45% remaining
for the full plan, not a measured acceptance score. Do not turn fixture counts into a claim
of production completion. No partial final report or repeat of the pending login request.

Native browser lifecycle `b0462175df6e0ed113601fe5629ef2f3c7f7f771` now implements fixed
extension-only native authentication, connect/heartbeat/disconnect and owner status/
selection/disconnect. Session/window replacement quarantines admitted original forms,
revokes old tasks/plans/commands and preserves quotas/pause reasons without replay.
Windowless heartbeat always denies automatic window creation. Suppressed-write rollback,
unknown commit and API reconnect are tested. Fresh191 standard +235 full native PG tests
(426 distinct), Clippy/format/diff pass;42 isolated Python projection comparisons pass.
See [qualified browser evidence](acceptance/native-browser-profiles-20261116.md).
No actual browser/account/provider/queue/service change. Poll/start/ack remain unavailable;
continue command broker, task/form/application execution and remaining approved ports.
The owner reiterated continuing to full completion; do not stop at this source checkpoint.

Browser command broker `35cf48e38db12c88333abc781a6afa086506bec3` ports owner enqueue and
native poll/start/ack with existing idempotency hashes, selection/session/lease fences,
fresh packet/material/profile/destination/policy checks and retained receipt/quarantine
no-replay rules. Lease expiry is checked after material waits. Status normally uses one
SQL snapshot without the owner lock, and closed history no longer fills live inventory.
Fresh192 standard +250 full native PG tests (442 distinct), Clippy/format/diff pass.
Three real native-process framed requests use the fictional Rust HTTP host;20,002 closed
records and owner-lock contention tests pass. Continuity snapshot/verify checks881 refs.
See [qualified broker evidence](acceptance/native-browser-command-broker-20261116.md).
No installed/actual owner browser/provider/account/queue action. Task/form/execution ports
remain next; native command transport is not a working application or strict receipt.
Continue full authorized work without a partial final report or repeated login request.

Task lifecycle `9c4ace570535a5856184775f8045ee89eafdd05f` ports native open/get/update
and owner list/application lookup/control, preserving tab/profile/version ownership,
sticky stop, interrupted-fill uncertainty and request nonce/savepoint/lease fences.
Ordinary task checkpoints are read-only repeatable snapshots without owner/packet locks;
filling checks reopen under the mutating fence. Existing packet locking stays unchanged.
Fresh193 standard +262 complete native PG (455 distinct Rust), Clippy/format/diff pass;
36 isolated actual-Python DTO/helper comparisons are inside one new standard test.
See [qualified task evidence](acceptance/native-browser-task-lifecycle-20261116.md).
No installed/actual owner browser/provider/account/queue action or application receipt.
Form inspection, exact-field review/consume, fill receipts and question bridging remain
next, followed by the remaining full-plan ports and combined/cutover/live gates.
Do not stop at this checkpoint, repeat login asks or treat task metadata as completion.

Newest owner execution instruction: research/plan/structure first, implement all remaining
files, then run all test categories together at the end; avoid repeated test runs. Apply
[the consolidated delivery plan](plans/completion-execution-20261116.md) and
[primary research record](plans/completion-research-20261116.md). Preserve current uncommitted
pure form policy/schema/test work. Do not run tests, builds or new live acceptance during
the remaining source-writing phase; add regression fixtures for the final combined gate.
Final runner must include missing browser/UI/Python PostgreSQL stages before execution.
Source review found243 API declarations across21 files; this is not route parity coverage.
Current rough engineering estimate is58% complete /42% remaining after the three published
browser milestones. It is not measured acceptance; hold until another meaningful evidence-
backed milestone and report increases to the owner. Last full validated checkpoint remains
193standard+262nativePG at9c4ace5; untested new source must not inherit those passes.
No pending test processes remain. Full plan stays active; continue source implementation.

Form source checkpoint `203a1b9eb04f2c0949b64043193ba86c9bf118c4` adds frozen form DTOs,
native inspection/preparation/exact-review/consume/receipt, owner plan list/review, task
attachment, durable unanswered-question bridging and explicit Ask queueing. Fifteen new
PostgreSQL regression declarations are saved but UNRUN; no compilation/build/Clippy or
new combined tests were run under the latest owner instruction. Formatting was written.
See [source-only evidence](acceptance/native-browser-forms-source-20261116.md). Last full
validated checkpoint remains9c4ace5/455distinct; new source does not inherit that result.
Question delivery/reply parity, queue/kernel and remaining full-plan ports are still open.
No installed/browser/account/owner-data/provider/queue action or strict receipt. Keep58/42
rough estimate and continue source work, including final-runner database/browser stages;
do not end at this checkpoint or run the deferred acceptance early.

Final-gate source `3473cf039e336cde8ea1a9b27b4c0aef1d70a3ae` expands the local runner
with Python PostgreSQL, four UI configurations,26 extension browser fixtures and explicit
backend browser journeys. Three stack fixtures now create owned native PostgreSQL17
clusters without Docker, with private environments and matching built Brave/Edge native
host names. Default extension build/fixtures now use Brave; no Chrome fallback in fixture
launchers. Source only:9 new harness regressions written,0 executed; formatters wrote files,
but no build/lint/check/test/browser/cluster/service/provider/application action ran.
The form source follow-up30033ac retains paused question-only denial;16 PG declarations
are now unrun. See [qualified infrastructure report](acceptance/final-gate-source-20261116.md).
Continue command defaults/hash compatibility, native execution/kernel and other remaining
ports before executing the final gate. Actual Edge app absent from observed Applications;
Safari remains deferred. Do not claim the source runner is validated or increase58/42.
Current private continuity snapshot found104 index entries but only6 available transcripts
and98 missing files; saved6 available privately. Missing transcript recovery remains limited.

Native command source91cc44a +ordering follow-up4c2d282 now fill DTO defaults and calculate
legacy declaration-order/masked-secret hashes from original bytes, including opaque dict
order. Eleven layouts were extracted by AST only; a drift exporter joins the final runner.
Two new standard test declarations contain18 positive actual-Python hash comparisons and
8 rejection cases, all UNRUN. No current build/check/Clippy/test/live change. See
[qualified contract source report](acceptance/native-command-contract-source-20261116.md).
Source form fixtures now use valid64-character semantic keys. Continue native execution/
queue/kernel and all other remaining source ports before the final test gate. Keep58/42,
STOP, three quarantined consumed admissions/lifetime4/hour1, zero strict receipts, pending
physical sign-in action and all actual owner browser focus constraints. Do not stop at this
source checkpoint or report it as a validated/installed/working full project.

Execution core source454dffa adds six actual frozen DTOs and pure policy/filter/queue-ID/
inspection/receipt predicates under `rust/agent-runtime/src/execution/`. Chrono-TZ0.10.4
is pinned with std; Cargo resolved4 new packages without changing existing versions or
compiling. Three standard regressions are written but UNRUN, including3,240 date/applicant
scenarios. Source/schema generation/formatting only; no check/build/test/live action.
See [qualified execution core report](acceptance/execution-policy-source-20261116.md).
Next port transactional execution storage/status/control and the complete stop/claim/
admission/identity/PDF/questionnaire/upload/submission/reconciliation kernel. These pure
helpers are not an operational application queue. Preserve all prior active scope and
continue; no partial final or increase beyond58/42. Full validated checkpoint is still9c4ace5.

Execution status sourcef23f5e3 now wires the two existing owner GET routes for queue status
and Naukri account-binding metadata. Read-only repeatable snapshot,2 business SELECTs,
retained-history aggregate/public projection, no owner-row lock, no policy/budget rewrite;
native submission remains unavailable. Five new PG test declarations are UNRUN, including
20,002-row/owner-lock/redaction and STOP/quota preservation fixtures. No build/check/test/
fixture/live operation. See [qualified status report](acceptance/execution-status-source-20261116.md).
Current-account receipt predicate now rejects missing UUID/revision context as well. Next:
transactional owner control/fences and full native queue/kernel, then all remaining ports.
No actual source installation, browser or provider change, strict receipt or percentage gain.

Execution controller source757ea01 adds the owner queue policy/control routes, shared-owner
revision fencing, interrupted-write quarantine, fresh-inspection resume, independent
Naukri task/plan/command revocation and current-account first-worker-proof guard. One new
standard and10 new native-PG test declarations remain UNRUN. No build/check/test/live
operation or installation; prior455 tests remain prior9c4ace5 evidence. See
[qualified control report](acceptance/execution-control-source-20261116.md).
Continue complete kernel/claims/admissions and remaining ports; hold58/42 and no partial final.

Queue/admission sourcec83f2fb ports internal enqueue/claims/lease recovery, factual any/all
skill eligibility, current account/private-PDF and original-questionnaire context, durable
lifetime/hour/day aggregates and atomic Apply/packet admission. No native queue dispatch
or production scheduler installation yet. Two new standard +9 new PG declarations are
UNRUN; full encrypted-PDF/write fault fixtures remain to add with kernel integration. See
[qualified admission report](acceptance/execution-admission-source-20261116.md).
No test/build/check/live action or percentage increase; continue full kernel and other ports.

History/receipt sourcefd85d94 adds internal typed observations, two-document immutable
receipts, canonical guarded confirmation and transactional owner notices/outbox. Historical
reconciliation without Apply cannot assert worker packet success. Two standard +4 PG
declarations remain UNRUN; native broker/lost-read response bounds/full write fixtures are
still required. See [qualified receipt report](acceptance/execution-receipt-source-20261116.md).
No build/test/check/live receipt/delivery/install or percentage gain. Continue native
discovery/preparation/profile checks, questionnaire processing and full broker, then all
remaining plan scope. Keep source-first/final-gate instruction and no partial final.

Saved-source/preparation source4b47ae3 adds ten-row approved-source cursors, private
metadata projections, no cursor skip on backpressure, idle owner-lock avoidance and local
factual packet/resume/account preparation. A separate current-material packet creation
path preserves post-lock policy reads without relaxing normal snapshot requirements. Four
new PG declarations and all existing packet regressions are UNRUN. See
[qualified preparation report](acceptance/execution-preparation-source-20261116.md).
No tests/build/check/live/scheduler/install or percentage increase; continue ordinary
discovery/profile/questionnaire/native broker and the entire remaining scope.

Profile fact foundation and corrections source877cad2 adds18-field pure comparison,
add-only verified skill/chip checks, actual account/sync DTOs and canonical UUIDs. Source
review corrected preparation's nested missing-answer snapshot requirement: SERIALIZABLE
plus post-owner-lock control/profile/material version locks, not the previous described
READ COMMITTED path. Receipt hash now matches the actual spaced-ASCII legacy expression.
Three new standard oracle/DTO declarations +1 new owner-wait/Stop PG declaration are UNRUN.
See [qualified facts/snapshot report](acceptance/profile-facts-and-snapshot-source-20261116.md).
Broader serializable form/review/generation owner-wait/control audit remains required.
Continue full account/profile-sync IO, questionnaires, discovery/native broker/scheduler
and remaining scope. No check/test/build/live/install or estimate increase beyond58/42.

Owner account/profile controls sourcea7415da adds account PUT with explicit confirmation,
primary/selected binding, CAS and contact preservation; profile-sync GET/PUT policy keeps
current confirmed version, read-only status and uncertain-save history/rollback shape.
Five new PG declarations remain UNRUN. See [qualified controls report](acceptance/account-profile-controls-source-20261116.md).
Full profile-sync work/save/reconcile, questionnaires, discovery/native broker/scheduler
and broader serializable owner-wait audit remain required. No build/test/check/live/
installation or percentage gain; continue the complete existing scope, not a partial final.

Owner-wait fence source30cd214 addresses visible-control and first-control insertion
snapshot races by advancing only owner-row metadata in Rust browser/execution and the
Python cached guard; private memory JSON/message/TTL/identity fields remain untouched.
Serializable forms also lock bounded control/profile/project reference versions. Native
health/capability reads ping PostgreSQL without owner locks/updates. Five new Rust PG +1
backend PG declarations and two adjusted existing timing cases are UNRUN. See
[qualified owner snapshot report](acceptance/owner-snapshot-fence-source-20261116.md).
New source is uninstalled; whole writer-family STOP coordination and full combined tests
remain required. Continue profile-sync work/save/reconcile, questionnaires, discovery/
native broker/scheduler and all remaining scope; hold58/42, no partial final.

Profile-worker sourceb6b1f4a adds confirmed-version/account-bound periodic comparison, independently verified summary/skills saves, immutable intent history, preserved skill chips, optional real private-PDF byte checks and reference-only dashboard notices. Two standard +9 native-PG regression declarations are UNRUN. No build/check/test/provider/install operation; prior455 remain prior9c4ace5 evidence. See [qualified worker report](acceptance/profile-worker-source-20261116.md). Continue native broker/discovery/questionnaires and other source before final combined gate;58/42 held. Unknown saves never replay; only positive independent persistence closes an active pointer. Installed STOP162/lifetime4/hour1/three quarantines/zero strict receipts unchanged.

Search/intake/reconsideration source1a993d4 ports confirmed-role ordinary search rotation, bounded20-URL set-based permanent history/capacity/event checks and ten-record filter reconsideration that can request only a fresh listing read. Two standard declarations (including280 actual Python search comparisons) +9 native-PG declarations are UNRUN. No build/check/test/live/install action. See [qualified discovery-source report](acceptance/search-reconsideration-source-20261116.md). Continue bound observed-job ingestion, original questionnaires/owner replies/native broker/scheduler and other services before final combined test gate.58/42 held; prior455 remain prior9c4ace5 evidence; installed/quota/focus/account gates unchanged.

Bound listing source24923ef ports native report validation, observed normalization, source/URL employer identity, atomic company/job/source observation, preserved canonical owner decisions, applicant-count notices and factual eligibility into the preparation lane. One standard declaration with48 actual-model comparisons +6 PG declarations are UNRUN. See [qualified listing report](acceptance/listing-observation-source-20261116.md). Search corpus count corrected to280 (previous560 was a documentation multiplication error). No check/build/test/live/install; prior455 remain prior9c4ace5 evidence;58/42 held. Continue original questionnaires/owner replies/native broker/scheduler and all other ports; no partial completion claim.

Questionnaire step source32d649a ports original-form report transitions, current packet/account/PDF checks, full-width reuse hashes and factual owner-answer validation. Four standard declarations (48 answer cases,48 transition cases,12 reuse keys,5 stricter salary/employment/remote guards) +4 native-PG declarations are UNRUN. See [qualified step report](acceptance/questionnaire-steps-source-20261116.md). Grounded preparation, owner question/reply persistence and native/scheduler integration remain unfinished. Continue independent source; no check/build/test/live/install;58/42 and prior455 at9c4ace5 held. No partial final/completion/receipt claim.

Queue owner-question sourcec7dd77d ports stable original-step envelopes, current-context dashboard replies with correct provenance, fresh account/PDF/job/form resumption and separate exact-scope reuse approval. Five native-PG declarations are UNRUN; no new standard declarations in this slice. See [qualified question/reply report](acceptance/queue-owner-questions-source-20261116.md). No prompt sent/model/provider/live/build/check/test/install; actual HTTP/Telegram integration and grounded preparation remain pending. Expired/uncertain envelopes and message IDs are retained without reenrollment.58/42 and prior455 at9c4ace5 held; continue source without partial final.

Grounded questionnaire preparation source37dac29 uses the generation connection, releases the owner transaction before authorized Cohere narrative IO, resolves confirmed/approved facts, retains context/source/approval proof and rechecks it before answer admission. Six PG declarations are UNRUN; no new standard declarations. Admission/submission entry points now use consistent SERIALIZABLE snapshots, and factual preflight holds a canonical-profile share lock. See [qualified preparation report](acceptance/questionnaire-preparation-source-20261116.md). No build/check/test/model/live/install; prior455 remain9c4ace5;58/42 held. Continue complete authenticated native controls/broker/scheduler and remaining ports, including bounded lost-read reconciliation. No partial final or operational completion claim.

Lost-response reconciliation sourcece9c2a6 adds durable maximum-three lease/read-admission ceilings alongside legacy report counts. Lost poll/admission responses and same-lease continued reads cannot silently renew the bounded account/history recovery; exhausted work stays quarantined, spent Apply history unchanged. Two standard +3 PG declarations are UNRUN. See [qualified response-bound report](acceptance/reconciliation-response-bounds-source-20261116.md). No build/check/test/live/install;58/42/prior455 held. Continue full authenticated native controls/broker and remaining source; final combined gate still deferred.

Native queue broker source58b26d2 wires authenticated status/control/poll/bind/check/admit/finish/abandon to execution services, consistent owner fences, rejection savepoints, read-only status, original-tab loss handling and current consumed-permit checks. Questionnaire answers transport only after admission; automatic manager/WebUI and windowless work remain refused. One standard +12 native-PG declarations are UNRUN. See [qualified native broker report](acceptance/native-queue-broker-source-20261116.md). No compile/check/test/native process/browser/live/install; prior455 at9c4ace5 and58/42 held. Continue scheduler/connection, complete owner/recovery/legacy/provider/platform source before final combined acceptance; no partial final.

Queue scheduling sourcec318859 connects local intake/reconsideration/preparation to the existing execution connection and background questionnaires to the existing shared transient slot. Scoped authorized Cohere settings share the provider gate; default model choice remains. Final host drain pauses a RUNNING queue through its current fences; no auto-resume, refund or replay. Two standard +4 PG declarations are UNRUN. See [qualified scheduler report](acceptance/queue-scheduling-source-20261116.md). No build/check/test/process/model/live/install; source four/three peak ceiling is unmeasured.58/42/prior455 at9c4ace5 held. Continue complete owner/recovery/legacy Telegram/Gmail/outreach/provider/platform source before final combined acceptance; no partial final.

Owner preparation controls source1dc53da adds deterministic preparation-only intents, separate policy/control CAS, individual unknown-safe controls, bounded saved-listing review and retained exec_event outbox/ACK. Five DTOs frozen;2 standard declarations (37 actual DTO +16 actual policy-reason cases) and7 PG declarations are UNRUN. Owner mutations now SERIALIZABLE; existing account concurrency fixture allows safe snapshot rollback; already-bound packet review advances the shared metadata fence. See [qualified controls report](acceptance/owner-preparation-controls-source-20261116.md). No test/build/check/provider/live/install; prior455 at9c4ace5 and58/42 held. GET Naukri summary/import, complete packet/nonqueue questions/replies/reuse, legacy worker/recovery/Telegram and all remaining service/platform ports still pending. Continue full source before combined gate; no partial final. Latest private continuity snapshot204cdd6ff7c52dcdb9f15b5b4262a1b939ec3d1cf240872a43a00fdef495c753 preserves104 indexed/6 available/98 missing at2026-11-16T12:09:04Z; missing bytes/account sidebar not recovered.

Dashboard-question source6e603d7 connects question list/ask/packet-ask/strict dashboard reply/separate reuse/copy to existing envelopes, guarded packets and original queue account/PDF/form context. Single answer+provenance UPDATE prevents trigger-driven double answer revision; exact siblings advance, old task grants clear, no new Apply/permit. Twelve PG declarations are UNRUN; no new standard declarations. Ordinary expired prompts preserve old IDs; delivery_unknown and original queue prompts never reenroll automatically. See [qualified dashboard question report](acceptance/dashboard-questions-source-20261116.md). No test/build/check/live/provider/install;58/42/prior455 at9c4ace5 held. GET Naukri summary/import, full legacy worker/recovery/Telegram and all remaining services/platforms still need completion; continue full source before combined gate, no partial final.

Naukri dashboard source983838b adds coherent read-only legacy summary, actual frozen capabilities, generation-bound alert observations, private lease omission and100-record streamed receipt counts. Expired alerts are omitted without GET writes; decision/execution/alert arrays fail closed over10000, queue status remains independently paginated. One standard +4 PG declarations are UNRUN. See [qualified dashboard summary report](acceptance/naukri-dashboard-summary-source-20261116.md). No test/build/check/live/provider/install or measured performance; prior455 at9c4ace5 and58/42 held. Continue owner import/full legacy preparation/recovery/Telegram and all remaining Gmail/outreach/provider/platform source before combined gate; no partial final.

Owner-import source52ddda0 adds actual DTO/normalized factual intake, local ATS URL identity, exact current alert review and shared conservative source/URL persistence. Canonical human decisions/employer associations remain; only same-requisition explicit owner facts may correct the reviewed employer. Similarity yields hints, never merges. Identity conflicts reject per record; DB/ACK failures abort the batch and review markers. One standard declaration (16 actual normalization +6 URL cases) and6 PG declarations are UNRUN; existing native ingestion fixtures must revalidate the shared save path. See [qualified import report](acceptance/owner-listing-import-source-20261116.md). No test/build/check/live/provider/install; prior455 at9c4ace5 and58/42 held. Continue full legacy preparation worker/recovery/Telegram and all remaining Gmail/outreach/provider/platform source before combined gate; no partial final. Latest private continuity snapshot0303cb6702b846e7abc483f95569630fb54bde7d3514098b62e7bdaef5af4d41 at2026-11-16T12:40:04Z retains104 indexed/6 available/98 missing; no missing-byte recovery claim.

Legacy preparation source956fa15 adds committed90s claims/three local attempts, current factual packet/PDF preparation, uncertain fill/submission recovery without replay/refund, separate UTC preparation budget/saved-match notices, ten-record expiry/question maintenance,10s health observation and legacy-only final quiescence. Common history guard now checks locally retained confirmed reviewed mail evidence; malformed active history fails closed. Two standard declarations (48 actual eligibility +16 history cases) and12 PG declarations are UNRUN. See [qualified recovery report](acceptance/legacy-preparation-recovery-source-20261116.md). No test/build/check/provider/live/install/measurement; prior455 at9c4ace5 and58/42 held. Continue retained receipt indexing, complete Telegram delivery/commands/reconciliation and all remaining Gmail/history/alerts/workspace/outreach/provider/platform source before combined gate; no partial final. Latest private snapshot9afa8624c8b2c1316421fd7ea849d8fadbceaa1e25c8642846dd1c1ae06a85ae at2026-11-16T12:54:02Z preserves104 indexed/6 available/98 missing, not missing-byte/sidebar recovery.

Retained indexing source531ab20 adds five-record updated_at/key scans and historical SUBMITTED_RECORDED projections without changing original receipts/packets/admissions. Strong worker, unknown, spent, packet/form and leased work remains unchanged, intentionally strengthening old indexing. Four PG declarations are UNRUN; no new standard declarations. See [qualified retained-index report](acceptance/retained-receipt-index-source-20261116.md). No test/build/check/live/provider/install/measurement; prior455 at9c4ace5 and58/42 held. Continue complete Telegram delivery/commands/reconciliation and all remaining Gmail/history/alerts/workspace/outreach/provider/platform source before combined gate; no partial final.

Telegram-question source1213e47 adds bound unknown-before-send prompt intents, fixed-owner force_reply, current-context receipt/reply correlation, shared guarded answers with Telegram update provenance, cooldown/fair draining and new typed packet-notice outbox binding. Historical pending/sending deliveries and unbound old prompts are not adopted or resent; dashboard answering remains available. Eight PG/loopback declarations are UNRUN; no new standard declarations. See [qualified Telegram report](acceptance/telegram-questions-source-20261116.md). No test/build/check/live message/provider/install/measurement; prior455 at9c4ace5 and58/42 held. Continue full legacy Naukri/browser/account/general Telegram command parity, explicit unknown-prompt reconciliation and all remaining Gmail/history/alerts/workspace/outreach/provider/platform source before combined gate; no partial final.

Telegram Naukri commands sourcefe02ace adds typed owner-only queue status/add/control, bounded saved-job/preparation intents and separate legacy controls through existing guarded services. Mutations fence before Telegram state; status avoids owner lock; rejected commands roll back while offset/outbox acknowledge once. One standard +5 PG declarations are UNRUN. See [qualified command report](acceptance/telegram-naukri-commands-source-20261116.md). No test/build/check/live message/provider/install/measurement; prior455 at9c4ace5 and58/42 held. Continue browser/account/general conversation/preview/reset command parity, explicit unknown-prompt reconciliation and all remaining Gmail/history/alerts/workspace/outreach/provider/platform source before combined gate; no partial final. Latest private continuity snapshot2046729c55b3b94292f49a0aa8fa6296639fb70fba49bf10a9aab5630e3b172c at2026-11-16T13:08:17Z retains104 indexed/6 available/98 missing; no identity rewrite or missing-byte/sidebar recovery claimed.

Telegram browser source8d85a95 adds selected ordinary-profile status and guarded open/prepare/pause/resume/cancel queues under /browser, retaining /chrome as an alias. Trusted actor-bound retries cannot adopt another actor's nonce. No window/fallback/fill/submission authority is introduced. One standard +5 PG declarations are UNRUN. See [qualified browser command report](acceptance/telegram-browser-commands-source-20261116.md). No test/build/check/live/provider/install/measurement; prior455 at9c4ace5 and58/42 held. Continue account/general conversation/preview/reset and explicit unknown-prompt reconciliation, then remaining Gmail/outreach/provider/platform source and final combined gate; no partial final.

Telegram local-command sourcef939e54 adds saved runtime/connection/discovery status, policy-audited URL previews and isolated owner-hashed selection reset, reusing actual native hashes and retained audit identities. Saved metadata is labeled separately from live checks; complete provider/CLI/MCP registry and natural conversation remain pending. Two standard +8 PG declarations and2 extra existing hash cases are UNRUN. See [qualified local-command report](acceptance/telegram-local-commands-source-20261116.md). No test/build/check/live/provider/install/measurement; prior455 at9c4ace5 and58/42 held. Continue explicit unknown-prompt reconciliation, full conversation/registry and remaining Gmail/outreach/provider/platform source before final combined gate; no partial final.

Telegram reconciliation source63cf059 fixes queue dashboard answering for delivery_unknown/not_sent and preserves same-packet siblings. It adds exact-attempt/current-binding immutable owner findings, no resend/expiry renewal, late positive Bot API evidence/conflict records and an authenticated dashboard control/fixed gateway route. One Rust standard +9 PG/loopback +4 frontend declarations,1 expanded existing UI case and3 gateway assertions are UNRUN. See [qualified reconciliation report](acceptance/telegram-reconciliation-source-20261116.md). No build/check/test/live/provider/install/measurement; prior455 at9c4ace5 and58/42 held. Continue full natural conversation/registry, Gmail account/history/alerts/workspace and all remaining outreach/provider/platform source before final combined gate; no partial final.

Reviewed Gmail history source42ddd19 adds the existing list/review/forget/retention routes, actual DTO normalization, account-bound unexpired evidence, monotonic current confirmation/status, canonical identity, owner/SERIALIZABLE/version fencing and bounded100-record expiry maintenance on the existing execution connection. GET is read-only; ambiguous duplicate rows fail closed; expired confirmation/evidence cannot silently revive. Two standard declarations (40 actual DTO/18 identity comparisons) +12 PG/HTTP declarations are UNRUN. See [qualified history report](acceptance/gmail-history-source-20261116.md). No build/check/test/live/provider/install/measurement; prior455 at9c4ace5 and58/42 held. Continue full Gmail account/OAuth/selection/sync/alerts/draft workspace and remaining conversation/registry/outreach/provider/platform source before final combined gate; no partial final.

Gmail read selection source1fe3b37 adds local account list/status/selection/evidence/leads, frozen actual DTOs, batched credential-free metadata, saved-vs-live labeling, current scopes/body/version guards, lease invalidation and read-only account/expiry paging with message-purpose metadata decryption. Three standard +8 PG/HTTP declarations are UNRUN. See [qualified selection report](acceptance/gmail-read-selection-source-20261116.md). No build/check/test/live/provider/install/measurement; prior455 at9c4ace5 and58/42 held. Continue full connect/OAuth/refresh/verify/disconnect/sync/lead import, alerts/draft workspace and all remaining scope before final combined gate; no partial final.

Gmail OAuth sourcecf3b946 adds original read-account authorization/callback/refresh/verify/disconnect lifecycle, fixed Google transport, exact scope/identity/account guards, durable unknown refresh intents and shared transient API permit without owner locks across IO. One standard +13 PG/loopback declarations are UNRUN. See [qualified OAuth report](acceptance/gmail-read-oauth-source-20261116.md). No check/build/test/live/provider/install/measurement; prior455 at9c4ace5 and58/42 held. Continue selected sync/lead import, job alerts/three-role draft workspace and all remaining conversation/registry/outreach/provider/platform source before combined gate; no partial final.

Selected Gmail sync source2137c9c adds calendar-clamped historical windows, folder progression, committed selection/account leases, fixed bounded GETs, page-batched deduplication, private-safe uncertain evidence and atomic checkpoints. Three standard +12 PG/HTTP declarations are UNRUN. See [qualified sync report](acceptance/gmail-selected-sync-source-20261116.md). No check/build/test/live/provider/install/measurement; prior455 at9c4ace5 and58/42 held. Continue reviewed lead import, job alerts/three-role draft workspace and all remaining conversation/registry/outreach/provider/platform source before combined gate; no partial final.
