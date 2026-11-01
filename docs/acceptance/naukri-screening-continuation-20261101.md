# Naukri screening continuation — installed live acceptance, 2026-11-01

**OPEN: no new application or receipt has been confirmed.** Real discovery is
running with minimum score **50**. This release adds continuation of supported
Naukri screening questions after the first admitted Apply. Installation, native
reconnection and an actual provider Resume Download passed; this is not a claim
that the new questionnaire adapter has completed a real application.

Implementation: [`a093eabc1ca1f0989b4ff7e3f7be187f442ddb2a`](https://github.com/karanagg166/automated-apply/commit/a093eabc1ca1f0989b4ff7e3f7be187f442ddb2a),
branch `fix/live-prepare-discovery-20261030`, [PR #48](https://github.com/karanagg166/automated-apply/pull/48).
Previous installed behavior: [bounded discovery acceptance](naukri-bounded-discovery-pages-20261101.md).
Times below are UTC; raw evidence remains private.

## Resulting behavior

The extension waits for the asynchronous Naukri questionnaire after one admitted
Apply and retains that exact inactive tab across service-worker wakeups. The
adapter recognizes the genuine retained chatbot structure: message containers,
DIV choices, contenteditable text and the Save control. It never activates a tab,
uses the keyboard/clipboard, opens a chooser or calls a private provider endpoint.
Once the owner adopts a form tab, that tab remains unavailable to automation.

Answers use verified saved facts, explicitly approved answer reuse, or grounded
narrative generation. Missing personal information goes through the existing
owner-only Telegram reply channel. Replies refresh the account, actual provider
PDF, listing and original form before continuing. Reuse defaults OFF and is
scoped to the profile version, actual question/options and relevant job facts.
Conflicting saved facts, sensitive/identity/consent questions and unsupported
extra resume-upload steps pause instead of manufacturing an answer.

The canonical packet remains `submitting`, fencing other application channels.
Each current question has its own durable single-use admission; input/choice
handlers can themselves submit. Lost responses reconcile through independent
application-history documents. An answer or Apply click is never a receipt.
The supervised one-application allowance now also survives midnight: an uncertain
first attempt cannot silently authorize another application on the next day.

Model work runs outside the owner transaction and releases its read connection
before remote generation. The owner's explicit instruction to use Cohere for
grounded Naukri answers is scoped to this adapter. The existing project credential
has an evaluation-key confirmation. A separate private versioned configuration
preserves its **5 requests/month and 110,000 reserved tokens/month** ceilings,
uses the already selected model, and authorizes candidate context for these
answers. The global provider and owner-command-text sharing remain unchanged.
No live Cohere generation occurred in this acceptance window. Account model
access and actual generated answers remain untested here; provider failures or
budget exhaustion must pause generation rather than invent an answer.

## Exact installed release and rollback

| Component | Installed source |
| --- | --- |
| API, execution worker, Telegram, native host | `a093eabc1ca1f0989b4ff7e3f7be187f442ddb2a` |
| Chrome extension | Same SHA, **1.3.13**, **23/23 exact files**, stable ID `gdjbmkffcpicbpiikcohlmokkmcpipgp` |
| Frontend runtime | Unchanged `f90cfe7ea3dfc7ca20efe1a1995b3da26707a028` |

The owner standing authorization in `AGENTS.md` covers this local update. No
additional SHA approval was requested. The queue was **STOPPED revision 33**
through replacement. All **344 records**, approved account binding revision
**1**, credentials, canonical PDF, historical application evidence and other
platform policies were preserved. No database snapshot was restored.

The original owned maintenance tab had closed. A new extension-owned inactive
setup tab was requested through native messaging; an unrelated existing setup
tab was left alone. Maintenance used only the new owned tab.

The first installer attempt stopped at its 20-second `launchctl bootout` command
wait while Telegram was shutting down. **No component files were replaced.**
The previous execution worker and Telegram service were restored and the exact
protected files verified. That attempt's evidence and inventory were retained.
The retry tracks services before unloading them and awaits the asynchronous
unload and old-PID exit. This changes installer shutdown tracking; it does not
increase application/database/native request timeouts or connection limits.

On the successful retry, all three old PIDs exited before their references were
replaced. Telegram's graceful unload took **18.643 seconds**. At **09:44:41**:

- API/database `/ready`: **200**, **2.357 seconds**, paired **LOCKED → LOCKED**.
- Frontend login: **200**; frontend runtime unchanged.
- Same-ID extension ordinary Reload: **1.3.13**, exact 23-file inventory.
- Native selected-profile connection: **CONNECTED**, commands enabled, fresh
  heartbeat after Reload.
- Account binding and queue configuration/record count: unchanged while stopped.
- Front Chrome window and all selected-tab IDs: exactly equal before/after the
  cutover. This is a bounded snapshot comparison, not continuous focus telemetry.

At **09:44:45**, the queue resumed as **RUNNING revision 34**, unchanged score
**50**, **SUPERVISED**, one-application allowance and hourly cap **1**. Other job
platforms remain disabled. Gmail remains READ + CREATE DRAFT ONLY; sending is OFF.
Recurring AUTOMATIC has not been activated because the first new independently
verified receipt is still absent.

Two private installation-plan inventories retain previous API `9946623`,
execution/Telegram `f90cfe7`, native `fc91a21`, all 22 previous extension files,
previous plists/wrapper, protected-file digests and exact new files. All old
releases and original configuration remain. Rollback stops the queue, waits for
new PIDs to exit, restores exact previous components, preserves the newly added
module in the rollback inventory, reloads the same-ID extension and verifies
readiness/account state. It never restores database snapshots over new outcomes
or retries an uncertain application.

## Genuine provider evidence after installation

Read-only profile comparison was temporarily enabled with **no approved profile
write fields**, no auto profile sync, and actual saved-PDF verification required.
At **09:45:51**, the new installed extension completed the genuine Naukri Resume
Download workflow: **100,198 bytes**, provider PDF SHA-256 equals the independently
verified canonical encrypted PDF, result **MATCHED_PDF_BYTES / COMPARED**. Filename
agreement was not used as proof. The existing saved resume needs no replacement.
The original disabled comparison policy was restored as revision **15** at
**09:46:01**. Neither email nor profile content was overwritten. Tight paired
screen-lock telemetry was not collected around this particular download.

The new installed release completed a genuine discovery cycle **09:45:02 →
09:45:22**, zero new unique URLs and no source error. At **09:46:44** (Mac LOCKED),
the durable queue held **344 records**: **250 SKIPPED**, **84 NEEDS_INPUT**,
**9 DISCOVERED**, and **1 retained historical receipt**. The consumer and worker
were polling. Telegram had a fresh **09:46:18 live_poll**, bound identity and no
reported error. There were **0 admitted browser writes and 0 new receipts**.
The nine discovered jobs were still awaiting genuine inspection at that snapshot.

Before installation, the overnight system had continued processing: at
**09:31:36**, **329 records** comprised **244 SKIPPED**, **84 NEEDS_INPUT** and the
same **1 historical receipt**; the source admission counter was **316**. By
cutover it had reached **331**, total records **344**. These are real durable
discovery/processing observations, not fixtures or proof of successful matching
and application submission. Age, experience, applicant metadata and the owner's
saved preference/skill checks still gate preparation. The startup/company-stage
restriction remains in force; its pending owner clarification has not been
treated as permission to admit unknown stages.

The next new-release discovery cycle also completed **09:50:08 → 09:50:29**:
provider page **2**, zero new URLs and no source error. At **09:50:50** (LOCKED),
the same 344 records were **255 SKIPPED, 85 NEEDS_INPUT, 3 DISCOVERED**, one
historical receipt, **zero admitted writes/new receipts**. This establishes two
completed genuine discovery cycles after service/extension restart; it does not
establish recovery during an in-progress real submission.

A separate read-only diagnostic at **09:50:23** assessed **321 genuine stored
listing-fact records**, with no skill-alias substitutions or policy changes:
**zero** satisfied all available admission checks. Overlapping blockers included
247 outside the age limit, 51 requiring age review, 15 requiring applicant review,
308 below score 50, and 320 with preference/required-skill negatives. Company stage
and startup status were unknown in all 321. Even hypothetically removing only
the preference/skill and unknown-field blockers would leave **zero** passing the
other current checks; simply waiving company-stage evidence would not make these
records eligible. This diagnostic reads persisted evidence, not fresh provider
reverification or an authorization to submit anything.

QTrino's historical application was never reopened or replayed. No new Apply,
questionnaire answer, resume upload, submission receipt or submission notification
is claimed from this live window. A live profile download or source URL is not an
application receipt.

At **09:55:37**, all 344 existing records had finished their pending inspections:
**258 SKIPPED + 85 NEEDS_INPUT + 1 retained historical receipt**, zero new writes
or receipts. A third genuine source cycle was in progress on ordinary page 3.

That third cycle completed **09:55:33 → 09:55:57**, ordinary page **3**, **three
new unique real jobs** durably admitted, no source error. Total records increased
**344 → 347**, source admission count **331 → 334**. At **09:57:10**, inspection
had excluded one new job and the other two were pending; global totals were
259 SKIPPED, 85 NEEDS_INPUT, two DISCOVERED, one retained historical receipt.
Admitted writes and new receipts remained **zero**. This is genuine new-release
discovery and processing, not a fixture-enqueued cohort.

At **09:58:44**, all three new jobs had finished inspection: one exclusion and
two metadata holds. The full **347-record** ledger comprised **259 SKIPPED +
87 NEEDS_INPUT + 1 retained historical receipt**, with no undispatched
DISCOVERED records, **zero admitted writes and zero new receipts**. At
**09:58:33**, final integrity checks again passed backend/database readiness,
native connection, approved binding revision 1, exact same-ID 23-file extension,
exact new component references, protected credential/configuration digests,
RUNNING revision 34/score 50, restored disabled comparison policy and Gmail
READ + CREATE DRAFT ONLY with sending OFF. Historical releases and rollback
files remain intact.

An additional genuine search-layout inspection used only the newly owned inactive
setup tab, then restored its setup URL. The actual experience slider displayed
**0 / Any**; that is not evidence of a selected Fresher filter. A Startup company
type checkbox was observed, but this does not prove an employer's early funding
stage. No search filter or application policy was changed based on those guesses.
The page had 20 real listing links and no observed challenge. Both navigations
refused an active/adopted setup tab. During this later interval the lock state
changed to UNLOCKED and the all-window selected-tab comparison differed; a later
check showed the same front window and Profile 8 selected tab, with the setup tab
still inactive. The difference's cause is unestablished; continuous preservation
of every selected-tab ID is not claimed. No activation, keyboard or clipboard
operation was issued.

## Targeted validation, separated from live evidence

| Check | Result | Scope |
| --- | --- | --- |
| Backend questionnaire/submission/Telegram/background queue/queue regression set | **94 PASS, 15.90 s** | Isolated fictional database; 13 questionnaire cases included |
| Added midnight authorization regression | **1 PASS, 0.38 s** | Isolated fictional database; test initially failed due to a missing test import, corrected before candidate build |
| Exact immutable candidate's own venv | **14 PASS, 5.92 s** | 13 questionnaire + midnight case, overlapping the preceding sets |
| Focused Node queue/chatbot tests | **32 PASS, 0.750 s** | Fictional DOM/native responses |
| Actual isolated Chromium execution/chatbot cases | **29 PASS, 107.589 s** | Shipped DOM functions; genuine class shapes with fictional content; inactive browser tabs |
| Actual isolated Chromium queue cases | **11 PASS, 62.644 s** | Shipped queue; fictional provider/native responses |
| Chromium provider/unexpected requests, chooser events | **0 / 0 / 0** | Both runs; provider DNS/requests routed away from the live service |
| Ruff E9/F/I, diff whitespace, selected Prettier checks | **PASS** | Changed implementation/tests/types |
| API export, regenerated frontend types/typecheck | **PASS** | Contract additions; no frontend runtime rebuild/replacement |
| Candidate own pinned venv/pip check/extension build | **PASS** | No mutable dependency symlinks; stable ID unchanged |

The earlier 27-case Chromium run was superseded by the final 29-case run. Backend
sets overlap; they are not 109 distinct cases. One mistyped pytest filename ran
zero tests before the corrected 94-case invocation. These fixture checks establish
implementation guards, not production questionnaire or application acceptance.

Reproduction from the implementation SHA:

```sh
.venv/bin/python -m pytest backend/tests/test_naukri_questionnaires.py backend/tests/test_naukri_submission.py backend/tests/test_packet_telegram_questions.py backend/tests/test_naukri_background_queue.py backend/tests/test_application_queue.py -q
pnpm -C extension exec node --test tests/naukri-chatbot.test.mjs tests/naukri-queue.test.mjs
pnpm -C extension exec node tests/naukri-execution.browser.mjs
pnpm -C extension exec node tests/naukri-queue.browser.mjs
pnpm -C frontend typecheck
pnpm -C extension build
```

## Acceptance matrix and remaining work

| Requirement | Status | Evidence / remaining work |
| --- | --- | --- |
| Exact local install with stopped queue, rollback, stable ID and preserved data | PASS | Installed a093eab; previous bytes retained; 344 records and binding revision 1 unchanged |
| Approved Profile 8 identity and canonical provider-saved resume | PASS | Existing approved binding; fresh genuine Download and PDF byte digest match |
| Backend/database/frontend/native/Telegram after service restart | PASS | Ready/login 200, native fresh reconnect, actual Telegram live poll |
| Locked readiness and focus preservation during cutover | PASS | Paired locked ready 200 and matching front/selected-tab IDs |
| Genuine recurring discovery after restart | PASS, bounded | Three completed new-release cycles, pages 1–3; third admitted three new real jobs; no source error |
| New supported questionnaire controls/Telegram resumption | NOT TESTED LIVE | Isolated backend/DOM/Chromium cases pass; no eligible live application reached this adapter |
| Grounded Cohere narrative answer | NOT TESTED LIVE | Scoped configuration and unchanged conservative budget; no generation claimed |
| New eligible real application and independent provider receipt | BLOCKED | No new admission; all 347 current records inspected/excluded/held or historical; no new qualifying supported application |
| Additional chatbot-required resume upload/replacement | BLOCKED | No chooser-free supported upload accepted; saved canonical resume already matches |
| Bounded recurring AUTOMATIC activation | BLOCKED | Requires first new receipt and critical checks; not activated |
| Restart during a real application / real locked form filling/submission | NOT TESTED | No qualifying real attempt; heartbeat alone is insufficient |
| Continuous 24/7 operation | NOT ACCEPTED | Local browser requires awake Mac, Chrome, login, network and provider availability; quotas/filters/challenges remain enforced |

Continue genuine discovery and inspect the pending jobs. When one passes every
saved filter, the existing one-application authorization permits its supported
ordinary flow without another per-job prompt. Verify independently in application
history; do not replay after uncertain results. Activate bounded AUTOMATIC only
after that first receipt and critical checks. Keep working on supported uploads,
real questionnaire/provider acceptance and restart/locked-screen reliability.
No merge, hosted Actions, Gmail sending, other-platform activation, release
deletion or cleanup occurred.
