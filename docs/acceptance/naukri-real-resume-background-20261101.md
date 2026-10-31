# Genuine unattended resume verification and background maintenance

Branch `fix/live-prepare-discovery-20261030` → `main`, [PR #48](https://github.com/karanagg166/automated-apply/pull/48).
Local date **2026-11-01**; all observation times below are **2026-10-31 UTC**.
[Sanitized measurements](naukri-real-resume-background-20261101-metrics.json).

**Naukri remains OPEN. Zero new application submissions or receipts.**
The installed worker now verified the actual provider-saved PDF twice through
the genuine Download UI, across extension reloads. Real discovery/inspection
continues under the unchanged standing cap-one policy. No eligible inspected
candidate has yet met every saved requirement, and recurring AUTOMATIC is off.

## Exact installed components and authority

| Component | Installed exact source |
| --- | --- |
| API | [82d46e3a62f2c605d4fd98d586ace44a099b7b7f](https://github.com/karanagg166/automated-apply/commit/82d46e3a62f2c605d4fd98d586ace44a099b7b7f) |
| Execution worker | [cfd28af4a34d3d631d13191f720f3684775b4f38](https://github.com/karanagg166/automated-apply/commit/cfd28af4a34d3d631d13191f720f3684775b4f38) |
| Same-ID extension **1.3.11** | [33a132edce50252693b17dd2e6cf176a53f24710](https://github.com/karanagg166/automated-apply/commit/33a132edce50252693b17dd2e6cf176a53f24710) |
| Telegram, frontend, native host | `fc91a219d5b824f934bb733eaf20166661e1f08b`, unchanged |

The owner's explicit standing authorization for autonomous local Naukri updates
is recorded in [AGENTS.md](../../AGENTS.md), including **no further SHA/update
approval prompts** and the renewed **no-focus** constraint. It does not authorize
merge, cleanup, release deletion, hosted Actions, Gmail sending, other platforms,
policy relaxation or historical/uncertain submission replay.

The prior [reconnection and worker installation report](naukri-autonomous-updates-reconnect-20261101.md)
records automatic reconnection after the owner opened existing Profile 8 once.
No identity question, popup/button setup or binding replacement was required.

## Actual Resume Download: failure preserved, correction verified

A new read-only opt-in in the existing bound profile worker verifies the saved
resume without creating a job, packet or application. It reads the current
confirmed primary private PDF, decrypts/checks it locally, passes only its digest
as an expectation to the isolated verifier, and rechecks the current resource
again when receiving the provider observation. A changed resource, checksum,
byte count, identity, profile/session/window/tab binding, policy or lease blocks
verification. Resume filenames are not evidence. This grants no profile writes.

| Actual installed observation | Genuine result |
| --- | --- |
| 1.3.9, 21:06:09 | **FAIL** `profile_resume_download_pdf_not_observed`; no PDF match claimed |
| Original profile-sync policy restored, 21:06:13 | Read-only probe disabled; revision 9 |
| 1.3.10, provider observation **21:14:57.785971** | **PASS**, `COMPARED`, resume `MATCHED`, **100,198 bytes**, exact canonical/provider digest match |
| Original policy restored, 21:15:05 | Revision 11; no profile writes |
| 1.3.11 after reload, provider observation **21:19:38.126202** | **PASS again**, `COMPARED`, resume `MATCHED`, **100,198 bytes**, same canonical/provider digest match |
| Original policy restored, 21:19:48 | Revision 13; probe disabled, auto-profile-write false, approved-fields list unchanged |

The first failure established that the unattended capture was not accepted even
though an earlier supervised Download had produced a matching file. The corrected
MAIN-world adapter recognizes both `anchor.click()` and dispatched click events
on the exact UI-created download anchor. A genuine PDF may use an octet-stream
or absent MIME label; its `%PDF-` prefix, conservative **2 MB** limit, complete
SHA-256 and byte count establish the file. It consumes only that captured download,
restores the exact prototype descriptors on exit and leaves unrelated blobs/page
actions unchanged. The **8-second capture limit was not increased**.

The actual successful report does not record which event/MIME variant the page
used; that distinction is not claimed as live evidence. Both new paths are
covered separately in isolated browser regressions. No cookies, signed URLs,
PDF contents, filename, digest or candidate contact details are public.

The MAIN-world capture now receives only the exact profile URL. Work leases and
profile/session bindings remain in the trusted/isolated extension contexts.
Canonical PDFs are never replaced by a filename comparison. **No provider resume
replacement is needed for these observed matching bytes.** Future application
admission still requires its own fresh, bound resume observation; these read-only
profile records are not reusable Apply grants or submission receipts.

## Owner focus and autonomous maintenance: actual Mac acceptance

The old guard treated a selected Naukri tab in any window as active owner work.
This blocked background discovery while another Chrome profile was being used.
It now checks the window's actual `focused` state, rather than confusing current
or last-used windows with focus. [Chrome documents the distinction](https://developer.chrome.com/docs/extensions/reference/api/windows#property-Window-focused).
Missing/ambiguous window evidence yields. Selecting/adopting an actual worker tab
still permanently stops using that tab; foreground Naukri activity still yields.

For future updates the owner/updater can record a bounded maintenance request
through the existing private operation store. The existing authenticated native
poll offers it **only while the queue is STOPPED**, with the exact selected
profile/version, selection version, browser session and window binding, canonical
nonce and a maximum two-minute expiry. Global OFF, disabled profile/platform and
normal authentication checks remain. The payload has a fixed purpose, with no
arbitrary URL or script. The extension records intent before creation, opens only
its own **inactive** `chrome://extensions/` tab and does not admit an employer job.

At **21:04:36**, this actual native-driven path created one own inactive setup tab.
The **front-window and every active-tab ID matched the before snapshot exactly**.
There was no employer action. The request was then marked completed. Subsequent
1.3.10 and 1.3.11 updates used this own inactive page, without navigating personal
pages, selecting windows/tabs, typing or using keyboard/clipboard automation.

Earlier bootstrap maintenance snapshot differences remain documented in the
previous report; their cause was not established. The bounded successful sample
and the absence of focus commands are not a claim of continuous observation of
every instant or successful locked-screen operation.

Operational reproduction for a deliberately stopped queue:

```sh
.venv/bin/python backend/scripts/request_naukri_maintenance.py --env-file /private/path/to/runtime.env --request-setup
```

The CLI records a request, not an observed opened tab or an installation success.
It validates the owner-verified fixed profile and connected selected binding,
uses a temporary NullPool connection and prints no credentials. The equivalent
native request was exercised live above; CLI help/Ruff were checked separately.
No additional Chrome permission or personal profile access was requested.

## Actual installations and rollback

- API/extension 1.3.9 cutover: **STOPPED revision 18**, **296 records**.
  Old API PID 1089 exited at **21:02:30** before reference replacement; new PID
  **4631** was ready at **21:02:54**. Same-ID extension loaded at **21:02:56**;
  installation passed **21:03:07**, all other protected references unchanged.
- Extension-only 1.3.10: **STOPPED revision 20**, all **22/22** files verified,
  runtime displayed at **21:13:29**, checks passed **21:13:43**. Account binding
  revision 1 and all eight protected service/config/native references matched.
- Extension-only 1.3.11: **STOPPED revision 22**, all **22/22** files verified,
  runtime displayed at **21:18:14**, checks passed **21:18:27**. Other components,
  account, existing records and policy were unchanged.
- Final resume: **RUNNING revision 23**, SUPERVISED cap **1**, hourly cap **1**,
  concurrency **one**, minimum matching **80**, age **2 days**, applicant threshold
  **10,000**, unknown-applicant review and existing global daily cap **80** unchanged.

Each immutable build has exact source, independent artifacts and a verified
rollback inventory. API candidates used their own pinned venv with passing pip
checks; the final two extension-only updates used Node core without dependency
installation. Superseded uninstalled builds were preserved. No installed release
was edited as source, and no older release or backup was deleted.

Rollback: keep the queue stopped, preserve/reconcile uncertain outcomes, disable
and restore any active resume-probe policy before reverting to an older API, wait
for the candidate API PID to exit, restore the exact former API plist and/or all
22 prior extension files, restart/ordinary Reload and verify protected inventory.
Disabled probe policy serialization remains readable by the previous API. Never
restore database snapshots over new outcomes or erase a receipt/Apply fence.

## Actual job filtering and remaining submission blocker

A read-only diagnostic at **21:20:10** evaluated **223 actual persisted browser
fact records** with the unchanged saved matcher/policy. **None was fully eligible;
all 223 scored below 80, maximum 70**. The highest score belonged to an already
too-old posting. The highest score among records not definitely outside the age
limit was **42.31**. All 223 lacked required company-stage evidence; other missing
requirements and age/applicant ambiguities were retained. The uninspected backlog
is not declared ineligible. No score, skill, qualification or posting date was
manufactured, and no filter was loosened to obtain an application.

The follow-up diagnostic at **21:47:15** covered **259 actual fact records**:
again **zero fully eligible**, all below 80, maximum **70**. This diagnostic was
read-only; it did not promote work, create a packet, change a score or submit.

The structured `monthsOfExperience` minimum is now enforced even when it fits
inside the visible range: a one-month minimum under a 0–3-year label produces
minimum **1/12 year**, not zero. A minimum above the visible maximum still returns
`experience_requirement_evidence_conflict`. This conservatively tightens actual
admission. A speculative in-memory skill-name normalization preview also yielded
zero eligible records; it was not persisted or deployed as matching behavior.

### Final bounded background observations

Thirteen scoped read-only samples from **21:23:53–21:29:52** all observed the
queue RUNNING, Mac UNLOCKED and zero new action admissions. No monitor query
failed. Pending inspection fell **59 → 50** during that six-minute sample.
Read/connection durations were **2.146 / 2.327 / 3.866 s min/median/max**.

| Actual installed Date discovery cycle | Newly admitted distinct URLs | Duration |
| --- | ---: | ---: |
| 21:19:54–21:20:16 | 1 | 22.377 s |
| 21:25:26–21:25:44 | 0 | 18.340 s |
| 21:30:52–21:31:12 | 0 | 20.065 s |

These are genuine provider UI reads, not fixtures. The configured interval is
300 seconds; busy work delayed starts. Repeated searches deduplicated existing
URLs. Source admissions reached **284** and total records **297**, including
other previously approved sources and the historical receipt. Neither number
represents eligible jobs or submitted applications.

At **21:34:51**, the persistent queue was:

| Stage / reason | Count |
| --- | ---: |
| DISCOVERED, queued | 42 |
| NEEDS_INPUT: posting_age_requires_review | 22 |
| NEEDS_INPUT: applicant_count_requires_review | 3 |
| NEEDS_INPUT: experience_requirement_evidence_conflict | 11 |
| NEEDS_INPUT: owner_tab_active | 1 |
| SKIPPED: posting_outside_age_limit | 211 |
| SKIPPED: current_profile_preferences_or_required_skills_exclude_job | 6 |
| Historical SUBMITTED_RECORDED | 1 |
| READY / new admitted actions / new receipts | 0 / 0 / 0 |

The one owner-tab read refusal was retained; it was not automatically retried as
an application. Eleven real experience conflicts were blocked, rather than
treated as qualifications. Of the original **128** pending IDs, **115** had an
inspection outcome at **21:35:53** (99 SKIPPED, 16 NEEDS_INPUT), while **13**
remained DISCOVERED. That original backlog was still incomplete at this snapshot;
processing continues without changing filters or replaying an employer action.

At **21:44:11**, all **128 original IDs had inspection outcomes**: **104 SKIPPED**
and **24 NEEDS_INPUT**, **zero still DISCOVERED**. The exclusions were 103 outside
the posting-age limit and one profile/skills exclusion. Unresolved outcomes were
16 date-precision reviews, four applicant-count reviews, three experience conflicts
and one owner-tab refusal. Completion of inspection does not mean those jobs were
applied to or that unresolved metadata was approved. Newly discovered work remains
separate from this completed cohort.

At **21:31:21**, all four installed LaunchAgents had live PIDs. Backend/database
readiness returned **200 in 2.105 s**, selected Profile 8 was CONNECTED with
commands enabled and a fresh native heartbeat, and frontend `/` returned its
expected **307 redirect to `/login`, then 200**. Telegram's actual durable
`live_poll` state advanced to **21:31:56**, bot identity remained bound, and
`last_error` was null. No test message or fictional success notification was sent.
These checks do not establish a genuine application receipt or locked-Mac readiness.

The final standing-policy read at **21:49:21** verified queue **RUNNING revision 23**,
SUPERVISED cap **one/hour one**, `owner_submission_authorized=true`, local Naukri
preference `automatic_preferred`, execution mode `ON_DEMAND`, and Telegram
notification on a verified receipt enabled. Only the Naukri queue adapter is
configured. Gmail remains `draft_only`, with sending disabled. No per-job approval
or release approval is pending for that standing first eligible application.

## Focused verification, actual versus fixtures

| Check | Exact result | Scope |
| --- | --- | --- |
| Profile/PDF/submission backend regressions | **52 passed, 9.38 s** | Isolated fixtures, including five new PDF-proof cases |
| Policy rollback compatibility follow-up | **17 passed, 2.11 s** | Overlapping profile suite, corrected disabled opt-in serialization |
| Maintenance state/binding/expiry regressions | **6 passed, 29 deselected, 0.73 s** | Isolated native dispatcher fixtures |
| Exact API-candidate own-venv smoke | **12 passed, 40 deselected, 1.94 s** | Overlapping resume/maintenance cases |
| Final observation/queue/native Node regressions | **62 passed, 4.262 s** | Isolated fixtures/native offline bounds; min-experience and MAIN-argument checks |
| Final Download/execution Chromium checks | **26 cases passed, 9.670 s** | Fictional pages, zero live/unexpected requests and chooser events |
| Focus/queue/maintenance Chromium checks | **10 cases passed, 54.827 s** | Actual isolated inactive tabs, fictional provider pages, zero live/unexpected requests and choosers |
| API type regeneration / frontend typecheck / Ruff / format / diff / build / pip checks | PASS | Changed contracts/files and own environments |
| Genuine provider PDF verification | **2 PASS observations**, earlier 1 FAIL preserved | Actual installed Profile 8, not fixtures or filename matching |
| Genuine native maintenance creation | **PASS bounded snapshot** | Own inactive tab, unchanged front/active IDs |

Counts overlap and are not summed as unique tests. An initial five-case test
failure caught a local settings/configuration variable shadowing error, fixed
before installation. A stale 1.3.6 version assertion also failed before being
updated. The genuine 1.3.9 PDF failure is separate from these fixture failures.
No broad frontend/full backend suite or hosted Actions was rerun. For the final
extension-only changes, backend validation was reused because backend code did
not change. No timeout or database connection/pool cap was increased.

Reproduction from the relevant implementation SHA:

```sh
.venv/bin/python -m pytest backend/tests/test_naukri_profile_sync.py backend/tests/test_naukri_upload_preflight.py backend/tests/test_naukri_submission.py -q
.venv/bin/python -m pytest backend/tests/test_naukri_background_queue.py -q -k extension_maintenance
node --test extension/tests/naukri-observation.test.mjs extension/tests/naukri-queue.test.mjs extension/tests/native-protocol.test.mjs
node extension/tests/naukri-execution.browser.mjs
node extension/tests/naukri-queue.browser.mjs
pnpm -C extension build
```

Stop remains slow: one extension cutover's Stop plus verification took **13.882 s**;
the API cutover's Stop plus full inspection took **14.020 s**. These are differently
loaded observations, not controlled performance improvements. New API readiness
needed about 24 seconds after old-PID exit. Existing native/SQL latency remains
open; no CPU/RAM before/after benchmark or definitive locked-browser test occurred.

## Acceptance and next actions

| Requirement | Status | Remaining limit |
| --- | --- | --- |
| Approved account and canonical/provider PDF | PASS actual observations | Fresh per-application proof remains required |
| No repeated update approvals | PASS | Standing owner policy recorded; reviewed installs automated |
| Own inactive setup / actual focused-window guard | PASS bounded actual and regression evidence | Respect owner adoption; no continuous-focus or locked claim |
| Real recurring discovery/filter/match | PASS exercised cycles/exclusions | Uninspected jobs remain unknown; no currently eligible observed candidate |
| Original 128-job inspection cohort | PASS completed at 21:44:11 | 104 excluded, 24 held; no fabricated qualification or application |
| New supported form/Apply and independent receipt | BLOCKED | Zero new admissions/submissions/receipts; do not weaken filters |
| Questionnaire/Cohere/Telegram resumption | NOT ACCEPTED live | No new eligible form reached; existing recurring questionnaire integration unfinished |
| New receipt notification accuracy | NOT TESTED live | No success notification fabricated |
| Recurring AUTOMATIC / 24/7 submissions | OPEN, NOT ACTIVATED | First genuine receipt and critical acceptance required |
| Actual locked-Mac submissions / cold Chrome launch | NOT TESTED | Awake readiness/heartbeat is insufficient |

Keep genuine discovery and durable inspection running under the saved cap-one
authorization. Complete a supported eligible real application and independent
history verification when available, then activate bounded AUTOMATIC only after
the required checks. Preserve Gmail READ + CREATE DRAFT, other platforms disabled,
historical QTrino/uncertain fences, all credentials/data/releases and rollback.
No merge, cleanup, release deletion or hosted job was performed.
