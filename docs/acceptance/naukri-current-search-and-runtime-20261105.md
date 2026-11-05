# Approved third attempt, current search controls and installed runtime

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`. **OPEN: zero new verified worker receipts.**
The owner explicitly approved the pending lifetime2→3 proposal. The additional
slot is available; the two older uncertain attempts remain consumed/quarantined.
This supersedes the pending quota and installed-version statements in
[the preceding report](naukri-form-loss-and-history-20261105.md).

## Genuine installed behavior

The owner policy changed only `supervised_submission_cap:2→3`, through the
authenticated installed frontend gateway. The rolling hourly limit remains1,
score50, any verified listed skill, age14days, applicant threshold1000 and
unknown-count review. Other platforms remain OFF; recurring AUTO still requires
the first strict worker receipt. Actual frontend Start resumed RUN154 after
policy revision153. An initial gateway request lacked its required Origin header
and returned403 before mutation; fresh configuration verified unchanged before
the correctly authenticated request. No gateway protection was weakened.

The installed discovery generator now interleaves internship keywords with
confirmed junior target-role searches. This broadens discovery only; the saved
profile currently permits full-time employment, and every actual listing must
still satisfy that and all other checks. No internship eligibility is inferred.

The first real internship search failed `search_date_sort_not_confirmed`.
Inspection of the genuine inactive page found a current, deliberately collapsed
GNB input with exact Fresher value/title and `experience=0` in the URL, while the
older sidebar slider was absent. The adapter had been waiting for that slider.
It now supports this exact current header, preserving unique controls, matching
URL/query, conflicting-evidence, account, owner-adoption and challenge guards.
Legacy sliders retain their zero/selected checks. Internship keyword searches
also preserve Recommended relevance and use the genuine Last1day control.
Every job's actual date and eligibility are still verified independently.

The corrected function on the genuine page reached Recommended / Last1day /
Fresher and18 links, with zero application actions and equal focus snapshots.
Durable deduplication added12 new identities and kept6 existing/fenced identities.
The full18-job audit found9 excluded by saved preferences/skills,8 held for
lower-bound applicant counts, and1 held for unknown employment type. None passed
every current check. A subsequent genuine20-link Fresher observation added1 new
identity and deduplicated19; its unfinished freshness check was not called passed.
Its original setup tab subsequently disappeared, cause unknown; no replacement
Apply or invented facts resulted.

After installation, actual frontend Start resumed **RUN160**. The installed
normal worker's filtered Backend Developer search completed
17:02:49.259–17:03:06.276UTC without a source error, adding0 identities because
its links were already recorded. This is real installed behavior, not a fixture
or a heartbeat inference. Further scheduled reads and full eligibility continue.
Two Apply admissions and zero worker receipts remain; no third Apply is claimed.

## Exact releases, installation and rollback

| Component | Actual installed SHA |
| --- | --- |
| API and execution worker |[1f14f1ca661bf59fd06f95fb5bbf39419e1b1051](https://github.com/karanagg166/automated-apply/commit/1f14f1ca661bf59fd06f95fb5bbf39419e1b1051) |
| Extension disk AND runtime1.3.40 |[968cdaedec369493b435e33fddb741a9d870c253](https://github.com/karanagg166/automated-apply/commit/968cdaedec369493b435e33fddb741a9d870c253),26 files |
| Frontend, unchanged |7efdb64fb7b8100f9268ac1d17761ea8c188cbfd |
| Telegram/native host, unchanged |b6b069051cdddc26683e67ef64646a90a2a7f753 |

The stable extension ID remains `gdjbmkffcpicbpiikcohlmokkmcpipgp`; permissions and
manifest key are unchanged. The new26th file is the guarded maintenance module.
The answer-reuse key repair is now installed in both API and execution: full
SHA-256 in the existing50-character preference key, legacy question conversion
only on explicit reuse approval, and unchanged scope/expiry/revocation checks.
No real approved-answer reuse is claimed from fixture tests.

The first API/worker installer hit SQLSTATE55P03 on the owner lock **before STOP
or replacement**. A bounded retry used the existing SKIP LOCKED owner guard,
then committed STOP155 with2,462 records and two admissions. Exact API/worker
replacement passed15:23:21UTC: ready200/frontend200, fresh execution heartbeat,
profile5/binding1, protected hashes and equal Chrome/OS focus snapshots. No
Chrome operation or extension replacement occurred in that service cutover.

The extension update used STOP159 and preserved2,497 records. An initial direct
Apple Events call could read DOM but lacked privileged extension APIs; it
returned no execution acknowledgement. All25 previous1.3.39 files were restored,
the added module preserved in rollback storage, and the unchanged browser session
plus genuine `Version:1.3.39` DOM independently established no completed reload.
The corrected operator route dispatches a DOM request to the extension's own
trusted page handler. The handler checks authenticated STOP revision, exact
profile/session/window, native-created unadopted setup ownership, no pending
form/read, expiry and a consumed per-request intent before `runtime.reload()`.
It never opens, navigates or activates a tab/window.

The genuine DOM request was acknowledged16:42:05UTC. At16:42:31 a new browser
session had a fresh connected native heartbeat; API/frontend returned200 and
profile5/binding1, policy, record count and protected files matched. Both the
normal settings version and its trusted runtime marker subsequently reported
**1.3.40** with the same ID. Disk evidence alone is not used as a runtime claim.

**Complete maintenance focus acceptance FAILED.** The runtime-reload portion
had equal before/after Chrome and OS snapshots. The later Apple Events navigation
for the version witness changed Chrome's front-window ordering to Profile8,
while selected tabs stayed unchanged and the OS foreground app stayed Chrome.
The cause cannot be proven from those samples, but this is not a focus pass.
Automatic navigation to extension settings or Chrome management pages is now
suspended. No window was activated to restore a snapshot. Ordinary inactive
Naukri processing remains installed. A native-created settings setup path and
whole-path focus acceptance remain necessary before calling updates unattended.

Private inventories remain under Application Support:
`installation-plans/junior-intern-1f14f1ca661bf59fd06f95fb5bbf39419e1b1051-retry1`
and `installation-plans/current-gnb-dom-968cdaedec369493b435e33fddb741a9d870c253`.
They retain exact API010f679/execution0c87562 plists, all previous1.3.39 files and
hashes, protected-file inventory and instructions. All earlier releases and
failed/prepared candidates remain preserved. Rollback keeps STOPPED, restores
exact prior components and verifies data/account/policy/readiness. It never
restores the DB, refunds admissions, replays Apply or deletes releases. A reload
must use a validated inactive trusted document; if Chrome cannot load it, request
only the unavoidable normal owner action, never reuse unsafe navigation.

## Targeted tests and measured limits

| Verification | Result |
| --- | --- |
| Exact API/worker1f14f1c |89 backend PASS,17.50s; own venv/pip check PASS |
| Source discovery file |73 PASS,9.34s; overlaps those89 |
| Fresh loopback PostgreSQL17.11 |3 groups PASS,0.079s: old-key22001 rejection, compact-key commit, fresh-session scope; fictional data/zero owner DB access |
| Final exact extension968cdae |68 Node PASS (58 queue+10 maintenance); build/26-file identity audit PASS |
| Search/queue isolated Chrome |32 PASS on275f366,68.155s process; all relevant shipped search/execution input bytes equal the final candidate |
| Final exact DOM-bridge reload |1 real isolated Chrome journey PASS,4 checks: two-window focus, owner tabs, inactive setup, consumed intent; new runtime version independently verified |
| Fixture provider/chooser access |Zero live Naukri, unexpected requests and chooser events in the search run; zero external requests in reload journey |
| Source checks |Targeted Prettier, Ruff E9/F/I for changed Python and diff checks PASS |

Source/candidate reruns overlap and are not summed. Early reload-harness failures
included Playwright default focus emulation and the fresh fixture's Developer
mode being off. Chrome explicitly reported unsupportedDeveloperExtension on
reload. The passing fixture enables Developer mode through its own ordinary
Chrome UI; no owner preference, OS control or security flag was changed to defeat
that requirement. The actual Profile8 Developer mode was read-only verified.
The initial direct-API Mac failure and its rollback are retained, not hidden.

Real native timing samples showed31–32 SQL reads totaling roughly5.2–5.6s and
connection occupancy around5.8–6.0s, with negligible pool acquisition time.
Twelve bounded role-session samples did not identify the original timed-out
lock holder. Slow sequential round trips and contention remain open; no database
connection limit, pool size or production request timeout was increased. Pool1
per process, role limit5 and schema003 remain. The local fixture DB server was
stopped and its data retained.

Reproduce affected source checks using existing dependencies:

```sh
.venv/bin/python -m pytest backend/tests/test_naukri_background_queue.py backend/tests/test_naukri_questionnaires.py -q
node --test extension/tests/naukri-queue.test.mjs extension/tests/naukri-maintenance.test.mjs
node extension/tests/naukri-queue.browser.mjs
node extension/tests/naukri-maintenance.browser.mjs
pnpm -C extension build
git diff --check
```

## Acceptance and next work

| Requirement | Status | Actual boundary |
| --- | --- | --- |
| Approved account binding and canonical data | PASS | Binding1/profile5 preserved; no contact/login overwrite |
| Provider saved PDF | PASS / NOT TESTED | Earlier genuine100198-byte checksum match retained; fresh40 submission preflight still required |
| Approved extra allowance | PASS | Lifetime3/hour1, only2 consumed; no history/budget reset |
| Genuine current header and installed discovery | PASS | Current GNB inspected; normal40 filtered cycle completed without source error |
| Actual deployed API/worker/extension readiness | PASS | Exact releases and separate runtime witness above |
| End-to-end maintenance focus | FAIL | Version-navigation window-order change; route suspended |
| First new completed form/submission/receipt | BLOCKED | No new fully eligible completed submission; zero new receipts |
| Recurring AUTOMATIC | BLOCKED | First strict worker receipt and critical checks still required |
| Repeated processing/restart/locked overnight | NOT TESTED | Prior Mac sleep prevents a24/7 claim; heartbeat is insufficient |
| Other adapters/contact discovery/drafts | NOT TESTED | Disabled/unaccepted; Gmail sending remains off |
| Full completion/review/merge | BLOCKED | Remains OPEN; no merge |

Continue genuine five-minute discovery and the one added eligible attempt under
the same filters; do not ask per-job approval within that allowance. Complete
supported factual fields/questionnaires, independently verify the sent receipt
and accurate notifications, then bounded AUTO. Preserve QTrino, both uncertain
admissions and every uncertain historical job against replay. Finish native
settings setup without unsafe navigation, then latency and natural locked/awake
acceptance. No hosted Actions, other-platform activation, Gmail send, paid
purchase, CAPTCHA/rate bypass, cleanup or release deletion occurred.
