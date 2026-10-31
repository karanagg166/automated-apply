# Autonomous updates installed; Profile 8 reconnected; real submission still OPEN

Branch `fix/live-prepare-discovery-20261030` → `main`, [PR #48](https://github.com/karanagg166/automated-apply/pull/48).
Local date November 1; observations below use **October 31, 2026 UTC**.

The owner explicitly authorized autonomous local Naukri service/extension updates
and asked that future SHA/update approval prompts stop. [AGENTS.md](../../AGENTS.md)
now records that standing authority and the renewed no-focus constraint. Earlier
reports' exact-SHA approval gates describe historical policy, superseded by this
owner instruction. Merge, cleanup, hosted Actions, Gmail sending, other platforms,
submission filters/limits and uncertain/historical replay remain restricted.

**No new Apply admission, submission or receipt. AUTOMATIC remains off.**

## Genuine reconnection and installations

At **20:31:46**, the running queue had 289 records, 71 DISCOVERED, 35 NEEDS_INPUT,
182 SKIPPED and one retained receipt. Its last search error was `owner_tab_active`.
The current Chrome inventory instead established that the bound Profile 8 window
was gone; only another Chrome profile's window was open. API readiness was 200;
selected Profile 8 was `PROFILE_OFFLINE`, commands enabled, last heartbeat
20:26:47. A historical search error was not treated as current browser evidence.

The owner opened existing Profile 8 on a non-Naukri tab after one requested action.
It automatically reconnected on its new window, without a popup/button or new
account approval. Readiness returned **200 in 2.172 s**, selected profile status
returned **CONNECTED**, and the account binding remained approved at revision 1.

| Component | Current exact installed source |
| --- | --- |
| API | `331ce17711667d21bc96c42d8dc74793d670095f`, unchanged |
| Execution worker | [cfd28af4a34d3d631d13191f720f3684775b4f38](https://github.com/karanagg166/automated-apply/commit/cfd28af4a34d3d631d13191f720f3684775b4f38) |
| Same-ID Chrome extension | **1.3.8**, [cf686f853b2c40642e950bba92fcb07ef8b655c1](https://github.com/karanagg166/automated-apply/commit/cf686f853b2c40642e950bba92fcb07ef8b655c1) |
| Telegram / frontend / native host | `fc91a219d5b824f934bb733eaf20166661e1f08b`, unchanged |

Stop and subsequent verification took **12.986 s**, producing STOPPED revision 16
at **20:40:59**. A browser-snapshot guard then stopped the initial installation
attempt **before any file replacement**. The differing snapshot was not retained;
its cause is unproven. Rechecks matched the baseline. No activate/focus command,
keyboard or clipboard operation was issued.

The already inactive Naukri automation homepage had no filled visible fields. It
was temporarily navigated to the ordinary Extensions maintenance page without
selecting a tab/window, then restored to its exact original URL. Other profiles'
pages were not navigated. Extension 1.3.8 loaded at **20:41:59**; exact **22/22**
files, stable ID/key/permissions, account binding, all protected references and
all **296** queue records passed verification at **20:42:12**, queue still stopped.
The final immediate browser snapshot differed again; a later read matched the
original front-window/active-tab IDs. These snapshots do not establish continuous
focus invariance or attribute intervening changes to either user or automation.
The homepage restoration itself passed. Raw evidence remains private.

The worker-only correction fixes a real recovery defect: the startup guard only
looked at the stopped legacy scheduler, ignoring the RUNNING PostgreSQL queue.
It now recognizes either authorized scheduler, fences both with global OFF,
rechecks Stop after lock acquisition and the process probe, and retains the
existing refusal to launch when any normal Chrome is already running. Startup
uses documented `open -g` background LaunchServices behavior. It never treats
launch success as an authenticated connection. Actual cold launch remains untested.

The clean immutable worker candidate had its own venv and passing `pip check`.
Only `backend/app/browser/profile_launcher.py` differs from the previous installed
worker's production backend. The old PID **1078** exited at **20:43:32** before
reference replacement. New PID **3076** passed installation at **20:43:37**.
Only the execution plist changed; extension files and all other protected
references, queue policy and all 296 records remained unchanged.

At **20:44:17**, the queue resumed **RUNNING revision 17**, existing SUPERVISED
cap **1**, hourly cap **1**, concurrency one, all filters unchanged. Thirteen
unprepared, never-admitted metadata failures were safely retried for the corrected
reader. Age/applicant-review and uncertain/submitted records were not reopened.

## Actual post-update behavior

The canonical PDF was decrypted/rechecked in memory: valid PDF prefix,
**100,198 bytes**, stored digest match, confirmed profile/resume, approved binding
revision 1. No email, PDF content or checksum is published. This recheck is not a
new provider-side Download observation; prior actual saved-PDF byte evidence remains
in the [earlier report](naukri-real-pdf-location-fix-20261031.md).

At **20:46:03**, worker heartbeat was **20:45:47**, and genuine Date discovery had
completed **20:44:37–20:44:57**, zero new URLs, no source error, cumulative source
admission count **283**. The persistent 296-record queue contained:

| Stage / reason | Count |
| --- | ---: |
| DISCOVERED | 81 |
| NEEDS_INPUT: posting_age_requires_review | 19 |
| NEEDS_INPUT: applicant_count_requires_review | 3 |
| NEEDS_INPUT: experience_requirement_evidence_conflict | 1 |
| SKIPPED: posting_outside_age_limit | 186 |
| SKIPPED: current_profile_preferences_or_required_skills_exclude_job | 5 |
| Historical SUBMITTED_RECORDED | 1 |
| New Apply admissions / confirmed receipts / ready jobs | 0 / 0 / 0 |

The new experience-conflict reason is an actual installed-browser outcome, not
an offline replay or fixture receipt. No unsupported qualification was inferred.

## Validation, performance and rollback

- **11 focused launcher/startup tests passed, 11 deselected, 0.81 s** in development;
  the same **11 passed / 11 deselected, 0.80 s** in the candidate's own venv.
  These overlap; seven cases are new. They cover the queue with stopped legacy
  scheduler, existing Chrome, disabled platform, global OFF, Pause/Stop and a Stop
  arriving after the process probe. All process calls are fictional in those tests.
- Ruff isolated E9/F/I, diff checks and own-venv `pip check` passed.
- Extension 1.3.8's prior **57 Node / eight Chromium** fixture checks were not
  rerun: its exact source/build was unchanged. Their scope is documented in the
  [previous report](naukri-aa47599-installed-live-20261031.md).
- No broad backend/frontend suite, new dependency version, database migration,
  connection/pool-limit increase, timeout inflation or hosted Actions.
- Stop remains slow: this observation's 12.986 s includes verification, unlike the
  prior 7.199 s request timing; no controlled performance improvement is claimed.
  CPU/RAM before/after were not benchmarked.
- Private rollback inventories preserve all **22** former 1.3.7 extension files,
  their hashes, the exact former aa47599 execution plist and protected references.
  On failure: STOP queue, wait for candidate PID exit, restore the prior worker
  plist or exact extension files, restart/reload and verify. Never roll back database
  outcomes or replay Apply. All historical releases/evidence/files remain protected.

Reproduce the focused source checks:

```sh
.venv/bin/python -m pytest backend/tests/test_phase54_local_mac.py -q -k 'launcher or queue_startup'
.venv/bin/ruff check --isolated --select E9,F,I backend/app/browser/profile_launcher.py backend/tests/test_phase54_local_mac.py
```

| Requirement | Result | Limit / next action |
| --- | --- | --- |
| Owner update authority persisted | PASS | No further SHA/extension approval prompts |
| Profile 8 restart/reconnect | PASS observed | Owner opened existing profile; no popup/button |
| Extension 1.3.8 / recovery worker installed | PASS | Exact inventories and live services checked |
| Canonical resume / approved account preserved | PASS observed | Per-application provider Download capture still required |
| Real discovery and corrected metadata decisions | PASS bounded | No eligible ready application in current snapshot |
| Focus preservation across every instant | NOT ESTABLISHED | No focus commands; snapshot differences retained as unexplained, current IDs match |
| Automatic cold launch when all Chrome is closed | NOT TESTED live | Existing-other-Chrome guard deliberately remains |
| Real new fill/questionnaire/Apply and receipt | BLOCKED | No eligible ready item; no fabricated submission |
| Recurring AUTOMATIC / locked-Mac submissions | NOT ENABLED / NOT TESTED | First genuine receipt and critical acceptance still required |

Next: verify the unattended real saved-resume Download path, continue processing
genuine eligible work, complete supported questionnaires with grounded answers,
and obtain the first independently verified new receipt before bounded AUTOMATIC.
PR #48 and Naukri remain OPEN. No QTrino replay, uncertain Apply retry, Gmail send,
other-platform activation, merge, cleanup or release deletion occurred.
