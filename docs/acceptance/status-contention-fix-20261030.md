# Status contention and Chrome reliability: candidate implementation, live acceptance pending

**Overall: FAIL / incomplete live acceptance.** This milestone contains implementation changes and local measurements. It does not establish continuous Chrome reliability. The dominant stage of the historical 16–20-second native requests is still **NOT PROVEN**: those requests did not have internal spans, and installing new instrumentation requires exact-SHA approval. The installed release remains `79ce5f6b514279e6d9022d85b659ad77fb31bd89`.

Implementation branch: `fix/live-prepare-discovery-20261030`, base `main`, [PR #48](https://github.com/karanagg166/automated-apply/pull/48).
Exact runtime candidate: [d504d26e889859b2b39111bb5deedce80c4bd589](https://github.com/karanagg166/automated-apply/commit/d504d26e889859b2b39111bb5deedce80c4bd589).
The reporting commit additionally contains the explicit fictional benchmark harness and this report; it does not change runtime source. [Sanitized measurements](status-contention-fix-metrics-20261030.json).

## Evidence and corrections

Reviewed the six requested reports, PR metadata, ownership registry, workspace policy, original private acceptance receipts/summary and native HTTP timing extracts from the Mac logs. The earlier three status timeouts, two revision conflicts, missing unrelated tab and seven new unattributed tabs remain failures. Earlier Stop/restart/crash successes were not unnecessarily repeated against production. Locked-screen testing remains owner-deferred.

Proven code/fixture findings:

1. `require_profile` made separate profile/fixed-selection/selection/lease reads, including a repeated selection read. It now refreshes all relevant rows in one SQL snapshot at **each** authorization boundary. Secret, selected profile, browser session, lease version/token, original expiry and lease expiry checks remain. No prior authorization result is cached.
2. Form context validation separately loaded reviewed profile/confirmation, packet and job. It now joins those validation reads while retaining the packet/context locks already acquired by the existing packet service. Packet revision, digest, profile confirmation, eligibility, policy and final lease checks remain. This removes round trips without introducing an analysis snapshot that could silently authorize stale context.
3. The owner-lock cache recognized only the innermost transaction. A savepoint could reacquire a lock already held by its ancestor. Ancestor-held locks are now reused; locks acquired in rolled-back children are never reused. PostgreSQL lock lifetime and the owner-before-packet ordering remain unchanged. This is transaction shortening through fewer SQL operations; expensive answer preparation has **not** yet been fully split into separate read/validate/write transactions.
4. Focus events always called `move`, incrementing task version and adding a persistent operation even after the task was already paused, inactive and had no plan/authorization. Only semantically identical focus observations now return unchanged state, after the existing identity and strict version checks. First meaningful focus loss still clears the plan/authorization and advances the version. A stale focus event still gets 409. Concurrent PostgreSQL tests verify two unchanged observations both preserve version 7; for a meaningful change one advances to 8 and the competing stale request is rejected.
5. Dashboard Open/Prepare previously admitted cached task versions after potentially slow profile reads. It now reads authoritative profile state first and task state last, checks selected identity/packet context, then admits with that version. Pause/Resume/Cancel refetch too, but refuse changed safety-relevant state. Errors refresh displayed state and require another owner gesture. There is **no automatic command retry**, no acceptance of stale versions and no restored old plan authorization.

These findings prove unnecessary work and a revision race mechanism. They do not prove which internal stage dominated any historical live timeout.

## Correlated instrumentation

The candidate emits one bounded `request_timing` JSON summary per HTTP request, with a server-generated request UUID, native request UUID and native remote command UUID. `X-Request-ID` is returned and the native host records the same backend UUID alongside command/request UUIDs. Native stdout remains framed protocol only. No credentials, SQL text/parameters, Gmail, resume bytes, page URLs or employer/candidate field values are recorded by this instrumentation.

Spans cover request entry through final ASGI completion; authentication; session construction; explicit connection acquisition; owner-row INSERT and row-lock acquisition; profile/task loading and authorization; packet/context building; resume access; form inspection/answers; SQL reads/writes and failed SQL; flush, commit and rollback; connection occupancy/check-in; native/status response serialization and HTTP response start/completion. Pool peak checked-out count is recorded. Engine instrumentation is installed once. No extra engine, connection slot, deadline increase or unlimited concurrency is introduced.

Interpretation limits: `pool_checkout_wait` is total connection acquisition, including connect/pre-ping when needed, **not pure queue time**. `owner_row_lock_wait` includes the lock statement's round trip; INSERT conflicts can wait in `owner_row_insert_wait`. Connection occupancy measures checkout to check-in, including transaction work. Parent/child spans overlap and must not be summed. Resume stage is absent when no resume bytes are read. Response serialization is explicit for the native and profile-status endpoints. The final body/HTTP duration includes dependency cleanup. SQL errors have a separate timing bucket. This distinguishes pool acquisition from transaction occupancy without asserting a pool cause from overlapping request timestamps alone.

## Measurements and genuine failures

Historical installed status: three 12-second observer ReadTimeouts; corresponding native requests **17.5237 / 19.6243 / 16.8151s** and overlapping status completions **17.5423 / 19.1990 / 15.8539s**. Readiness retained 207 HTTP 200 and three planned-restart ConnectError gaps, zero 503. These are inherited real observations, not rerun counts.

Final reproducible fictional native inspection comparison (20ms injected at every SQL cursor operation, same fictional form; legacy context/profile/lock functions loaded from reviewed commit `c9890845be596a5f78bf7e0253b528639c1a9cb9`):

| Metric | Before | After | Scope |
| --- | ---: | ---: | --- |
| SQL round trips | 101 | 93 | Includes savepoint/control statements |
| Dispatch plus commit | 2.5700s | 2.4084s | One sample each; about 6.3% lower, not production benchmark |
| Connection occupancy | 2.5646s | 2.4036s | Measured checkout/check-in |
| Owner-lock wrapper cumulative time | 0.1239s | 0.0490s | Includes SQL work, not pure lock contention |
| Candidate context/validation cumulative time | — | 0.8771s | Two calls; overlapping child spans |

The 93 remaining round trips are material. This improvement alone is insufficient evidence for the required live deadline. The benchmark does not model production pool scheduling, Supabase latency or the real page. An initial partial comparison measured 99→93 operations before the harness also replaced the execution module's imported legacy lock alias; the final 101→93 comparison above is authoritative. Engine hooks were also made idempotent before the final trace.

Independent pool test holds the only connection, queues another session and verifies measured acquisition delay >=40ms after a 50ms hold, two check-ins, and no leaked SQL values. Disposable PostgreSQL owner-lock test measures a genuine blocked legacy path rejected with `55P03` in **0.2045s**, versus ten candidate idle status/claim cycles averaging **0.0072s**. This verifies the established lock isolation mechanism, not a production latency promise.

**New actual Mac/remote failure:** a small direct read-only routine benchmark could not obtain its single connection: `role_connection_limit` (SQLSTATE not captured) (server message: too many connections for runtime role). It completed **zero queries** and was stopped; no successful remote before/after measurement is claimed. No database fault was injected and no limit/configuration was raised. This is an actual capacity failure and blocks the zero-connection-errors criterion. The four-slot runtime budget from the earlier report is a design budget, not a fresh verified session inventory. Do not start another remote observer or helper until existing sessions are inventoried within an approved maintenance window.

No new production CPU/RSS comparison is available. Pools remain bounded at their existing sizes; no dependency installation, extra worker or new service was introduced.

## Tab provenance and form detection

Candidate diagnostics use existing supported tabs/window/storage APIs and require no new manifest permission. An owner-enabled `chrome.storage.session.tabLifecycleAudit` expires within ten minutes and stores at most 512 events, with a truncation flag. It records timestamps, event type, per-audit salted hashes of tab/window IDs and available origins, and explicit source. Automated Apply activation requests and returned tab-creation IDs are marked `automated_apply`; created/removed/navigation/loading/activation/attach/detach/replacement/window-focus observations are **unattributed**. Origin is null when unavailable under existing grants. No raw URL, title, DOM, salt or browser secret should be published.

Chrome does not disclose the actor for every tabs event. Session restoration, user actions and other extensions cannot be reliably inferred from an ordinary event. An exposed session identifier only supplies a restoration hint; absence proves nothing. Own operation receipts can be joined to general events using hashed IDs. Unknown actors remain explicitly unknown. No tab closure API exists in this extension's task path. Existing exact profile/tab/window/session admission checks remain.

This audit is implemented and fixture-tested, **not installed or run in Profile 8**. It does not resolve the earlier missing tab or seven new tabs. Baseline/after snapshots and the event ring must cover all three future genuine attempts; truncation/expiry makes provenance incomplete and must be reported. No unrelated tab was newly inspected, adopted, modified or closed in this milestone.

The previous zero-field `read_only / NEEDS_INPUT` plans remain a **no-verified-form result**, not autofill acceptance. Existing fictional form regressions exercise labels/types/required fields, existing values, options/uploads/validation/manual controls/challenges and missing factual answers. No new genuine Naukri DOM observation or supported legitimate employer-form inspection was performed. Correctly classifying the current real page, then separately inspecting a genuine supported form when needed, remains NOT TESTED. No fields were filled or applications submitted.

## Validation matrix

| Requirement | Result | Evidence / next action |
| --- | --- | --- |
| Focus no-op and meaningful-change fencing | PASS, fixtures | Controlled concurrent real local PostgreSQL transactions |
| Pool contention/check-in; lock reuse/release | PASS, fixtures | New timing tests; ancestor rollback coverage; eight PostgreSQL tests |
| Stop, expiry, duplicate IDs, restart and unknown outcomes | PASS, local regression | Expanded backend safety suites; no new production recovery claim |
| Backend | PASS | **392 passed, 42.53s** |
| Disposable PostgreSQL | PASS | **8 passed, 2.96s**, loopback-only isolated databases/roles |
| Extension | PASS | **134 passed, 6.34s**, including bounded audit/privacy tests |
| Frontend | PASS | **284 passed / 37 files, 16.21s**; typecheck passed |
| Explicit RTT benchmark | PASS for completion | **2 passed, 5.55s**; results above, not native acceptance |
| Timing hook recheck | PASS | **3 passed** after idempotence/pool metrics adjustment |
| Ruff E9/F/I, changed frontend Prettier, extension build, diff check | PASS | Local only; stable extension ID preserved |
| Root stage for the three historical timeouts | NOT PROVEN | Capture installed correlated spans after approval |
| New direct remote benchmark | FAIL | Role connection limit before any query |
| Zero live status timeouts/readiness503s on candidate | NOT TESTED | Candidate not installed; no deadline changes |
| Three uninterrupted genuine Open→Prepare attempts | BLOCKED | Exact-SHA approval, capacity preflight, installed workload required |
| Profile 8 routing, service-worker restart, tab provenance on candidate | NOT TESTED live | Existing fixtures pass; installed extension acceptance still required |
| Genuine supported form recognition | NOT TESTED live | No zero-field autofill PASS |
| Locked-screen acceptance | NOT TESTED | Owner-deferred |
| Filling/submission/mail sending | NOT TESTED / disabled | Read-only scope retained |

Initial development runs retained failures from the new eager-checkout method missing in session mocks, missing lifecycle event in an extension mock, incomplete task identity in frontend fixtures, the extra authoritative frontend read, and omitted optional task type fields. The mocks/types were corrected and the final suites above passed. Initial disposable fixture setup used an incorrect role, then `/postgres` rather than the guarded test database; no tests executed until the localhost fixture URL was corrected. One benchmark filename failed collection before renaming. None of these runs are counted as passing coverage. No production data was used for fault injection. No hosted Actions were dispatched.

## Reproduction

```sh
.venv/bin/python -m pytest backend/tests/test_request_timing.py backend/tests/test_browser_forms.py backend/tests/test_reliability.py backend/tests/test_chrome_profiles.py backend/tests/test_execution_naukri.py backend/tests/test_naukri_recurring.py backend/tests/test_naukri_alert_email.py backend/tests/test_telegram_pairing.py backend/tests/test_agent_execution.py backend/tests/test_live_prepare_recovery.py backend/tests/test_local_gmail_discovery.py backend/tests/test_operational_health.py backend/tests/test_config.py backend/tests/test_extension_tasks.py backend/tests/test_packet_telegram_questions.py backend/tests/test_database_safety.py backend/tests/test_phase1_installation.py -q
# Explicitly set PROFILE_TEST_DATABASE_URL to a disposable localhost candidate_profile_test.
.venv/bin/python -m pytest backend/tests/test_reliability_postgres.py -q -s
.venv/bin/python -m pytest backend/tests/benchmark_inspection_contention.py -q -s
pnpm -C extension test
pnpm -C extension build
pnpm -C frontend test
pnpm -C frontend typecheck
```

Private logs stay in the owner-only `status-contention-20261030` folder. Sanitized counts/spans are published alongside this report; raw failure logs and private acceptance receipts are excluded from Git.

## Exact installation / rollback proposal — requires owner approval

1. Review runtime SHA `d504d26e889859b2b39111bb5deedce80c4bd589`. This is a **bounded diagnostic/correction candidate**, not an accepted unattended release. Do not merge. Installation approval must explicitly cover this SHA and the following bounded maintenance/read-only plan.
2. Confirm task PAUSED, no active command, no fill authorization, preserved Profile 8 binding and sending/submission gates. Preserve current runtime/configuration manifests and rollback receipts privately. Pause service processes only within the approved window; retain the original scheduler state. Gracefully quiesce the known Telegram worker if needed to free one known connection for a single session inventory; do not kill unidentified sessions or open a sixth observer. If the five-slot budget cannot be reconciled, stop before cutover.
3. Prepare an immutable release snapshot at the exact SHA, reuse immutable package caches, build frontend/extension, validate dependency/native-host/service paths and unchanged extension ID/permissions, and run the established TLS/role/catalog preflight with only one operator connection. No migrations, cleanup, candidate data edits or Chrome preference replacement. Preserve installed `79ce5f6…` and every historical release.
4. Within approved cutover, update the existing API/native host, execution/Telegram and frontend references to the same reviewed release; reload the existing extension under Profile 8 using the built candidate. Do not create a different browser profile or permanent development clone. Planned restart transport gaps must be timestamped separately. Record exact installed content hashes and restart only the authorized services.
5. Enable the bounded audit in the selected profile's extension service-worker console before the three attempts: `await chrome.storage.session.set({tabLifecycleAudit:{until:Date.now()+600000,salt:crypto.randomUUID(),events:[]}})`. Read the ring locally with `chrome.storage.session.get('tabLifecycleAudit')`; publish sanitized events without salt. Any expiry/truncation is retained as incomplete evidence.
6. Run one HTTP-only observer at the original 12-second status deadline, plus three explicit uninterrupted Open→Prepare attempts. Reconcile original command IDs, receipts, packet/task/profile/tab/window/session and plan identity. No outcome-unknown replay or silent 409 retry. Capture correlated pool acquisition, occupancy, lock and SQL/analysis spans. Stop at capacity errors, unknown outcomes or repeated core failures; do not expand workload. Keep no-form and genuine supported form results separate. Repeat only safety/recovery checks affected by these changes; locked screen stays deferred.
7. If cutover/acceptance fails, first reconcile in-flight command outcomes. Restore the privately backed-up service/native/frontend/extension references to exact previously installed `79ce5f6b514279e6d9022d85b659ad77fb31bd89`, retaining task Pause and all receipts/history; restart only the authorized services. No database rollback, stashes dropped, release deletion, profile reset or authorization restoration. Publish failures and the actual rollback result.

No step above has been performed by this milestone. Full transaction splitting, if spans justify it, still needs a carefully revalidated mutation boundary; it must not bypass packet/profile/task/Stop/expiry checks. Production acceptance remains open.

## Modified files

- `backend/app/agent/store.py`
- `backend/app/browser/chrome_profiles.py`
- `backend/app/browser/extension_tasks.py`
- `backend/app/browser/manual.py`
- `backend/app/browser/router.py`
- `backend/app/browser/service.py`
- `backend/app/core/timing.py`
- `backend/app/dashboard/router.py`
- `backend/app/db/session.py`
- `backend/app/execution/store.py`
- `backend/app/local_agent/native_host.py`
- `backend/app/local_agent/router.py`
- `backend/app/main.py`
- `backend/app/services/applications/packet_builder.py`
- `backend/tests/test_chrome_profiles.py`
- `backend/tests/test_extension_tasks.py`
- `backend/tests/test_live_prepare_recovery.py`
- `backend/tests/test_reliability.py`
- `backend/tests/test_reliability_postgres.py`
- `backend/tests/test_request_timing.py`
- `extension/background.js`
- `extension/build.mjs`
- `extension/tab-audit.js`
- `extension/task-coordinator.js`
- `extension/tests/preview.test.mjs`
- `extension/tests/tab-audit.test.mjs`
- `frontend/src/features/chrome-profiles.tsx`
- `frontend/src/features/extension-assistant.tsx`
- `frontend/tests/chrome-profiles.test.tsx`
- `frontend/tests/extension-assistant.test.tsx`
- `backend/tests/benchmark_inspection_contention.py` (explicit fictional comparison harness in reporting commit)
- `docs/acceptance/status-contention-fix-20261030.md`
- `docs/acceptance/status-contention-fix-metrics-20261030.json`
