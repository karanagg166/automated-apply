# Local combined validation through backend

Branch `feat/rust-agent-runtime` started clean at `cc18359268e9a28bc8d6b6a01f363fdae7833ae3`. The command was `uv run --no-project python scripts/run_acceptance.py --run`. The runner stopped at stage 13 of 36. The run record captured its starting commit and the failed stage. Its final source stamp was missing.

| Gate | Status | Evidence |
| --- | --- | --- |
| Contracts and Rust formatting | PASS | Ten stages passed before the Rust suite. |
| Rust workspace | PASS | 427 passed, zero failed and 1,079 ignored. Dedicated Rust PostgreSQL fixtures are a later stage. Workspace runtime was 173.899 seconds. |
| Strict Clippy | PASS | All workspace targets passed with warnings denied. The combined stage took 1.017 seconds using the existing build cache. |
| Backend on this commit | FAIL | 3,410 passed, 21 failed and one skipped in 844.57 seconds. Twenty tracebacks showed `explicit_postgresql_database_required`. The command workflow was the other failure. |
| Remaining 23 fixture stages | NOT TESTED | Frontend, extension, Rust PostgreSQL, migration rehearsal, browser E2E and release stages await the next run. |
| Installation and live provider acceptance | NOT TESTED | Validation covered fixture data. The Rust cutover, Mac focus evidence and strict Naukri worker receipt remain open. |

An isolated reproduction identified the first mismatch. The fixture URL omitted a password required by the application’s PostgreSQL target guard. After enabling authenticated disposable PostgreSQL, the reproduction exposed missing explicit executor fields in legacy browser acceptance requests and outdated assumptions in the command queue fixture. The targeted browser and PostgreSQL checks use fictional records and a separate headless Brave profile.

The PostgreSQL browser tests then uncovered a one-connection deadlock. Signed browser endpoints now check the exact signature before the operation and claim the nonce on the same transaction after acquiring the browser lock. Operation status uses the active command's pinned revision for cancellation. Named cancellation stops the exact operation before database reconciliation. The fictional narrative provider now follows the same read-transaction release and evidence checks as the default service. The runner records the ending source stamp when the first failure stops the run.

| Repair verification | Status | Evidence |
| --- | --- | --- |
| Originally failing backend cases | PASS | All 21 passed in targeted repair batches on PostgreSQL 17 and isolated Brave. The final narrative batch ran nine cases, including four remaining PostgreSQL cases, owner-proof replay and four cancellation regressions. |
| Acceptance harness and database lifecycle | PASS | 18 tooling tests. The Node fixture also connected to the authenticated disposable cluster and shut it down. |
| Complete clean-commit validation and cutover | NOT TESTED | The focused runs cover the repaired paths. The combined run and installed operational evidence remain required. |

Private combined evidence is under `.local/acceptance/20261118T091356Z-03149b5fab764dfbbab4decf4caa34f6/`.

## Clean rerun at `8cf1537`

The run passed 12 stages. The backend stage reported 3,426 passes, five failures and one skip in 879.86 seconds. Both source stamps identify the same clean commit. All 21 failures from the previous run cleared. The remaining 23 stages were pending after the backend failure.

One failing audit expected the old owner-approval dependency name. It now checks both the legacy approval dependency and the browser signature verifier against the same eight-route policy. The other four failures came from disposable reliability cases that connected as a restricted role without its own password, or replaced the fixture administrator's password with a placeholder. Those cases now use authenticated test connections and retain the same tested connection ceilings.

All 14 tests in the two affected modules passed on a fresh disposable PostgreSQL cluster. The source changes in this checkpoint are test-only. The complete release gate, local installation and live acceptance still need their own results. Private evidence is under `.local/acceptance/20261118T095126Z-0d6e7fd19a0346b492d64d0962ed1f58/`.

## Full backend pass at `667290a`

The next clean run passed 13 stages, including backend with 3,431 passes and one skip in 809.44 seconds. Frontend unit tests had 409 passes and four failures. The failures were three case-sensitive matches for rendered startup labels and one recovery fixture that reported more HTTP responses than attempts. The focused rerun passed all 14 tests in the two affected files. Frontend formatting passed after correcting the single reported test file.

The runner now accepts `--run --keep-going` to collect independent results in the same run. Stages that need an artifact record their unmet prerequisites. Release staging still requires all 36 stages to pass against one unchanged clean commit. The runner and release tests passed all 26 cases. The full frontend suite, remaining combined stages and installed verification still require their own results. Private evidence is under `.local/acceptance/20261118T100901Z-d50debea1f5245aba07a87cdab7d38d0/`.

## Full result collection at `9e3956c`

The clean run completed with 23 passing stages, six failures and seven unmet prerequisites. Backend recorded 3,431 passes and one skip. Frontend unit tests passed all 413 cases and the extension unit suite passed all 405 cases. Private evidence is under `.local/acceptance/20261118T132944Z-388d39744f6046eb80df433f6ccf0c39/`.

| Check | Status | Evidence |
| --- | --- | --- |
| Optimized Rust build, dashboard build and private-socket launch | PASS | Verified on the repair included in `2dbf61f`. The dashboard launch fixture passed one case. The optimized Rust workspace build took 8 minutes 1 second. |
| Native PostgreSQL baseline | FAIL | Fixture isolation and timestamp repairs raised the run from 188 to 939 passes out of 1,079. The remaining 140 failures were measured before the subsequent Gmail and form changes. |
| Gmail, questionnaire and browser form repair batch | FAIL | The next targeted run passed 146 of 154 cases. Eight failures remained at that source checkpoint, including four form cases and the native Brave smoke test. |
| Backend browser fixture | PASS | The stage passed 47 of 48 cases. The remaining MV3 denial case passed separately after selecting isolated Brave and verifying an actual permission denial. |
| Greenhouse preview and extension focus regression | PASS | The isolated popup fixture passed. The task coordinator suite passed all 34 tests, including an inactive tab open and reuse without a focus request. |
| Remaining clean release and local operational acceptance | NOT TESTED | Release staging requires a passing rerun at one clean commit. The authorized Naukri submission and independent strict receipt remain pending. |

Next.js moved from 16.4.2 to 16.4.5, which resolves the original build's security stop. The missing-socket fixture now checks for the established 503 response and confirms zero TCP fallback requests. [Next.js 16.4.5 release](https://github.com/vercel/next.js/releases/tag/v16.4.5)

An older Brave fixture reached the installed API because Brave resolved the native manifest through the macOS Chrome registry. It registered one unselected profile labeled `Fictional profile`. A versioned local owner request disconnected that exact profile. A fresh read verified that the record remained, the saved selection was identical, and the other connection states matched. The fixed fixtures use unique host names and an isolated Foundation home so Brave resolves each test manifest within its fixture directory. [Brave native host registry implementation](https://github.com/brave/brave-core/blob/master/app/brave_main_delegate.cc)

## Follow-up on 2026-11-19

| Check | Status | Evidence |
| --- | --- | --- |
| Dedicated Rust PostgreSQL | FAIL | 1,037 passed and 42 failed in 393.21 seconds. All 16 browser form cases, the isolated Brave/Rust native bridge and the Gmail draft-only workflow passed. At `e7c0f79`, 31 of the original 42 failures cleared. Of the remaining 11, nine cleared in the next focused branch run, including explicit Gmail reauthorization after an uncertain refresh. |
| Dedicated browser dashboard | PASS | All 31 tests passed in 1.9 minutes on isolated Brave and disposable PostgreSQL. This includes 12 dedicated assistant cases and the Gmail draft and history workflow. |
| Naukri dashboard | PASS | Both fictional cases passed. They exercise versioned preparation controls, explicit browser selection and a factual answer form when delivery is uncertain. |
| Browser profile and native messaging | PASS | Two isolated Brave profiles passed authentication, selected-profile-only delivery, background tab reuse, verified field filling, worker restart, browser restart and offline refusal. Zero employer writes or submissions. The isolated MV3/Python native host passed seven cases, and the real FastAPI/PostgreSQL stack passed one retained field receipt. |
| Owner dashboard and paginated reads | PASS | The Python discovery API passed 21 tests. All eight owner journeys passed in 51.7 seconds, including manual submission reporting as a separate owner claim and draft-only Gmail restrictions. Six Rust PostgreSQL HTTP tests passed in 1.03 seconds, including the last two cases from the earlier targeted run and the filtered contact, company, startup and outreach lists. |
| Local release and Naukri application | NOT TESTED | The installed service remains on its existing release. The current fixture and live acceptance gates are still open. |

Private evidence for these checkpoints is in `.local/rust-postgres-verified-repairs.2t3pgg`, `.local/rust-final-failure-recheck.XnokNL`, `.local/rust-owner-flow-recheck.d6C9H3`, `.local/frontend-release-browser.XOuM9x` and `.local/extension-browser-recheck.cVrYrZ`.

Local source `aa82936` restores the UUID discovery entry point on the installed-runtime family and forwards approved Rust GET query parameters to the domain validators. A changed discovery request for the same UUID is refused before provider dispatch. The separate Brave preparation fixture verified that preparing a bound job leaves an unrelated foreground tab and window unchanged. These results use fictional records. Private evidence is in `.local/rust-http-query-recheck.AyBSuB`, `.local/browser-owner-journeys-recheck.2bF5jY` and `.local/brave-profile-prepare-recheck.TRCLE2`.

Local source `6cc1edb` updates the isolated Brave fixtures. The extension suite passed 25 of 26 fixture programs, including 44 Naukri execution cases and 32 queue cases. Its only failure was an unpacked-extension reload. The separate maintenance retest passed after enabling and checking Developer mode through the browser's own profile API in the disposable profile. The legacy native messaging suite passed 23 cases on Brave 157.0.8103.79, including a reload of an updated fixture manifest and stable-ID restart. It recorded zero form submissions and zero form POSTs. Production browser profile settings were untouched. [Chromium profile configuration API](https://chromium.googlesource.com/chromium/src/%2B/refs/heads/main/chrome/common/extensions/api/developer_private.webidl)

Private evidence for the two reload checks is in `.local/brave-maintenance-recheck.wbOC21` and `.local/brave-legacy-stack-recheck.XWHZBb`. The final 36-stage run will verify the integrated source and archived release inputs together.

## Clean release candidate at `6337de7`

All 36 stages passed on `feat/rust-agent-runtime` at `6337de745594e26e09c77c48e951d9dc90d9bfb5`. Both source stamps were clean and identical. The recorded stages took 45 minutes and 0.512 seconds. The command was `uv run --no-project python scripts/run_acceptance.py --run --keep-going`. The run is under `.local/acceptance/20261119T095446Z-70164aa84bb5451b9c27f1cd567a659a/`.

| Gate | Status | Evidence |
| --- | --- | --- |
| Contracts, Rust workspace and strict Clippy | PASS | All contract and policy gates passed, as did 427 Rust workspace tests. |
| Native PostgreSQL and migration rehearsal | PASS | 1,079 tests passed on disposable PostgreSQL, including the actual Rust native host and isolated Brave. The additive migration rehearsal verified the catalog, STOPPED checks and restricted grants. |
| Python and frontend | PASS | 3,433 Python tests passed with one skip. All 413 frontend unit tests and 55 frontend browser tests passed across four suites. Separate backend browser acceptance passed all 48 tests. |
| Extension and packages | PASS | 406 extension unit tests, all 26 isolated Brave fixture programs, and all 23 legacy native-stack cases passed. Brave and Edge packages preserved the stable extension ID. |
| Optimized build and local staging | PASS | The optimized Rust build completed in 380.292 seconds. Checksums matched the staged binaries, dashboard, SQL and separate browser bundles. Inactive cutover plan `rust-plan-szfg9cky` validated the selected private settings. |
| Rollback inventory and installed health | PASS | Verified nine installed definitions and 16 references with zero missing. The installed API was healthy and ready. The installed dashboard's login returned HTTP 200. |
| Owner database migration | BLOCKED | Read-only PostgreSQL inspection found zero of six required Rust tables. The installed role lacks CREATE on `public`. The queue was STOPPED at revision 162 and legacy preparation was STOPPED. The optimized preflight returned `agent_database_target_mismatch`, which also covers absent required tables. The installed Python rollback recognizer's pinned catalog matches the candidate catalog. |
| Installed Rust and real platforms | BLOCKED | Cutover requires the owner-approved SQL package and a successful fresh preflight. Passive inspection identified the owned Brave process and extension worker with zero page targets. The live Naukri account, focus and fourth supervised receipt checks remain open, followed by the other platform checks. |

The reviewed additive SQL checksum is `ee2c2f612d4a40bcd66c2e15cd18c487d1a88383f53d54fb3918ab62725b9f42`. An owner-controlled backup and operator session are required by the [database migration policy](../online-postgresql.md#migration-approval-scope). The [reviewed SQL](../../supabase/runtime/001_rust_agent_runtime.review.sql) checks for STOPPED before creating the Rust tables. Preserve the hourly cap of one and the three quarantined prior admissions. One supervised Naukri admission remains available after the identity, resume, focus and eligibility checks pass.
