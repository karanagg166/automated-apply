# Fresh junior discovery and experience evidence repaired; real receipt pending

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`. **Naukri remains OPEN with zero new receipts.**

The installed worker's genuine internship reads exposed `No fixed duration` as
another placement-duration label. A separate issue treated a single `0 years`
experience label as a maximum of zero, unnecessarily excluding candidates with
verified sub-year experience. Only an explicitly stated range establishes a
maximum. We retain the stricter observed minimum and leave an unstated maximum
unknown; an actual range/structured-minimum conflict still blocks the job.

[Schema.org](https://schema.org/monthsOfExperience) and
[Google's JobPosting documentation](https://developers.google.com/search/docs/appearance/structured-data/job-posting)
define `monthsOfExperience` as a minimum. Interpreting an un-ranged UI label as
providing no upper bound is our conservative metadata inference, rather than a
claim of a Naukri maximum. Configured custom advertised-experience ceilings still
require a known source maximum. Other filters and the candidate's facts stay exact.

## Exact changes, tests and installed components

- [API48fafb7](https://github.com/karanagg166/automated-apply/commit/48fafb77b97ac7e86813e89ad6781a15f846e084)
  includes a persistent, bounded discovery-read retry: only
  `backend_not_ready`, `backend_timeout` and `backend_transaction_rolled_back`,
  only an `inspect_job` without packet/form/admitted action, at most three retries
  with60/120/240-second backoff. Every new lease/document still passes current
  policy, profile, account, owner-focus and provider controls. Restarts retain the
  count; exhausted/protected/provider-challenge work remains held. No Apply is retried.
- [Extension1.3.29/c7869af](https://github.com/karanagg166/automated-apply/commit/c7869afc064177d6d5aaed4df9a73a4172e7f19a)
  includes the minimum-only/no-fixed-duration fixes and uses the genuine optional
  **Last 1 day** Freshness control for fresher keyword searches. Recommended keyword
  relevance stays; original role/Date sweeps still cover older jobs. No guessed
  endpoint/query or full-listing eligibility exception is added. Unrecognized or
  external freshness controls fail closed.
- Source backend71 targeted tests passed9.36 seconds; exact API candidate71 passed
  9.08 seconds. Source parser58 passed1.260 seconds; exact extension candidate58
  passed1.543 seconds, queue41 passed0.374 seconds, and22 actual isolated Chromium
  journeys passed38.943 seconds. These source/candidate overlaps are not added.
  Browser journeys used fictional routed pages: zero real/unexpected requests or
  file choosers. The actual new DOM forms informed the fixtures; fixture success
  is not live provider acceptance. Ruff, formatting, build, `pip check` and diff
  checks passed. Unchanged broad suites were not rerun.

Actual replacement passed at15:47:37UTC, under STOP123 with1,955 retained records:

| Component | Exact installed SHA |
| --- | --- |
| API | `48fafb77b97ac7e86813e89ad6781a15f846e084` |
| Extension1.3.29 | `c7869afc064177d6d5aaed4df9a73a4172e7f19a` |
| Execution, Telegram, native host | `b6b069051cdddc26683e67ef64646a90a2a7f753` |
| Frontend | `ae66975691a75cb0a3a43010dcfdba26a5100128` |

All24 extension files and the persisted stable installation path/ID match. Full
online003 catalog audit and ready200 passed, frontend200, fresh native reconnect,
profile5/account-binding1 and protected environments/service/frontend/native hashes
were preserved. Chrome front-window/active-tab snapshots matched. Exact previous
APIb6 and extension1.3.26 bytes/plists remain in rollback inventory; no historical
release was removed. Failed installation restores those components under STOP,
checks readiness/data/account/policy and never rolls back application history.

The actual Stop control response took10.052 seconds, excluding the later setup
wait. This remains a performance problem; it is not claimed solved. No connection
limit or timeout was increased. Actual dashboard Start then returned RUN124 with
any-skill/score50/14 days/1,000 applicants/unknown-count review, lifetime-one/hour-one
SUPERVISED and zero unexpected frontend requests. No allowance was reset.

## Genuine worker evidence and remaining failures

The first20 fresh internship-layout reads completed. Actual installed observations
now retain minimum1/12 year and maximumnull; seven were outside the age limit,
one held unknown applicant count, and12 remained unrecognized. Captured examples
of those failures use the newly identified no-fixed-duration layout; that fix
was subsequently included in1.3.29. A genuinely
inspected direct internship had42 applicants and a recent date, but also restrictive
residence wording and ambiguous employment evidence; this is not a claim that it
passes the owner's current policy or can be submitted.

At15:35 UTC, a real read through the newly connected Supabase plugin reported1,954
identities and zero admissions/new receipts. The named Supabase connection contains
the intended project; a separate Primary connection does not. Only read-only
aggregate queries were issued through the plugin. The earlier custom MCP OAuth
refresh failure is distinct; no further owner reconnect is required for the
working plugin or the already applied CLI repair.

After RUN124, a single audited batch scheduled20 fresh, never-attempted listing
reads, prioritizing the prior single-year conflict holds. No packet/eligibility/
write authority was added. New actual observations have begun: a single-year page
now retains its stricter one-month minimum with maximumnull and is independently
rejected for posting age. Freshness selection on the real installed search page
is still being inspected; isolated success alone does not prove it worked there.

Historical QTrino and uncertain031126029747 remain protected from replay. First
new receipt, live form completion, notification accuracy, recurring AUTOMATIC,
restart and locked-Mac application acceptance remain unachieved/unverified.

## DevTools macOS identity issue corrected

A native DevTools MCP call started a persistent headless system Google Chrome.
Despite its separate user-data directory, its `com.google.Chrome` identity confused
macOS AppleScript's application-name lookup. The maintenance guard could not find
the known setup tab and refused before any installed file changed. The subsequent
setup-tab observer also looked at the wrong process; the original owned inactive
tab was still present and was reverified after the correction. No owner tab was
navigated, activated, typed into or closed.

Only the exact task-owned headless browser and its old MCP server were stopped.
The private Codex configuration now explicitly selects the existing Playwright
Google Chrome for Testing executable (`com.google.chrome.for.testing`); other
settings were compared unchanged and a private backup retained.
[Verifierb70c985](https://github.com/karanagg166/automated-apply/commit/b70c985)
rejects the wrong bundle before launch. Actual SDK verification of the corrected
registered server passed all five checks/32 tools at15:48:48UTC, with zero provider
navigation/queue writes and identical owner frontmost/window/active-tab metadata.
The old native MCP transport was closed and requires client refresh; the current
SDK connection works. Native hot refresh is not claimed accepted.

| Acceptance | Result | Evidence / limit |
| --- | --- | --- |
| Genuine internship parsing through installed worker | PASS | Actual minimum-only facts; stale/count exclusions preserved |
| Exact retry/experience/freshness candidate checks | PASS |71 backend;58 parser;41 queue;22 isolated browser journeys |
| Exact API/extension installation, rollback and dashboard | PASS | STOP123/1955, ready200, preserved data/focus; RUN124 |
| Real Supabase plugin read | PASS | Correct project link; actual aggregate data; no write |
| DevTools distinct browser/SDK isolation | PASS | Five actual checks,32 tools, owner metadata equal |
| Native DevTools transport refresh | NOT TESTED | Cached old transport closed; corrected registration verified via SDK |
| Real installed Freshness selection and transient restart recovery | NOT TESTED | Source/candidate checks only; ordinary worker observation ongoing |
| First new real application/receipt | FAIL | Zero new confirmed submissions at the current checkpoint |
| Recurring AUTOMATIC / restart / locked application operation | NOT TESTED | First worker receipt prerequisite preserved |

Reproduce relevant checks with:

```sh
.venv/bin/python -m pytest backend/tests/test_naukri_background_queue.py -q
node --test extension/tests/naukri-observation.test.mjs extension/tests/naukri-queue.test.mjs
node extension/tests/naukri-queue.browser.mjs
.venv/bin/python backend/scripts/verify_chrome_devtools_mcp.py
pnpm -C extension build
git diff --check
```

Next: finish actual fresh reads/search inspection, complete one supported eligible
application once, independently verify persistent provider history and notifications,
then bounded AUTO and repeated/restart/locked acceptance. No Gmail send, other-
platform activation, CAPTCHA/rate bypass, hosted Actions, merge, cleanup or release
deletion. Raw DOM, profile/resume/account, configuration and private logs stay private.
