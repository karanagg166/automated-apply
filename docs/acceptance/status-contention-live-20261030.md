# 074fb82 installed live diagnostics: three consecutive cycles, reliability FAIL, rollback restored

**Overall FAIL.** The exact approved implementation `074fb828e6da04a093024c0ac4227b0d4ebca712` was installed and exercised through the real Profile 8 extension/native host/FastAPI/online PostgreSQL path. Three consecutive genuine Open→Prepare attempts completed without rejected admission, unsafe replay or unknown outcome. Nevertheless two original-12s profile-status observations timed out. The actual dominant cost was measured: repeated SQL reads inside a long inspection transaction occupy the sole business connection, while status waits for it. Readiness remained healthy during the bounded workload.

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch `fix/live-prepare-discovery-20261030`, base `main`. Tested installed SHA: [074fb828e6da04a093024c0ac4227b0d4ebca712](https://github.com/karanagg166/automated-apply/commit/074fb828e6da04a093024c0ac4227b0d4ebca712). Focused follow-up, **NOT installed**: [90f2f2ade50a1c31b26ca85cc7fdf5e93bb67c20](https://github.com/karanagg166/automated-apply/commit/90f2f2ade50a1c31b26ca85cc7fdf5e93bb67c20). [Sanitized metrics, correlated traces, lifecycle events and rollback evidence](status-contention-live-metrics-20261030.json).

The approved acceptance-failure rollback restored service/native/frontend references to **`79ce5f6b514279e6d9022d85b659ad77fb31bd89`** and the original extension path with matching 17-file content. All nine backed-up static installation/configuration files match, and all four processes were running at final verification. Rollback encountered real capacity/readiness failures, retained below. No new implementation SHA was installed beyond approved074fb82. No merge, hosted Actions, cleanup, application filling/submission, Gmail sending or unattended expansion occurred.

## Installation and database capacity

Reused the primary owned development checkout. Prepared a registered detached immutable release worktree at exact074fb82 with its own Python environment and frontend build, constrained to the previously installed dependency versions. Pip used cached packages, `pip check` passed, frozen/offline pnpm installation and frontend/extension builds passed. No mutable dependency directories were symlinked into the release. Kept all previous releases, private configuration, candidate data and rollback backups. Full restricted-role/TLS/catalog preflight passed; no schema migration or permission/role limit increase occurred.

The first capacity snapshot overlapped the single staging operator, so its five-session count included that known process and was not treated as the cutover inventory. After staging closed its connection, **13:17:45–13:17:49 UTC** pre-cutover inventory gracefully quiesced only the known Telegram worker, verified its exit, then observed **4/5 sessions including the temporary audit**: readiness idle, execution idle-in-transaction, API idle, audit active. Audit closed before Telegram was restored. No unidentified session was killed.

Cutover ran **13:18:10–13:19:08 UTC**. Known service processes were gracefully stopped, backed-up references changed to the exact SHA, and services restarted. Seven cold-start ConnectError polls preceded first readiness200; the successful request took3.540s, not total startup duration. These planned gaps are outside the native monitoring window. Chrome's existing Profile8 extension was reloaded via its extensions page and the native directory chooser; enabled extension ID stayed `gdjbmkffcpicbpiikcohlmokkmcpipgp`. Its new path was the approved release's `extension/dist`; content and manifest identity/permissions were checked. No preferences file was directly edited and no new Chrome permission was granted.

Post-install verification: **nine HTTP200 checks**, actual framed native-host health, selected binding unchanged, historical terminal values unchanged, paused unauthorized task before workload. The audit was enabled in the actual service worker console; its inspector was closed before commands, avoiding artificial worker lifetime during the workload. Settings/extensions diagnostic tabs were explicitly identifiable and included in tab baselines.

## Three genuine uninterrupted attempts

Real window **13:27:07–13:33:54 UTC**. One HTTP-only observer and one HTTP-only acceptance helper; no production DB observer occupied an extra slot. The helper fetched profile state first and authoritative task revision last, made no retries, admitted unique original command IDs, reconciled terminal outcomes and paused after each cycle.

| Attempt | Open admission-attempt→observed terminal | Prepare admission-attempt→observed terminal | Total including reads/Pause | Outcome |
| --- | ---: | ---: | ---: | --- |
| 1 | 62.180s | 70.945s | 161.455s | completed / completed |
| 2 | 29.597s | 63.908s | 115.277s | completed / completed |
| 3 | 39.625s | 68.884s | 126.648s | completed / completed |

These durations include admission, alarm/polling and observation delay, not just DOM execution. Six original commands completed before their original expiry. All three plans had zero fields/actions/approved fields, `read_only / NEEDS_INPUT`, `verified_application_form_not_present`. Same task, packet revision, Profile8 binding, application tab/window and browser session across attempts; zero field authorization. Final real database audit found **three new plans**, **zero new packets for the same job/candidate**, and **30 prior terminal commands unchanged**. An initial count mistakenly compared all historical plans against a preflight snapshot that omitted plans; it was corrected using authoritative `created_at` within the workload window, yielding3. No claim of16 new plans is made.

The helper's PASS is scoped to command completion. It does not override overall reliability FAIL or establish autofill. Existing Stop/expiry/restart protections were not weakened. No unnecessary repeat of earlier passing destructive recovery tests occurred; original command expiry was observed, but no new live expired-command fault was injected.

## Concurrent monitoring and live bottleneck

The observer completed **88 samples per endpoint /264 requests**, **13:27:06–13:34:55 UTC**, deliberately stopped after the three attempts. It originally allowed120 samples; no completed120 count is claimed. Original12-second timeout retained; no retry or error removal. Planned cutover/rollback gaps are outside this window.

| Endpoint | Outcomes | Mean / p95 / max seconds |
| --- | --- | --- |
| health | 88 HTTP200 | 0.0200 /0.0424 /0.1595 |
| readiness | 88 HTTP200; zero503 | 1.1805 /1.5384 /2.3673 |
| profile status | 86 HTTP200; **2 ReadTimeout** | 3.0293 /7.7182 /12.0087 |

Timeout observations began **13:29:22.322 and13:33:23.132 UTC**. Server-side status requests completed after the client's deadline. Slow status traces show **13.202s total with12.319s pool acquisition,0.290s SQL and0.443s occupancy**, and **14.065s total with13.016s acquisition,0.441s SQL and0.593s occupancy**. Thus this live evidence directly distinguishes status queue/acquisition delay from its own short transaction; the pool cause is measured, not inferred solely from temporal overlap.

| Genuine native inspection | HTTP seconds | SQL read count /seconds | SQL write count /seconds | Pool acquisition | Connection occupancy |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 13.632 | 63 /9.870 | 7 /1.651 | 1.232 | 11.952 |
| 2 | 13.529 | 63 /9.952 | 7 /1.170 | 1.563 | 11.520 |
| 3 | 15.158 | 63 /11.113 | 7 /1.165 | 2.042 | 12.673 |

Authentication and serialization were sub-millisecond; commits roughly0.15s. First inspection's two context validations took5.813s cumulatively (nested spans overlap), with packet-context builds3.159s; plan revalidation3.997s overlaps that work. Form inspection/answers5.389s also includes context. No resume bytes were needed for zero-field forms; this is not resume-I/O latency. Owner-row-lock statement time in the first trace was0.146s. Owner INSERT wrapper1.949s includes acquisition/pre-ping/SQL and must not be reported as pure lock waiting. Parent/child spans are not additive.

`pool_acquisition` includes queue/new connection creation and excludes pre-ping. `connection_occupancy` covers checkout→check-in. The installed lazy-checkout rejection check returned403 in0.0322s client time /0.00659s full server time with **zero acquisition, SQL or occupancy stages**. It confirms a SQL-free rejection no longer demands a connection. Total tracing CPU overhead relative to an uninstrumented identical live workload was not measured; no zero-overhead claim is made.

Representative resources across88 samples: API mean2.991% CPU, peak RSS78.531MiB; execution0.670%,45.828MiB; Telegram0.308%,51.906MiB; frontend0.050%,10.391MiB. The previous non-identical210-sample window had API mean3.173%, peak133.922MiB and status mean2.488s/p956.587s with3 timeouts. Current mean3.029s/p957.718s does **not** prove live latency improvement. Resource samples differ in workload, cache, uptime and planned restarts; no memory optimization is claimed.

## Focused root correction, not another broad infrastructure phase

Live traces establish repeated SQL round trips during inspection as the dominant stage. Source inspection identified repeated project fingerprints: `approved_projects` reads configuration, reads it again inside `approved_projects()`, and each `project()` rereads configuration then its approval. With four configured projects this is **10 SQL reads per fingerprint**; inspection computes the fingerprint at initial plan creation and final revalidation.

The development correction90f2f2a replaces each fingerprint operation with **one fresh coherent SQL snapshot** of configuration and both repository/document project approval namespaces, then runs the same existing approval selection logic against a copy-only read adapter. It is **not a cross-request cache**. Every fingerprint boundary rereads current records; priority/configuration mismatch, pending revision and missing approval still invalidate; task/profile/packet/Stop/expiry and final revalidation remain. No SQL engine/connection/timeouts/limits changed.

With one bounded read-only operator connection after monitoring ended, the actual online database routine comparison measured **10 SQL operations /1.653633s** for the installed selection versus **1 /0.457622s** for the development snapshot, **identical fingerprint digests**. This proves that routine's improvement with real data, not full corrected inspection/status latency. No writes, copied candidate values or raw digests were published. Only approved074 was installed;90f2f2a needs new exact-SHA review. Broader transaction splitting and infrastructure redesign were not started.

Final local validation: **494 tests passed in46.67s**, including six new fingerprint tests for1/3/8 repository projects, document-only projects, pending approval/configuration changes, read-only adapter and fresh state. Ruff E9/F/I and diff checks pass. An intermediate fixture treated a string revision as an integer; corrected final run passed, failure retained privately. Prior074 validation counts (394 backend,9 disposablePG,134 extension,284 frontend) are prior evidence; JS did not change and those suites were not all rerun here. No hosted Actions were run.

Modified implementation files: `backend/app/agent/tools.py`, `backend/app/browser/service.py`, `backend/tests/test_project_stamp_snapshot.py`. Public report/metrics files are separate from runtime source. This is a targeted application-preparation read correction, leaving Naukri form recognition as the next product priority after the demonstrated timeout is addressed.

## Profile8 tab preservation and genuine no-form result

The ten-minute,512-event session audit recorded **11 events without truncation**, covering all three attempts. General events remain unattributed; one `created` event matches an `automated_apply /created_result` receipt by salted tab hash. Two later `activation_requested` receipts refer to that same application tab. Navigation/load observations match its hashed origin. No removed event or unrelated operation was recorded. All **nine baseline non-target tabs** (seven unrelated plus two own diagnostic tabs) retained IDs/window IDs/URL hashes; zero missing, modified or new unrelated tabs. Two explicitly created/closed inspector tabs are excluded. This proves bounded ID/URL preservation, not DOM equality or long-term attribution for all Chrome actors. Historical missing tab/seven new tabs remain unexplained and are not relabeled fixed.

The application tab was created in the selected Profile8 window and reconciled through the real task/native binding, then reused. Existing old bound tab was not silently reused after worker-restart invalidation; a fresh application tab was explicitly created. No unrelated tab was adopted. Lifecycle audit expiry prevents attributing later user activity; after-window browser changes are outside this acceptance and not assumed application-caused.

Read-only DOM examination of the actual bound Naukri page found **job-details pathname, zero forms, zero frames**, three visible text inputs labeled **Select job type / Enter keyword, designation, or companies / Enter location**, and a visible **Apply** button. Those are search/navigation controls, not application fields. The zero-field result is correct **for the currently visible document**. Whether Apply opens a questionnaire, external flow or directly submits is **NOT DETERMINED**. Apply was not clicked, values not filled, and no live supported employer form recognition PASS is claimed. Next meaningful step is owner-safe navigation to an actual application form, followed by read-only inspection/preparation; do not treat current NEEDS_INPUT as that milestone or activate a possibly submitting button under read-only scope.

## Screen telemetry and rollback failures retained

The ordinary run did not request or induce screen locking/unlocking. Aggregation nevertheless found **111 LOCKED and18 UNKNOWN** OS observations during helper events. Initial UNKNOWN telemetry was never assumed unlocked. The owner-deferred controlled locked-screen acceptance remains **NOT TESTED / NOT ACCEPTED**; incidental telemetry and completed commands are separately recorded, not converted into a locked-screen PASS.

After terminal outcomes and task Pause were independently reconciled, rollback began **13:47:04 UTC**, restored service/native/frontend references and first readiness200 at **13:47:54**. Chrome's original extension directory could not be restored while the native chooser was inaccessible. It was completed when the normal desktop became available after the owner said continue; the same17-file original content/ID is now verified. No stale authorization, database rows, command history or plan receipt was restored/deleted.

Rollback was **not trouble-free**: its verification got health200, **three readiness503s**, then five other HTTP200s; the separate operator audit connection was rejected by the role limit. Telegram exited on connection-limit error. A recovery attempt to quiesce Telegram found no PID. Quiescing/restoring only the known execution process still could not obtain an audit connection. These are post-workload failures, separate from readiness88/88 during the actual cycles. My intermediate commentary incorrectly described the nine rollback HTTP checks as all passing; this report corrects that to six200/three503 and preserves the raw receipt.

Later, with the known Telegram process gracefully quiesced, a single audit finally captured **5/5**: two API-labeled idle sessions, one Telegram-labeled idle session despite the known process exit, execution idle and the audit active. Private evidence shows older and newer sessions have different client addresses. That is **consistent with lingering sessions across network changes**, but connection labels/addresses do not prove ownership or justify killing them. No unidentified session was terminated. Audit closed before known Telegram was restored; all four local processes were running afterward. Final HTTP-only rollback checks returned health200 (0.0368s), readiness503 (1.3228s), status200 (1.1525s) and paused-task200 (0.9644s). This adds a fourth retained post-rollback readiness503, separate from the three earlier verification503s. Capacity remains a material limitation, not a restored-reliability PASS. No additional observers or browser workload were started.

Current rollback result is **references and extension restored; capacity degraded**. All nine static backup hashes match, old installed release remains clean,17 extension files match, selected binding unchanged, task PAUSED without authorization/active commands. All old/new releases and private backups remain preserved.

## Acceptance matrix and next actions

| Requirement | Status | Actual scope |
| --- | --- | --- |
| Exact approved074 installation/build/preflight | PASS | Real service/native/extension cutover, old release retained |
| Lazy checkout avoids SQL-free occupancy | PASS for live check | 403 trace has no checkout/SQL/occupancy |
| Three consecutive genuine Open→Prepare | PASS for completion | 6 completed original commands,3 read-only plans, zero rejected attempt |
| Zero unexpected profile timeouts | **FAIL** | 2/88 original12s failures retained |
| Readiness during bounded native window | PASS | 88/88 HTTP200, zero503 |
| Dominant live stage measured | PASS | SQL63reads+7writes occupies11.52–12.67s; status acquisition12.32/13.02s |
| Role capacity / recovery | **FAIL after rollback** | Limit rejections,4 readiness503s across verification/final checks, lingering session labels; no forced termination |
| No unsafe retry / unknown outcome / duplicate packet | PASS for exercised window | No retry,6 completed before expiry,0 new scoped packets |
| Receipt/plan/history persistence | PASS | 3 new plans,30 historical terminal commands unchanged |
| Exact Profile8 binding and unrelated tabs | PASS for bounded audit | Same task/tab/session;9/9 non-target IDs/URLs preserved;11 events |
| Genuine application form | NO FORM on observed document | Job details/search controls; Apply behavior not activated/determined |
| Supported legitimate form recognition/preparation | NOT TESTED live | Next product priority; no autofill claim |
| Stop/expiry/restart fault cases | Prior passing evidence only | Not unnecessarily repeated; fences unchanged; task final Pause verified |
| Controlled locked-screen acceptance | NOT TESTED / owner-deferred | Incidental LOCKED observations separately retained |
| Rollback | PASS for file/content restoration; capacity FAIL | Both service references and original extension restored; no history rollback |
| Focused correction90f2f2a | PASS tests/routine, NOT INSTALLED | 494 tests; real read-only10→1 SQL fingerprint comparison |
| Employer fill/submission/Gmail sending/unrestricted automation | NOT AUTHORIZED / NOT TESTED | None performed |

Reproduction: run the actual installed owner-approved path with one HTTP-only `backend/scripts/measure_reliability.py --samples120 --interval-seconds5`, original12s observer deadline, one helper/owner gesture sequence and no overlapping SQL observers. Retain each original command ID/terminal receipt and read task revision immediately before admission. The actual helper and raw reports remain private in `status-contention-upgrade-074fb82-20261030`; sanitized traces/counts are linked here. Do not rerun production fault injection. Focused correction tests: `.venv/bin/python -m pytest backend/tests/test_project_stamp_snapshot.py -q`; combined494-test command retained in private final test log and earlier report's broad list plus six candidate-context modules. `ruff check --isolated --select E9,F,I` and `git diff --check` passed.

**Next exact-SHA proposal:** review90f2f2ade50a1c31b26ca85cc7fdf5e93bb67c20, but do not install before owner approval and a newly safe connection inventory. Keep the published backup/build/cutover/reconciliation/rollback plan, original12s monitoring and strict stop conditions. Preserve79ce5f6 as rollback. Do not expand into broad infrastructure optimization or repeat broad acceptance without a demonstrated critical failure. The measured status timeout warrants this focused project-read correction; then prioritize a genuine Naukri application form and factual preparation. The current read-only authority does not establish permission to press an Apply control that might submit. No merge is requested or authorized.
