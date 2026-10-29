# Phase 5.3 focused validation

PR #45's subsequent review is recorded in the
[case-by-case failure classification and bound Prepare verification](pr45-review-followup.md).
That report distinguishes the intermediate accidental run from the supplied
`ec432ba` head, compares only affected files with the base, and records the
background-tab/window regression. The original engineering evidence below is
historical; it is not a new full-suite or live-acceptance claim.

All automated profiles, employers, questions, servers and test databases are
fictional. Genuine observations and the one private review draft are recorded
separately in [acceptance](acceptance.md). No complete backend/extension suite or
hosted workflow was run. One frontend invocation accidentally forwarded `--`
through pnpm's script runner and ran all 268 frontend cases (247 passed, 21 failed,
11 unhandled fixture errors). This violated the intended focused-only scope and
was not repeated. Affected fixture expectations were corrected for the explicit
executor choice and new profile endpoint; subsequent explicit-file runs are below.

## Backend and contracts

The focused files are:

```sh
python -m pytest backend/tests/test_execution_naukri.py \
  backend/tests/test_naukri_application_capabilities.py \
  backend/tests/test_packet_telegram_questions.py -q
```

The 99-case run passed. Six final expiry/currentness checks passed after separating
expired evidence from malformed evidence, adding two new cases (101 distinct
backend cases across the focused runs). These cover canonical posting imports,
range validation, requisition deduplication, matching, stale packet criteria,
closed/expired native destinations, prior applications, no automatic question
queue, owner-only reply correlation, revision locking, pause/cancel, and unknown
Telegram delivery without a duplicate send. Tests deny genuine network calls.

```sh
python backend/scripts/export_openapi.py
pnpm -C frontend api:types
pnpm -C frontend typecheck
```

OpenAPI regenerated; generated `ImportJob` types include reviewed destination,
posting status, timestamp and expiry. Typecheck passed. Changes add optional
review evidence; owner-supplied facts never become provider-verified claims.

## Frontend

```sh
pnpm -C frontend exec vitest run tests/naukri.test.tsx \
  tests/applications.test.tsx tests/field-review-experience.test.tsx
pnpm -C frontend build --webpack
pnpm -C frontend exec playwright test --config playwright.naukri.config.ts
```

46 affected unit tests passed. Production webpack build and one production UI
Chromium journey passed. The latter uses intercepted fictional API responses and
checks historical account status, unknown experience, delivery-unknown display,
exact revisioned pause/resume/cancel, no implicit mutations and a fictional
screenshot. It makes no real backend, employer or mailbox request.

The engineering worktree uses an external dependency symlink. As documented for
Phase 5.2, webpack builds successfully but standalone tracing warns about files
outside its root; `next start` emits its existing standalone-output advisory.
A separately approved immutable release must install its own dependencies before
building the deployment artifact. No build configuration workaround is committed.

## Extension/native and Chromium

```sh
node --test extension/tests/naukri.test.mjs extension/tests/phase52-form-dom.test.mjs
node --test extension/tests/ui.test.mjs
node extension/tests/phase53-naukri.browser.mjs
pnpm -C extension build
PYTHON=/ABSOLUTE/EXISTING/TEST/PYTHON node extension/tests/assistant-native.browser.mjs
```

- 19 Naukri/shared-DOM unit cases passed: search exclusion, explicit form/dialog
  scope, unknown drawers, login, field identity, retention, partial cancellation,
  stale forms, custom controls and unsupported background activity.
- Two popup/settings unit cases passed, including loaded version and granted,
  missing or unverified network-blocking permission states.
- Three fictional isolated-world Chromium Naukri-shaped DOM cases passed: header
  search cannot become an application, one selected field retained after events,
  existing values preserved, stale snapshot and refresh rejected. There were zero
  form submissions or employer write requests. This is not a genuine Naukri fill.
- Seven real isolated MV3/Python-native cases passed with a fictional HTTP backend,
  including browser restart, fresh-review requirements and duplicate rejection.
  Settings also checks the actually loaded test bundle version and the real Chrome
  DNR grant. Temporary native manifests live only in the disposable test profile.
- Seven selected coordinator/DOM permission/interruption checks passed using:

```sh
node --test --test-name-pattern='interactive cancellation|fresh inspection during|permission declined|Open refuses|dashboard cancellation|browser restart|bound navigation' \
  extension/tests/phase52-form-dom.test.mjs \
  extension/tests/network-guard.test.mjs \
  extension/tests/task-coordinator.test.mjs
```

## PostgreSQL concurrency

`backend/scripts/verify_execution_postgres.py` passed against a fresh disposable
PostgreSQL 17 container, using the cached image with `--pull=never`, a random
loopback-only port and fictional credentials. Eight concurrent intent requests
produced one attempt; eight claims produced one lease. Pool restart, fencing,
pause/resume, uncertain dispatch and the durable outbox passed. It made zero
employer requests. The container and child fixture database were removed.

The first attempt reached PostgreSQL's temporary initialization server before its
final TCP listener was ready and failed connection establishment. The successful
rerun waited for `pg_isready -h 127.0.0.1`; no production configuration or TLS
policy was relaxed. This is ORM concurrency evidence, not a production migration.

## Failures and limitations

The first native browser fixture encountered its extension-created initial
navigation racing Playwright's fixture navigation. Setup now retries only that
specific competing-navigation error; all DOM/native/recovery assertions still
must pass. The focused rerun passed. No functional assertion is skipped.

Chrome's extension pages did not return usable results through AppleScript page
scripting in the owner browser, and the macOS UI-control interface did not expose
clickable elements. No successful owner-profile DNR/native check is inferred
from those attempts. The owner confirmed that installed extension 1.3.0 is enabled;
the new 1.3.1 version/permission display was verified only in isolated Chromium.
A current actual portal/health receipt remains an owner-driven acceptance step.

Changed-file Ruff (`--isolated --select E9,F,I`), Prettier and whitespace checks
passed. Private/runtime hashes and primary checkout state are rechecked before
publication. The genuine job/packet addition is intentionally retained in the
approved database; candidate profile/resume data and private configuration are
not modified. No genuine fill, upload, submission or Telegram message was sent.

## Selected Chrome profile integration

The profile-reuse work is part of this same Phase 5.3 branch and PR. See the
[execution design and root cause](chrome-profile-reuse.md).

- The affected backend files (`test_chrome_profiles`, `test_extension_tasks`,
  `test_extension_answers`, `test_browser_forms`) passed 79 cases before the final
  historical-receipt regression. The final 12-case profile file passed after the
  receipt change. This covers binding credentials, two profiles, selected-only
  claims, stale selection/profile/task/packet versions, expiry, no redelivery,
  explicit transfer, restart, disconnect, owner auth, Telegram correlation,
  default executor routing, late partial receipts and native credential redaction.
- Seven affected frontend files passed 66 cases. After adding historical receipt
  display, the three affected packet/profile files passed 44 cases. No other
  frontend files were rerun after the accidental full invocation noted above.
- Final coordinator/form/native UI/network guard checks: **44 passed**, including
  expired commands and revoked-origin preparation before DOM access. The broader
  initial affected extension run passed 58 cases. No full extension suite ran.
- MV3 → Python native host smoke: **7 cases passed**, with one retained fixture
  receipt, zero employer write requests and zero submissions. It uses a fictional
  HTTP backend; it is separate from the genuine PostgreSQL stack below.
- `chrome-profiles.browser.mjs` passed with **two simultaneous real MV3 Chromium
  profiles → Python native host → authenticated FastAPI → disposable PostgreSQL 17**.
  Only selected A received the first Open/inspection. Six concurrent retries
  deduplicated to one command; repeated Open reused the same window/tab. An exact
  fixture field approval produced retained values and a database receipt while
  preserving manual input and sending zero employer writes/submissions. Explicit
  switch routed the next Open to B. CDP stopped the actual B service worker;
  trusted wake required fresh inspection with the same session. Closing and
  reopening B preserved its binding UUID, rotated its session and cleared old
  tab/plan authority. An expired heartbeat returned `PROFILE_OFFLINE` and paused.
  Independent SQL checked two bindings, retained receipts and zero submitted packets.
- Explicit isolated-browser smoke: **15 passed, 10 deselected** (inspection states,
  redirects/crash/restart/stale documents, and rejection of everyday profiles).
  One changed opening API/auth/permission/revision/CSRF contract check passed,
  13 deselected. Playwright is selected explicitly for these fictional tests.
- Production build and final typecheck passed. Generated API types include the
  profile list/selection/commands, exact executor choice and plan/task profile
  identity. Two production Chromium UI journeys passed with fictional API fixtures;
  the profile screenshot is [here](screenshots/chrome-profiles-fictional.png).

Reproducible focused invocations:

```sh
python -m pytest backend/tests/test_chrome_profiles.py \
  backend/tests/test_extension_tasks.py backend/tests/test_extension_answers.py \
  backend/tests/test_browser_forms.py -q
node --test extension/tests/task-coordinator.test.mjs \
  extension/tests/form-bridge.test.mjs extension/tests/ui.test.mjs \
  extension/tests/network-guard.test.mjs
pnpm -C extension build
PYTHON=/ABSOLUTE/EXISTING/TEST/PYTHON node extension/tests/chrome-profiles.browser.mjs
pnpm -C frontend exec vitest run tests/chrome-profiles.test.tsx \
  tests/browser-policy.test.tsx tests/browser-assistant-improvements.test.tsx \
  tests/phase4-job-dashboard.test.tsx tests/local-connections.test.tsx \
  tests/applications.test.tsx tests/field-review-experience.test.tsx
pnpm -C frontend build --webpack
pnpm -C frontend typecheck
pnpm -C frontend exec playwright test --config playwright.naukri.config.ts
```

Integration failures were corrected without skipping functional assertions:
initial navigation could arrive after tab binding and pause a new task; Open now
waits for its requested load before binding. Profile transfer initially attempted
an old-profile task read; explicit Open now checks its expected task version at
transfer. Heartbeats are serialized so opt-in ordering cannot regress. Browser
session rotation now clears numeric tab identity on the first authenticated new
heartbeat, before local recovery finishes. The test explicitly enables interactive
retention only for its separately approved fictional fill; assignment-only receipts
were correctly kept unverified. Fixture assertions were corrected for exact worker
restart reason names and Playwright exact text matching.

No installed profile, native wrapper, live private env, service definition, existing
candidate fact or resume was changed by these tests. Actual personal/job Chrome
connection and read-only execution with the new release, real permission revocation,
and genuine Telegram delivery remain separately approved live acceptance steps.
