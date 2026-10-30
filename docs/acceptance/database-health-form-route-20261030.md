# Database recovery and real application-form route — PR #48

Status at 2026-10-30 15:10 UTC: **capacity remains degraded; installation is blocked**. Controlled quiescence verified that current service shutdown releases its mapped connections, while two older idle backends survive. No unknown backend was terminated. The exact correction is built but uninstalled. Read-only examination establishes that Apply is connected to an authenticated POST workflow, not a proven navigation-only link. No application form or new preparation packet is claimed.

- Repository / branch / base: `karanagg166/automated-apply`, `fix/live-prepare-discovery-20261030`, `main`; [PR #48](https://github.com/karanagg166/automated-apply/pull/48).
- Installed throughout this milestone: [`79ce5f6b514279e6d9022d85b659ad77fb31bd89`](https://github.com/karanagg166/automated-apply/commit/79ce5f6b514279e6d9022d85b659ad77fb31bd89).
- Reviewed, built, **not installed**: [`90f2f2ade50a1c31b26ca85cc7fdf5e93bb67c20`](https://github.com/karanagg166/automated-apply/commit/90f2f2ade50a1c31b26ca85cc7fdf5e93bb67c20).
- Previous evidence remains in [the installed diagnostic and rollback report](status-contention-live-20261030.md). This report does not replace its two profile timeouts or rollback readiness failures with a PASS.

## Actual Mac / online database findings

A system process inventory found exactly one known API, execution worker, and Telegram worker, each pointing to the installed SHA, plus the existing frontend. No older API/worker instance was visible. System-wide PostgreSQL socket inventory found three remote TCP sockets, one per known database service. Local disposable PostgreSQL is a separate fictional test fixture and is not the real-data target.

The runtime uses **direct Supabase PostgreSQL on port 5432 with verified TLS**, not Supavisor transaction pooling. Business settings remain `pool_size=1`, `max_overflow=0`. The intended steady budget is API business + API readiness + execution + Telegram = four connections; frontend has no direct PostgreSQL pool. The role limit remains five. The API readiness pool is independently bounded at one, shares only in-flight probes, and is disposed together with the business pool at graceful shutdown. Workers do not create readiness pools.

At 15:02 UTC, HTTP returned health200 (0.0218s), readiness503 (1.0485s), and profile-status200 (1.8163s), using the original 12-second client deadline. The existing application task was PAUSED without authorization, and no command was queued, leased or executing. No extra database audit was opened before freeing a known worker slot.

One audit connection was used during controlled graceful service quiescence. Current local socket client address/port pairs were matched to database backend address/port pairs; application names alone were not accepted as attribution. Raw tuples, backend PIDs and process inventory remain private.

| Controlled state | Sessions including the one audit | What changed |
| --- | ---: | --- |
| Telegram stopped, exit verified | 5 | Known Telegram socket released; two older idle sessions remain alongside current API, execution, audit |
| Execution stopped, exit verified | 4 | Exact backend matching execution socket disappears |
| API stopped, exit verified | 3 | Exact backend matching API socket disappears |
| All three exited, confirmation after three seconds | 3 | Two older idle sessions plus audit remain; no local production DB socket owns either old tuple |

The two remaining sessions began at 14:35:06 and 14:37:33 UTC, have API/Telegram labels, and last recorded query starts around 14:38:40/44. Both are **idle**, with null transaction start and `ClientRead`; neither is idle-in-transaction. They use an older client address from the earlier private receipt. Their actual originating process identity is **unproven**. They are consistent with orphaned sessions after a network/address change, not evidence that shutdown failed to dispose the current pools. No PID was killed on this inference.

The audit closed at 15:03:11 UTC before the same API/execution/Telegram service definitions were restored. All four LaunchAgents were loaded afterward. The API log explicitly records pool closure, application shutdown completion and old process exit. Telegram and execution have `finally: close_db_engine()`; Telegram session contexts end before long polling and idle waits. Source review found no perpetual database checkout around its network poll. The historical transient execution idle-in-transaction state was not reproduced in this bounded inventory; the configured 30-second idle-transaction timeout remains intact.

Observed server settings on PostgreSQL17.11:

| Setting | Observed value |
| --- | ---: |
| `idle_in_transaction_session_timeout` | 30,000ms |
| `statement_timeout` | 30,000ms |
| `idle_session_timeout` | 0 |
| `tcp_keepalives_idle` | 1,800s |
| `tcp_keepalives_interval` | 60s |
| `tcp_keepalives_count` | 9 |
| `tcp_user_timeout` | 0 |
| `client_connection_check_interval` | 0 |

These settings allow delayed dead-peer cleanup: approximately 39 minutes from the last relevant TCP activity under the documented keepalive model. Query timestamps are not TCP packet timestamps, so this is a **bounded diagnostic expectation, not a guaranteed expiry time**. One natural-cleanup observation window is pending; repeating restarts does not recover those two sessions. No limit, credentials, database defaults, schema, runtime connection options or production application data were changed by the investigation.

Primary references: [PostgreSQL17 TCP connection settings](https://www.postgresql.org/docs/17/runtime-config-connection.html), [Supabase direct/session/transaction connection modes](https://supabase.com/docs/guides/database/connecting-to-postgres). Direct and session connections support the session/prepared-statement behavior this backend requires; switching to transaction pooling is not a drop-in recovery.

## Exact90f2f2a review and preparation

The correction replaces each project fingerprint's repeated configuration/project reads with one column-select snapshot of configuration and both repository/document approval namespaces. It passes a copy-returning, write-denying adapter to the **same** `approved_projects` logic. That logic still requires a candidate, an approval, identical candidate/approved revision and identical current project configuration. Priority/order, document-only configuration and missing/pending approvals retain their existing meaning. Each fingerprint call executes fresh SQL; no cross-request authorization cache exists. Selecting columns avoids stale ORM identity-map objects.

Fingerprint creation and final `FormService.fresh` remain separate calls. Packet revision, context digest, destination, plan expiry, reviewed answer revision/expiry and canonical resume bytes are still checked. Task loading flushes and refetches current state; expected task revision, profile/session/window/tab/plan bindings, command/lease expiry and owner Pause/global Stop gates remain. The existing narrow allowance for fresh inspection after focus-only pause is unchanged; it does not permit filling after owner Pause/Stop. `074fb82`'s lazy checkout remains: no eager `session.connection()` was added. No additional engine, slot, deadline increase or automatic replay was introduced.

The previously measured remote fingerprint routine remains **10 reads /1.653633s → one read /0.457622s, identical digest**. That is earlier real routine evidence, not a new corrected full-inspection benchmark. No real candidate values or digests are published.

New validation in this milestone:

| Validation | Exact result | Scope |
| --- | --- | --- |
| Fingerprints, timing/lazy checkout, stale plan/task, expiry, Pause/Stop | **22 passed in2.63s** | Isolated fictional SQLite/unit fixtures |
| Probe pool disposal/in-flight sharing and Telegram outage lifecycle | **4 passed in4.47s** | Isolated fixtures; Telegram transport mocked, no real messages sent by tests |
| Five-slot budget and SQL-free rejection under actual pool contention | **2 passed in0.82s** | Disposable localhost PostgreSQL only |
| Ruff E9/F/I and diff check | PASS | Reviewed fingerprint/session/timing files |
| Exact candidate build | PASS | Independent Python venv, constrained to prior dependency versions, pip check; offline frozen pnpm installation; frontend and extension builds |

An initial disposable PostgreSQL invocation selected a nonexistent local role and produced **two setup errors in0.32s**. The fixture's saved connection metadata supplied the correct role; the corrected two-test run passed. This did not connect to production and is not omitted from the record. Previous494 backend passes are prior evidence, not added to this milestone's28 passes. No broad unrelated suite, infrastructure benchmark, hosted Actions run or new fault-injection acceptance loop was run.

The registered linked immutable candidate worktree is at exact90f2f2a and has an independent environment/build. No mutable dependency/build directory was symlinked into a release. Nine current static installation/private-configuration files match the prior rollback hashes and now have a separate private backup. Prepared plan files change only six installed service/native/frontend references to the candidate; native host identity remains unchanged. The candidate extension has not been loaded. Existing installed/historical releases, credentials, data and rollback backups remain preserved.

## Genuine page / Apply inspection

Read-only DOM inspection used the existing Chrome window/tab associated with the saved Profile8 task. No new browser, profile, navigation, tab closure, form edit, field authorization or button activation was performed. The inspected [public job](https://www.naukri.com/job-listings-backend-developer-naukri-e-hire-gurugram-0-to-2-years-261026028027) still has **zero forms, zero frames and zero file inputs**. Three visible text inputs are job type, keyword/company and location search controls; all are optional, empty and valid. They are not an application questionnaire. No required application answers, attached resume or application validation state can be established from this document.

Two visible enabled Apply controls have duplicate `apply-button` IDs. Both are `<button>` elements with no explicit type attribute, no form association, no href and no inline `onclick`. The browser's default `type` property is `submit`, but without a form that does **not** establish the effect of the site's script. Direct DOM handler metadata exposed no handler in the available script world; that absence is not proof of no handlers. Canonical/base URLs point to the same job-details page; history provides no reviewed form destination.

Read-only GETs of the exact **public JavaScript assets already listed by the page** independently establish a click workflow. The [job-details bundle](https://static.naukimg.com/s/9/121/_next/static/chunks/app/jd/page-3579924741a096ea.js) registers the Apply selector with a job-specific workflow payload. Its loaded [workflow utility](https://static.naukimg.com/s/9/121/_next/static/chunks/nkworkflowutility.93cf0c49ad6c7e94.js) binds click listeners and issues an authenticated credential-including POST before processing the response/chatbot/redirect. The job-details bundle also contains conditional company-follow PUT behavior. Bundle hashes and bounded source findings stay private; no browser cookies, tokens or candidate details were copied into those requests or public evidence.

This establishes **a route toward a workflow/questionnaire, not navigation-only safety**. It does not establish which backend branch this exact job/account will take, whether an application is immediately recorded, or whether questions precede submission. No speculative destination was opened and no POST endpoint was called. No real form preparation packet was created in this milestone; the prior zero-field plans remain no-form evidence.

The smallest owner action authorization, if desired after review, must explicitly cover **one activation of this job's Apply control in Profile8, including possible immediate application submission using the site's current profile/resume and any enabled company-follow write**. Read-only/preparation permission does not cover that risk. A preparation-only alternative is an independently obtained genuine questionnaire/form URL with no auto-apply parameters; inspect that destination read-only first. Do not append `showLB`/`regToApply` or similar parameters: the loaded code can auto-invoke the workflow on page load.

## Exact installation preflight and bounded continuation

**Not an installation authorization. Do not execute cutover while capacity is degraded.** Before asking the owner to approve installation, complete and publish the dated capacity result and finish the candidate/rollback plan review. Required preflight for exact90f2f2a:

1. Confirm all current installed references still point to exact79ce5f6 and all nine static backup hashes match. Keep every old release and all raw evidence. Confirm the candidate's tracked runtime source matches the exact reviewed SHA, pip check/builds pass, extension identity/permissions match, and no schema migration is required.
2. Use HTTP to verify the selected Profile8 binding, PAUSED task without authorization, and zero queued/leased/executing commands. Obtain a fresh task revision at each later admission; do not carry revisions through cutover.
3. With normal services healthy, use **one** bounded read-only operator connection and client-address/port mapping to inventory the role. Require exactly the intended four runtime backends plus the audit under the unchanged limit5, no unidentified extra backend, and no idle-in-transaction leak. Close the audit before workload. A readiness200 alone does not prove the operator slot exists.
4. Require a bounded HTTP-only healthy window at the unchanged12s deadline, covering pool recycling, with no unexpected readiness503, connection-limit failure or status timeout. Planned quiescence startup gaps are separate and must remain in receipts. If capacity remains degraded, stop installation and propose targeted provider/owner diagnosis; no blind termination or limit increase.
5. Obtain explicit owner installation approval for **full SHA90f2f2ade50a1c31b26ca85cc7fdf5e93bb67c20**, preserving exact79ce5f6 rollback. After approval, gracefully stop only known services, verify exits/ports, atomically install the reviewed six references, restart API and then other services, verify native health and unchanged Profile8 selection, and explicitly load the same-identity candidate extension through Chrome. No new permission, role/pool change, production data restoration or merge is included.
6. Only after healthy post-install budget verification run **three genuine consecutive Open→Prepare cycles**. Use one HTTP-only observer and original12s status deadline. Retain every original command/terminal outcome, no hidden retry; preserve unrelated tab IDs/windows/URLs; reconcile commands and Pause after each cycle. Stop on a critical capacity/timeout/unknown-outcome failure rather than repeating the loop.
7. A no-form plan is not application-preparation success. Keep Apply untouched until its separate action authority is resolved. At a genuine form, inspect fields, required questions, existing values, resume attachment and validation without submission, then persist and verify the actual preparation packet. Any additional runtime correction needs a new reviewed SHA. Rollback restores only reviewed references/content after command reconciliation, never stale authorization or database history.

Reproduction of focused review tests: `backend/tests/test_project_stamp_snapshot.py`, `backend/tests/test_request_timing.py`, the stale-plan case in `test_browser_forms.py`; task-revision/expiry/Stop cases in `test_chrome_profiles.py` and `test_extension_tasks.py`; the three named lifecycle cases in `test_reliability.py`. Disposable PostgreSQL command:

```sh
# Set PROFILE_TEST_DATABASE_URL from the existing disposable fixture metadata only.
.venv/bin/python -m pytest \
  backend/tests/test_reliability_postgres.py::test_four_runtime_pools_and_one_operator_fit_five_slot_role_budget \
  backend/tests/test_reliability_postgres.py::test_native_identity_rejection_does_not_wait_for_database_checkout -q
```

Raw scripts, exact commands, receipts, source hashes and build/test logs remain restricted under the owner's private `database-health-20261030` evidence directory. No candidate PII, resumes, Gmail contents, environment values, socket addresses, browser secrets or raw screenshots are published. CPU/RSS comparisons were not measured in this investigation; the earlier non-identical resource comparisons remain qualified in the prior report.

## Acceptance matrix

| Requirement | Status | Current evidence / next action |
| --- | --- | --- |
| Identify current process-owned connections | PASS | Full TCP tuple mapping plus backend disappearance on verified graceful exit |
| Identify actual owner of two older sessions | BLOCKED | Labels/address/history insufficient; no termination authorized/performed |
| Dispose current API/worker pools | PASS for measured exits | Known backends disappear; API shutdown/pool logs agree |
| Stable readiness and four-runtime-plus-audit budget | FAIL / recovery pending | Initial readiness503; natural cleanup observation pending |
| Exact90 approval/freshness/lazy-checkout review | PASS for review/tests | 26 isolated unit cases and2 disposable PostgreSQL cases |
| Candidate build and rollback preparation | PASS, uninstalled | Exact candidate built; nine backups verified; six reference plans prepared |
| Exact90 installation | BLOCKED | Healthy capacity and explicit exact-SHA approval required |
| Three new corrected live cycles / zero12s timeouts | NOT TESTED | No installation or loop attempted |
| Genuine Apply metadata/source inspection | PASS read-only | Authenticated POST workflow established; navigation-only safety not established |
| Genuine form / required answers / resume / saved packet | BLOCKED | No genuine form reached; no success claimed |
| Submissions, company follow, Gmail sending | NOT AUTHORIZED / NOT PERFORMED | Separate explicit owner action authority required |
| Hosted Actions / merge / cleanup | NOT PERFORMED | Manual-only workflow triggers preserved; no deletion |
