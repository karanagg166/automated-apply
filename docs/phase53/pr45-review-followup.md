# PR #45 review follow-up

Reviewed starting head: `ec432baf7eae5393e7c15aa472b25cfd3eb21f46`.
Comparison base: `8c1635139a8943e9c2b72f39c4db593e1ccaa5b5`.

## Accidental frontend run: all failures classified

The original, saved local log is `reports/chrome-profile-frontend-tests.log`
(SHA-256 `f2aa10aaa2ee35ab6fd3ef2bae92f74b2015dfe009cd41e4e4d96c83aa6e5895`).
It records 247 passes, 21 failures and 11 unhandled errors. It was captured during
implementation, before the fixture/expectation fixes in the starting head; the
log does not record a Git SHA. It must not be presented as an exact-head run.
Logs stay local and ignored; this report records their non-private findings.

Only its six failing files were rerun at the base: **61 passed**, no unhandled
errors. Those six plus the new profile file were rerun at the supplied head,
before making follow-up code changes: **66 passed**, no unhandled errors.
Saved evidence: `reports/pr45-baseline-frontend.log` and
`reports/pr45-exact-head-frontend.log` (verbose case names in each).

Classification: **0 baseline test failures reproduced; 21 fixture/expectation
integration failures, already resolved at the supplied head; 0 production
regressions demonstrated by these 21 failures.** All 11 unhandled errors have the
same fixture response-shape cause. This does not assert that untested cases or
an entire suite pass. The active-tab bug below is a separately reproduced
production regression, outside those 21 frontend cases.

The classifications below use three specific causes:

- **Endpoint fixture**: a broad API mock returned packet, connection or legacy
  policy data to the newly mounted `browser/chrome-profiles` query. That payload
  lacked `profiles`, crashing `ChromeProfiles` and sometimes unmounting the test's
  form. Existing head validates the response shape before using it. Empty DOM,
  detached assertions, inability to focus an answer and missing generation calls
  are downstream symptoms; they do not establish separate answer logic defects.
- **Executor expectation**: a legacy browser test mounted the new extension
  default but asserted isolated-browser controls. Its fixture now explicitly
  selects **Use isolated automation browser**. Original safety assertions remain.
- **Packet fixture**: four policy tests used a deliberately partial packet without
  `snapshot.destination`; the newly mounted profile panel previously dereferenced
  it. Existing head handles absent destination data and these tests explicitly
  select the isolated executor and supply a shaped profile response.

| ID | File and exact failed case | Classification / handling |
| --- | --- | --- |
| F01 | `tests/applications.test.tsx` — displays company, title, destination URL, and confirmed resume status | Endpoint fixture; also updated the canonical-PDF explanation expectation; passes at base and supplied head. |
| F02 | `tests/applications.test.tsx` — enforces a supplied word limit before saving or reviewing an answer | Endpoint fixture; passes at base and supplied head. |
| F03 | `tests/applications.test.tsx` — offers configured generation for supported technical experience questions | Endpoint fixture; passes at base and supplied head. |
| F04 | `tests/browser-assistant-improvements.test.tsx` — displays application context and readiness indicators with PDF resume confirmation | Endpoint fixture; also selects the isolated executor; passes at base and supplied head. |
| F05 | `tests/browser-assistant-improvements.test.tsx` — prominently displays non-submission guarantee notices and manual handoff instructions | Endpoint fixture; also selects the isolated executor; passes at base and supplied head. |
| F06 | `tests/browser-assistant-improvements.test.tsx` — distinguishes supported vs unsupported fields requiring manual entry | Executor expectation; passes at base and supplied head. |
| F07 | `tests/browser-assistant-improvements.test.tsx` — links to '/needs-input' queue when incomplete or missing questions are detected | Executor expectation; passes at base and supplied head. |
| F08 | `tests/browser-assistant-improvements.test.tsx` — requires a valid destination and never equates resume selection with PDF verification | Executor expectation; passes at base and supplied head. |
| F09 | `tests/browser-assistant-improvements.test.tsx` — displays workflow stage indicator and emphasizes non-submission guarantee when filled | Executor expectation; passes at base and supplied head. |
| F10 | `tests/browser-policy.test.tsx` — requires visible approval of the configured asset origins and sends their exact policy digest | Packet fixture; passes at base and supplied head. |
| F11 | `tests/browser-policy.test.tsx` — invalidates the asset approval if the advertised policy changes | Packet fixture; passes at base and supplied head. |
| F12 | `tests/browser-policy.test.tsx` — blocks filling unsaved edits and requires fresh value/context review after saving | Packet fixture; passes at base and supplied head. |
| F13 | `tests/browser-policy.test.tsx` — waits for the refreshed packet before accepting review of an analysis result | Packet fixture; passes at base and supplied head. |
| F14 | `tests/field-review-experience.test.tsx` — displays stale-packet warning non-destructively without discarding saved answers | Endpoint fixture; passes at base and supplied head. |
| F15 | `tests/field-review-experience.test.tsx` — keeps dom_assignment receipts unverified | Endpoint fixture; passes at base and supplied head. |
| F16 | `tests/field-review-experience.test.tsx` — keeps unknown receipts unverified | Endpoint fixture; passes at base and supplied head. |
| F17 | `tests/field-review-experience.test.tsx` — does not report an unavailable task as a clear challenge state | Endpoint fixture; passes at base and supplied head. |
| F18 | `tests/local-connections.test.tsx` — keeps a browser indicator separate from verification | Endpoint fixture; passes at base and supplied head. |
| F19 | `tests/local-connections.test.tsx` — does not promote configured credentials to verified status | Endpoint fixture; passes at base and supplied head. |
| F20 | `tests/phase4-job-dashboard.test.tsx` — detects ATS platform (Ashby) and displays completion metric badges after status check | Endpoint fixture; also selects the isolated executor; passes at base and supplied head. |
| F21 | `tests/phase4-job-dashboard.test.tsx` — opens Needs Input without inventing a durable ID from the DOM field ID | Executor expectation; passes at base and supplied head. |

## All 11 unhandled errors

Each is `TypeError: Cannot read properties of undefined (reading 'find')` at
`ChromeProfiles`, from `state?.profiles.find(...)` in that intermediate source.
They are **endpoint fixture errors introduced by mounting the new query against
old mocks**, not pre-existing baseline errors. Vitest's “last test” attribution
can include an asynchronous error after that case; it is not proof of a separate
failure in the case's business logic. Each corresponding file passes without
unhandled errors at the supplied head.

| Error | File / Vitest last-test attribution | Classification |
| --- | --- | --- |
| E01 | `tests/applications.test.tsx` — enforces a supplied word limit before saving or reviewing an answer | Endpoint fixture; resolved. |
| E02 | `tests/applications.test.tsx` — offers configured generation for supported technical experience questions | Endpoint fixture; resolved. |
| E03 | `tests/phase4-job-dashboard.test.tsx` — detects ATS platform (Ashby) and displays completion metric badges after status check | Endpoint fixture; resolved. |
| E04 | `tests/field-review-experience.test.tsx` — displays stale-packet warning non-destructively without discarding saved answers | Endpoint fixture; resolved. |
| E05 | `tests/field-review-experience.test.tsx` — keeps dom_assignment receipts unverified | Endpoint fixture; resolved. |
| E06 | `tests/field-review-experience.test.tsx` — keeps unknown receipts unverified | Endpoint fixture; resolved. |
| E07 | `tests/field-review-experience.test.tsx` — does not report an unavailable task as a clear challenge state | Endpoint fixture; resolved. |
| E08 | `tests/browser-assistant-improvements.test.tsx` — displays application context and readiness indicators with PDF resume confirmation | Endpoint fixture; resolved. |
| E09 | `tests/browser-assistant-improvements.test.tsx` — prominently displays non-submission guarantee notices and manual handoff instructions | Endpoint fixture; resolved. |
| E10 | `tests/local-connections.test.tsx` — keeps a browser indicator separate from verification | Endpoint fixture; resolved. |
| E11 | `tests/local-connections.test.tsx` — does not promote configured credentials to verified status | Endpoint fixture; resolved. |

Residual frontend diagnostic: both the base and supplied-head focused runs emit
the same React `act(...)` environment warning in “waits for the refreshed packet
before accepting review of an analysis result”. That case passes; it is a
baseline fixture warning, distinct from the 11 unhandled exceptions. No failed
or unhandled case remains in the affected runs. No full suite was rerun.

Reproduce the comparisons in detached linked worktrees at each named SHA, sharing
only existing test dependencies; do not copy the head's tests over the base:

```sh
# Base: six previously failing files only.
pnpm -C frontend exec vitest run tests/applications.test.tsx \
  tests/browser-assistant-improvements.test.tsx tests/browser-policy.test.tsx \
  tests/field-review-experience.test.tsx tests/local-connections.test.tsx \
  tests/phase4-job-dashboard.test.tsx --reporter=verbose
# Supplied head: same six plus the new executor/profile routing coverage.
# Append tests/chrome-profiles.test.tsx to the explicit file list above.
```

## Bound Prepare correction

Remote Prepare now resolves only the stored tab ID in the explicitly selected,
authenticated profile and current browser session. It never queries the active
tab, changes focus, adopts another tab, transfers a profile or creates a new tab.
Both before and after DOM inspection it checks the versioned task and current
packet/context through the authenticated native host, then the saved window/tab,
exact URL, normal/non-incognito window, pending navigation, discarded/loading
state, exact origin permission and command expiry. The mailbox also checks
selection/profile versions and command context before start. DOM work remains
in the top frame's isolated world.

Focus loss still cancels pending fill authority and revokes the previous plan.
A fresh inspection alone may proceed from a `focus_lost`/`active_tab_changed`
pause. Old plan authorization cannot proceed. A later focus event preserves any
stronger pause reason, including owner Pause/Stop, navigation, refresh and
worker/browser recovery. Dashboard Prepare supports the same narrow exception;
it issues the exact revisioned command without an implicit Resume. CAPTCHA plans
remain read-only and require manual handoff. Remote Prepare always disables
interactive retention, and never calls fill/authorize/submit.

Task window IDs now survive native request construction instead of being
replaced by the profile's default Open window. Backend bound-task validation
checks the exact window as well as tab, profile/session and task version.
Unversioned dashboard reads still expose stale tasks for owner review; versioned
pre-inspection reads additionally validate the saved packet's current context.
No API schema, permission, migration or deployment-default change is needed.

## Focused Chromium regression

```sh
pnpm -C extension build
PYTHON=/ABSOLUTE/EXISTING/TEST/PYTHON \
  node extension/tests/chrome-profiles.browser.mjs --prepare-only
```

This mode connects two disposable Chromium profiles through the actual MV3
extension, authenticated Python native host and FastAPI with a fresh disposable
PostgreSQL 17 container (`--pull=never`, random loopback-only port). It selects
the job profile and opens an exact fictional application through the dashboard
command channel. It then prepares first with an unrelated foreground tab in the
same window, then with an unrelated foreground tab in a different window.

It asserts command completion, original profile/session/window/tab/packet identity,
unchanged foreground focus and selection, scripts only on the bound application,
unchanged empty/manual values on both pages, no application in the personal
profile, zero employer write requests and no submissions. Filling is disabled
in this mode; independent SQL checks zero fill authorizations and receipts.
Only its temporary extension copy grants the fictional origin. Installed Chrome,
real profiles, live settings, native manifests and services are untouched.

## Final focused results

| Check | Result | Saved local evidence |
| --- | --- | --- |
| Base, six affected frontend files | 61 passed, zero unhandled errors | `reports/pr45-baseline-frontend.log` |
| Supplied head, those six plus profiles | 66 passed, zero unhandled errors | `reports/pr45-exact-head-frontend.log` |
| Final affected frontend files | 69 passed, zero unhandled errors | `reports/pr45-final-frontend.log` |
| Profile/task backend contracts | 42 passed | `reports/pr45-profile-backend.log` |
| Shared answer/native inspection contracts | 14 passed | `reports/pr45-shared-native-backend.log` |
| Coordinator and form bridge | 57 passed | `reports/pr45-bound-prepare-unit.log` |
| Tab network guard | 4 passed | `reports/pr45-guard.log` |
| Real native-host framing/auth/offline probe | 1 selected test passed | `reports/pr45-native-auth.log` |
| Chromium background Prepare | Passed both foreground-tab and foreground-window variants | `reports/pr45-bound-prepare-chromium.log` |
| Supplied-head Chromium reproduction | Expected failure: `application_tab_not_active`, command `outcome_unknown` | `reports/pr45-original-prepare-repro.log` |
| Typecheck, changed-file Ruff/Prettier and whitespace | Passed | `reports/pr45-typecheck.log`, `reports/pr45-format.log` |

Final backend commands name only affected files/cases:

```sh
python -m pytest backend/tests/test_extension_tasks.py backend/tests/test_chrome_profiles.py -q
python -m pytest backend/tests/test_extension_answers.py \
  backend/tests/test_browser_forms.py::test_manual_native_identity_and_duplicate_protection \
  backend/tests/test_browser_forms.py::test_native_security_preview_cannot_authorize_and_pending_answer_is_not_duplicated \
  backend/tests/test_browser_forms.py::test_native_preview_only_dropdown_cannot_be_authorized \
  backend/tests/test_browser_forms.py::test_native_date_requires_exact_verified_value \
  backend/tests/test_browser_forms.py::test_native_repeated_unqualified_fields_do_not_share_answers -q
node --test extension/tests/task-coordinator.test.mjs extension/tests/form-bridge.test.mjs
node --test extension/tests/network-guard.test.mjs
PYTHON=/ABSOLUTE/EXISTING/TEST/PYTHON node --test \
  --test-name-pattern='real Python native host' extension/tests/native-protocol.test.mjs
```

The regression harness was copied into a detached worktree at the supplied head
and run against that head's unchanged backend and freshly built extension.
It failed at the first unrelated-tab Prepare with `application_tab_not_active`.
The final implementation passes the same assertion plus the separate-window
variant. During development, the new test also exposed focus-loss version/pause
handling; fixture fixes used the authorized popup to drain queued invalidations
and `getLastFocused` for the cross-window focus assertion. No production guard
or functional assertion was skipped to make the test pass.

Ten existing private/runtime/service/native files match their saved preservation
hashes. The primary checkout remains unchanged. All fixtures use isolated data;
Docker containers, native manifests and test profiles are cleaned up. No hosted
workflow, complete suite, real profile connection or live command enablement ran.

## Remaining live boundaries

Genuine personal/job profile connection, actual site permission/revocation,
Naukri DOM behavior and actual Telegram delivery through this release still need
separately approved installed acceptance. The Chromium regression uses the
owner-authenticated dashboard channel; owner/private-chat Telegram routing is
covered by isolated backend tests, not a genuine Telegram message.

Chrome must be running; alarms/native startup can delay commands. A closed,
moved, navigated, loading, discarded or stale-session bound tab fails closed;
revalidate or explicitly Open again. Concurrent control/revision changes reject
an old command and require a fresh request. Permission prompts require an owner
gesture in the selected profile. Remote preparation does not grant filling,
attachments or submission. DNR still cannot control pre-existing streams or
independent background activity. Existing expiry, deduplication, uncertainty,
offline behavior and the [installation/rollback boundary](install-and-rollback.md)
remain in force. No merge, install, live channel activation or genuine application
submission is authorized by this follow-up.
