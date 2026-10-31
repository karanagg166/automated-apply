# Approved installation, genuine discovery and compatibility failures — OPEN

This is an installation and failure-diagnosis milestone, **not successful Naukri
submission acceptance**. There were **zero new real submissions**, zero new receipts
and zero QTrino replays. The historical receipt remains recorded once.

- Repository/PR: [karanagg166/automated-apply #48](https://github.com/karanagg166/automated-apply/pull/48), base `main`.
- Source branch: `fix/live-prepare-discovery-20261030`.
- Compatibility implementation: [`70dad04b5235e1232e2b1fffc38a47a68cf8a013`](https://github.com/karanagg166/automated-apply/commit/70dad04b5235e1232e2b1fffc38a47a68cf8a013)
  (not installed).
- **Installed API/frontend/execution/Telegram/native:** owner-approved
  `ee8c591b382626f657f3e99f2e757c303ec217b0`.
- **Loaded Profile 8 extension:** that same approved SHA, version **1.3.3**,
  stable ID `gdjbmkffcpicbpiikcohlmokkmcpipgp`.
- Source extension version **1.3.4** is built/tested in development, **not installed**.
- [Sanitized measurements and changed-file inventory](naukri-installed-ee8-audit-metrics-20261031.json).

## Before and after installation

Before this continuation, services/native referenced `90f2f2a`; Profile 8 loaded
`b069092`. The queue, native profile binding, preparation worker, canonical
encrypted resume, Telegram question infrastructure and the genuine historical
receipt already existed. The approved `ee8c591` added a guarded direct-Apply
candidate, provider PDF verification through a supported link, quota admission,
unknown-outcome reconciliation, two-document history receipts and summary-only
profile sync. Those capabilities had passed fictional tests, not live acceptance.

The owner explicitly approved installing `ee8c591`, a new eligible real submission
test and subsequent bounded automation after genuine success. No merge or cleanup
was authorized or performed. Six existing installation references were replaced:
four LaunchAgent plists, the frontend launcher and native wrapper. Private env,
native origin/manifest, credentials, browser profile, application data and all old
releases were retained. No DDL, new daemon, broker, pool increase or provider budget
increase was introduced. Gmail remains READ + CREATE DRAFT only.

After the owner asked the agent to handle Chrome setup, the agent used Chrome's
ordinary Load unpacked dialog in the existing Profile 8 window. The stable deployment
directory is `~/Library/Application Support/Automated Apply/chrome-extension`.
All **21/21** files match the approved build, with no extra files. Chrome's persisted
path matches; the manifest key/ID and existing permissions are unchanged. Its API
permission set remains seven permissions; the active explicit host grant remains
`https://www.naukri.com/*`. New authenticated `poll_naukri_work` activity and native
heartbeats establish runtime use beyond a disk comparison. A complete Chrome Errors
panel inspection was not obtained; no claim that the panel was empty is made.

The installation had a sequencing defect: a 25-second old-process exit guard failed,
but the next tool operation nevertheless replaced references and attempted API
bootstrap. Follow-up verified old processes had exited, no old listeners remained
and only the new runtime was running before continuing. This was acknowledged to
the owner. Future cutover must resolve the exit guard before replacing/bootstrap.

## Actual installed observations

| Check | Result | Actual evidence / limitation |
| --- | --- | --- |
| Approved service/native references | PASS | All six references use exact `ee8c591`; previous artifacts retained |
| Stable extension identity/load | PASS | 21/21 files, persisted Profile 8 path, same ID/permissions, native activity |
| Initial readiness | FAIL then PASS | Initial HTTP 503 `database_unavailable`; later HTTP 200 about 3.143 s; failure retained |
| Database role budget | PASS snapshot | Four service/readiness sessions plus one read-only audit session; role limit five; not a long-running capacity proof |
| Local canonical resume | PASS | Confirmed primary encrypted PDF decrypted locally and checksum verified, 100,198 bytes; no resume bytes published |
| Normal UI discovery | PASS one cycle | 20 genuine URLs persisted; about 76 s from source start to committed batch; not 20 eligible jobs |
| Native discovery response deadline | FAIL | Finish response timed out, then read-only batch committed; no write authority or Apply attempt |
| Installed listing parser | FAIL | `job_required_facts_unrecognized` on at least five observations; actual modern header classes differ from fixtures |
| Status latency | FAIL | 12-second status/profile reads timed out during work; later stopped-state GETs 200 in 4.929/6.296/6.447 s |
| Stop responsiveness | FAIL | Original 12-second request timed out; later operational request completed in 26.05 s; deadline was not changed to relabel acceptance |
| Final durable queue | PASS stopped | `STOPPED`, revision 4; 20 paused messages, one historical recorded receipt, zero active commands |
| Current account identity | BLOCKED | Visible Naukri email differs from canonical verified email; login-alias confirmation requested; neither email changed |
| Provider-side selected resume | BLOCKED | Real UI has a Download button without the explicit link supported by installed verifier; filename is insufficient proof |
| Genuine profile sync | NOT TESTED | Compare-only configured; no completed provider comparison record, zero writes; stopped with `global_stop` |
| New employer submission/receipt | BLOCKED | Zero new submissions/receipts; no uncertain Apply was retried |
| Continuous automatic applications | BLOCKED | First genuine success and critical acceptance prerequisites not met; not activated |
| Locked-screen services | FAIL readiness | Three actual locked samples: API/database/liveness passed and worker heartbeat advanced; readiness 503 in all three |
| Locked-screen application/browser journey | NOT TESTED | No locked Apply/fill/upload claim |

The observed diagnostic listing was several weeks old, had a lower-bounded applicant
count and an external company-site Apply control. It is not an eligible live test.
No dates, applicant upper bounds, salary or qualifications were invented to admit it.

The account comparison used the visible profile contact email and a read-only
canonical database query. This establishes different emails, not that the human
owner is different. The owner must identify whether the selected login is an approved
alias or another account should be used. Canonical contact email and portal login
identity must remain separate; silently changing either to satisfy a comparison is
not acceptable. The owner's explicit mismatch-stop instruction applies.

## Actual awake-and-locked service observation

The owner session was observed naturally locked; the agent did not lock/unlock it.
The installed, approved release's read-only monitor recorded three samples beginning
09:37:36 UTC, 09:38:06 UTC and 09:38:36 UTC. Each had the correct user's macOS lock
telemetry `LOCKED` both before and after its requests. The bounded monitor exited 0.

API, direct database read and liveness passed **3/3** each. The execution worker's
persisted heartbeat advanced across all three samples while its automation was
stopped. Readiness failed **3/3**, HTTP **503**, in 3.816, 1.663 and 1.338 seconds.
These are retained acceptance failures. The monitor adds one database connection
against an already constrained role. After it closed, liveness returned 200 in
0.034 s, readiness 200 in 3.010 s and profile status 200 in 2.241 s; the selected
extension remained CONNECTED with a later authenticated heartbeat. An observer
effect is possible; the failures
cannot be attributed to screen locking from these observations. No pool/timeout was
increased. No genuine locked browser form, upload, submission, Telegram round trip,
restart recovery or continuous discovery cycle was exercised by this monitor.

## Compatibility implementation, not installed

`70dad04` changes the existing execution queue, native discovery finish, observation
contracts, site adapters, dashboard date display and their regression tests:

- A bounded 20-URL batch performs receipt/uncertain-packet checks, capacity checks,
  canonical requisition deduplication and transactional outbox publication using
  set-based SQL. Existing or damaged receipts and uncertain submissions remain fences.
- Stop/Resume event writes are batched in the same transaction as state changes;
  an unknown submission never becomes ordinary resumable work.
- Current layout uses the full `#job_header`, the company link excluding ratings,
  actual experience class and nested applicant label. Sticky title duplicates
  cannot become the primary header. Legacy fixtures remain supported.
- Read-only hydration absence is retried at most nine observations, 250 ms apart;
  challenges, changed context, owner adoption and writes are not replayed.
- A calendar posting date remains a date with exact time unknown. Eligibility uses
  the earliest possible instant across civil timezone offsets for a conservative
  age bound; it never stores that bound as an observed posting timestamp. Dates
  crossing the eligibility boundary require review. The dashboard labels unknown time.
- API types were regenerated. No migration or permission expansion is required by
  these compatibility changes.

This patch does **not** implement the real Download-button verifier, recurring
screening questionnaires, resume replacement, broader profile writes or a verified
login-alias binding. Those remain required before claiming the complete requested
pipeline. Source code presence is not evidence those live paths work.

## Local validation

| Suite | Final result | Scope |
| --- | --- | --- |
| Backend | **377 passed, 0 failed**, 16 files, 29.26 s | Fictional isolated tests |
| Frontend | **292 passed, 0 failed**, 38 files, 11.13 s | Fictional UI/contracts |
| Extension Node | **159 passed, 0 failed**, 6.616 s | Fictional DOM/native routing |
| PostgreSQL queue | **8 cases passed**, 0.222 s | Fresh loopback PostgreSQL 14.24, two-connection pool; concurrent 20-item duplicate batches and Stop included |
| PostgreSQL application/profile record | **2 cases passed**, 0.526 s | Fictional committed worker/receipt journey, independent connections |
| Chromium queue | **4 cases passed**, 5.539 s | Real inactive Chromium tabs, fictional current/legacy layouts, provider DNS blocked |
| Chromium execution | **12 cases passed**, 6.434 s | Fictional direct Apply, current header, wrong account/CV, single-use click, independent receipt documents |
| Build/static checks | PASS | Frontend production build/typecheck, extension build, OpenAPI regeneration, targeted Ruff/Prettier, diff check |

Browser: Chromium `156.0.8078.4`; **zero live provider requests** in browser regression
tests, zero unexpected requests and zero file chooser events. These counts are
separate from genuine owner-profile browser inspection and discovery above.

Five focused batch tests were also run with SQL-count properties; they overlap the
377 backend tests and are not added to that total. One candidate and twenty candidates
each used **8 SQL statements**; fencing twenty items used **5 statements** in that
isolated check. This demonstrates bounded database round trips. It does not establish
new production latency: the compatibility patch remains uninstalled. The previous
installed discovery took about 76 seconds and Stop 26.05 seconds, both failures to
resolve. Pools/deadlines were not increased. RAM/long-running throughput was not
benchmarked. The prior suite had 367 backend tests in 28.69 s, so the expanded suite
is not an equal-workload speed comparison.

Initial regression runs exposed 40 backend failures from an accidental validator
edit and two extension failures (version assertion and company-rating contamination).
Those defects were corrected before the implementation commit and the final suites
above passed. A diagnostic HTTP fetch timed out and AppleScript execution could not
establish hidden-page semantics; neither was called live adapter acceptance.

Reproduction from the primary source checkout:

```sh
.venv/bin/pytest backend/tests/test_application_queue.py backend/tests/test_naukri_background_queue.py backend/tests/test_naukri_batch_admission.py -q
pnpm -C extension test
pnpm -C extension exec node tests/naukri-queue.browser.mjs
pnpm -C extension exec node tests/naukri-execution.browser.mjs
pnpm -C frontend test
pnpm -C frontend typecheck
pnpm -C frontend build
pnpm -C extension build
```

The PostgreSQL verification CLIs require fresh disposable loopback databases and
reject production targets. Run `verify_application_queue_postgres.py --url` against
fresh `candidate_profile_test`, and `verify_naukri_submission_postgres.py --url`
against a separate fresh `candidate_profile_test_submission_<suffix>`, on an isolated
nondefault port. The ephemeral cluster used here was stopped afterward. Raw private
logs, pages, account comparisons, PDFs and installation inventories are not published.

## Activation and rollback

The installed snapshot remains fixed at
`$SUPPORT/release-candidates/ee8c591b382626f657f3e99f2e757c303ec217b0`, where
`SUPPORT=~/Library/Application Support/Automated Apply`. Do not relocate its venv.
The reviewed installation/rollback artifacts are in
`$SUPPORT/installation-plans/master-ee8c591b382626f657f3e99f2e757c303ec217b0`.
All historical releases remain protected. This report is not approval to install
the newer source commit, merge PR #48 or remove anything.

Rollback procedure:

1. Keep Stop active; inspect all active and unknown commands before any browser work.
2. Gracefully boot out Telegram, execution, frontend and API LaunchAgents. **Require
   confirmed PID exit** before proceeding. Resolve a failed exit guard first.
3. Verify preserved `*.previous` artifact hashes against the private plan. Restore
   only the four previous plists, previous frontend launcher and native wrapper
   atomically, preserving modes. Do not restore an old environment over newer owner
   changes. The native manifest and credentials were unchanged by this installation.
4. Bootstrap API, frontend, execution and Telegram and check authenticated health,
   readiness and profile routing. This restores the former `90f2f2a` service/native
   references; it does not roll back database/application history.
5. For extension rollback, preserve the same ID and profile. Use standard Chrome
   controls with the protected `b069092.../extension/dist` directory and verify the
   loaded path/permission/native handshake; do not delete the current deployment
   folder or edit immutable releases. Keep automation stopped during mixed-version
   checks. No rollback was performed in this continuation.

After the account mapping, supported saved-resume verification, form support and
installed acceptance are resolved, use dashboard **Naukri → Background queue**:
configure Naukri sources/filters/caps, choose the one-application supervised scope,
enable submission authorization, save and Start. The owner already authorized that
one eligible real test; no new per-job general approval is needed. Independently
persist its receipt before setting AUTOMATIC and restarting with conservative caps.
Do not raise owner limits automatically. Pause/Stop remain available. **Do not
activate now**: current account and resume preconditions remain unresolved. Other
platforms remain outside this milestone; do not activate Wellfound or Gmail sending.

Next required actions: resolve the login identity with the owner, implement and
verify the actual supported resume control, install a reviewed exact-version patch,
re-observe eligible fresh listings, complete the genuine application/receipt journey,
then repeated bounded cycles, recovery and locked-browser acceptance. The Naukri
phase remains **OPEN**.
