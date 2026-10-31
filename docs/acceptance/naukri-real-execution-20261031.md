# Live execution: compatibility candidate installed; zero new submissions

Repository `karanagg166/automated-apply`, branch
`fix/live-prepare-discovery-20261030`, base `main`, [PR #48](https://github.com/karanagg166/automated-apply/pull/48).
Implementation [aa47599a3bd8bfb2848844835fbc36654def361b](https://github.com/karanagg166/automated-apply/commit/aa47599a3bd8bfb2848844835fbc36654def361b).
[Sanitized measurements](naukri-real-execution-20261031-metrics.json).
Observation window starts 2026-10-31 17:09 UTC; queue snapshot below is **17:24:02 UTC**.

**Outcome B: zero new submissions, zero new independently confirmed receipts,
zero admitted Apply actions.** The one historical QTrino receipt is retained.
No duplicate, uncertain action replay, policy relaxation or AUTOMATIC activation.
No eligible job has yet been established; **120 records still await inspection**.
This does not establish that no eligible job exists in the backlog or on Naukri.

## Exact installed versions and actual restart

The owner explicitly approved the exact `331ce177...` cutover in response to the
installation question in this session. Only the prepared API/extension scope was installed.

| Component | Actual installed source / observation |
| --- | --- |
| FastAPI | `331ce17711667d21bc96c42d8dc74793d670095f`, new process PID 67601 |
| Profile 8 extension | Same ID, **1.3.6**, `331ce17711667d21bc96c42d8dc74793d670095f`, 22/22 exact files; Chrome's ordinary Reload and displayed version verified |
| Execution worker | `fc91a219d5b824f934bb733eaf20166661e1f08b`, existing LaunchAgent running |
| Telegram worker | Same `fc91a219...`, existing LaunchAgent running |
| Next.js frontend | Same `fc91a219...`, existing LaunchAgent running |
| Native host | Same `fc91a219...`; protected launcher/manifest preserved, genuine profile native traffic continues |
| Follow-up worker/extension candidate | `aa47599a3bd8bfb2848844835fbc36654def361b`, **NOT INSTALLED**, requires its own exact-SHA approval |

Queue Stop at 17:09 took **6.717 s**, producing STOPPED revision 12.
All 243 then-existing queue records were read across both API pages: no active
lease, executing action or unknown action at cutover. The old API PID 58160
exited at 17:10:49 before replacing its plist. New API readiness passed at
17:11:14 (3.635 s request), extension 1.3.6 loaded at 17:11:18, second readiness
passed at 17:11:20 (2.482 s request). Installation verification passed 17:11:29.
Policy, account binding revision 1, record count and protected references matched.
This is actual API restart/reload evidence; it is not acceptance of every component's crash recovery.

At 17:12:43 the queue resumed **RUNNING revision 13**, retaining the owner's
SUPERVISED scope: one new submission, hourly cap 1, Telegram on verified receipt.
The saved global daily cap remains 80, minimum score 80, job age two days,
applicant threshold 10,000, unknown applicants require review, concurrency one,
pending limit 200, background-only. No filter or cap was loosened.

## Genuine discovery, filtering and queue

The persistent queue grew **243 → 252** records. Nine added records came from
previously captured genuine Date-sorted search URLs, not synthetic or guessed
URLs. Seventeen such read candidates were prioritized; 114 other metadata reads
were deferred ten minutes with original availability values preserved privately.
The existing search scheduler performed genuine cycles **17:13:01–17:13:16** and
**17:18:30–17:18:50**; both admitted zero new distinct URLs. Its cumulative
admission counter remained 239; that source counter differs from total queue
records, which include saved sources and the retained receipt. Another cycle was
leased at 17:23:55. Discovery interval remains the configured 300 seconds.
Repeated URLs are deduplicated; these cycles are not 40 new eligible jobs.

The live Date-sorting observer captured zero completed results in this run.
Prior operator-assisted Date evidence is not relabelled automatic acceptance.
The shipped 1.3.6 search consumer still observes default ordering; the follow-up
source corrects this before candidates are admitted.

| Queue / blocking reason at 17:24:02 UTC | Count | Classification |
| --- | ---: | --- |
| DISCOVERED, queued for actual metadata inspection | 120 | Pending, eligibility unknown |
| SKIPPED: `posting_outside_age_limit` | 111 | Observed posting facts fail saved age bound |
| SKIPPED: `current_profile_preferences_or_required_skills_exclude_job` | 4 | Actual matching exclusions |
| NEEDS_INPUT: `posting_age_requires_review` | 9 | Date-only precision cannot establish saved age bound |
| NEEDS_INPUT: `applicant_count_requires_review` | 2 | Provider lower bound does not establish upper limit |
| NEEDS_INPUT: `backend_not_ready` | 2 | Software/remote-transaction failure; read-only work |
| NEEDS_INPUT: `job_required_facts_unrecognized` | 3 | Unsupported or incomplete observed page facts; not personal input |
| Historical `SUBMITTED_RECORDED` | 1 | Retained QTrino; never retried |
| Leased / executing queue jobs | 0 / 0 | Separate search lease is active |
| READY / BLOCKED_PLATFORM / SUBMISSION_UNKNOWN / new receipt | 0 / 0 / 0 / 0 | No new submission admission |

Counts sum to 252: 120 pending, 115 skipped, 16 blocked, one historical receipt.
Applicant-limit-reached, prior-application skips and direct minimum-score skips
were zero in this snapshot. Matching diagnostics on all four persisted inspected
job records found four title mismatches and four missing-required-skill results
(overlapping categories), scores 15–22.5, zero scores at least 80. The queue
records the combined matching reason before the separate minimum-score check.

Actual examples, all job links rather than application receipts:

| Genuine job | Actual result |
| --- | --- |
| [Coralindia Engineer](https://www.naukri.com/job-listings-engineer-coralindia-erode-0-to-4-years-311026008896) | New installed parser recognized **Less than 10 → bounds 0–9**; matching 15/100, rejected |
| [Technical Sales Engineer](https://www.naukri.com/job-listings-technical-sales-engineer-fresher-mel-systems-and-services-chennai-0-to-5-years-311026015511) | Same real 0–9 bound; matching 15/100, rejected |
| [Fullstack Web Developer](https://www.naukri.com/job-listings-fullstack-web-developer-sky-network-computer-academy-asansol-0-to-2-years-230726028832) | Observed 50+ has unknown upper bound; cannot establish applicant limit |
| [Remote/Hybrid Software Developer](https://www.naukri.com/job-listings-wfh-remote-hybrid-software-developer-120-vacancies-phoenix-advanced-bengaluru-0-to-5-years-311026015222) | Observed 100+ has unknown upper bound; cannot establish applicant limit |

Nineteen proven read-only failures were retried once after installation: six
backend-not-ready, seven required-facts and six applicant-count failures. Every
retry excluded admitted actions and prepared packets. Legitimate age and matching
exclusions were retained. Fresh Less-than labels now progress, but those actual
jobs are ineligible; no qualification or applicant/date fact was invented.

## Identity, resume, personal input and platform limits

The canonical encrypted PDF was verified again in memory: **100,198 bytes**,
valid PDF prefix and saved SHA-256 match. The approved account binding remains
revision 1. A supported, read-only profile comparison completed **17:16:15 UTC**
as `COMPARED`, checking the current profile UI account against the approved hash.
No profile values were changed. The temporary comparison enablement had no
approved write fields; its original disabled policy was restored, revision 5.

The [earlier genuine provider Download proof](naukri-real-pdf-location-fix-20261031.md)
is preserved. This run did not reach per-application unattended provider-PDF
capture, Apply, questionnaires, Cohere answers or independent new history
reconciliation. Fresh account/resume and prior-application checks remain required
by the installed admission path. No essential missing personal answer has been
established, so no repeated identity question or Telegram personal prompt was sent.

No CAPTCHA, rate-limit or access-control refusal was established as this run's
submission blocker. Unknown dates/counts are provider-evidence limitations;
required-facts failures still need exact page diagnosis. Questionnaires and
unsupported multi-step forms remain capability gaps, not successful automation.

## Software defects and focused correction

Actual new installed requests still returned **HTTP 503 / `lock_timeout`**:
two metadata admissions and one heartbeat in the retained timing sample.
Owner-row lock waits were approximately **2.16–2.17 s**. The 104 mixed request
samples had HTTP min/median/max **1.552 / 2.997 / 13.273 s**; these are not
104 discovery polls. The API repeatedly holds owner transactions over many
remote statements. This is not pool-capacity proof; capacity/timeouts were unchanged.

`queue_preparation.prepare_one` also takes the owner lock on idle ticks when only
browser inspections exist. Follow-up source adds an unlocked scheduling check;
real claims still revalidate policy/leases under the original lock. Expired Apply
leases still become unknown and are never redelivered. This removes one proven
unnecessary competitor; it does **not** claim to solve all native transaction latency.

The same candidate adds automatic ordinary **Sort → Date** selection in the
worker-owned inactive search tab before candidate observation. It checks exact
provider/path, owner adoption, challenge state, unique supported controls and
confirmed Date label; no guessed URL parameters, owner focus or unrelated click.
Unconfirmed/unsupported sorting yields an explicit reason, not silent success.

Changed implementation: `backend/app/execution/queue_preparation.py`,
`extension/naukri-queue.js`, version 1.3.7, focused tests and PostgreSQL verifier.
No schema, HTTP/native contract, dependency-version or permission changes.

| Validation | Exact result | Scope |
| --- | --- | --- |
| Backend queue/native/submission regressions | **65 passed, 9.67 s** | Fictional isolated fixtures, six new cases |
| Date/queue Node regressions | **30 passed, 1.690 s** | Fictional DOM/native fixtures, 16 new cases |
| Isolated Chromium queue cases | **7 passed, 55.328 s** | Actual isolated inactive tabs, fictional pages, zero live/unexpected requests or choosers |
| Fresh disposable PostgreSQL 14.24 | **9 passed, 0.340 s** | Two fixture connections; no production DB or application |
| Exact candidate own-venv smoke | **7 passed, 22 deselected, 0.97 s** | Snapshot/venv actually intended for installation |
| Ruff E9/F/I, Prettier, diff, extension build, own pip check | PASS | Relevant changed files; 22/22 exact build bytes |

The PostgreSQL contention experiment held the actual owner row lock. The former
idle claim path failed `55P03` under a 100-ms fixture lock timeout; the corrected
idle preparation returned in **0.002040 s** without taking that lock. This is a
fixture comparison, **not a measured live speedup**. Live search durations 14.953
and 20.248 seconds are uncontrolled observations. CPU/RAM before/after benchmarks
were not performed. No timeout/pool increase was used in production.

An initial Node run had one failing test because its fixture returned the wrong
operation after binding; correcting that fixture produced the 30-pass result.
Two private operator helpers initially failed (model configuration order; expired
ORM attributes after rollback); they were corrected, with no DDL or action replay.
Actual live 503s remain FAIL evidence, not replaced by fixture success.

Reproduce fixtures only, from the implementation SHA:

```sh
.venv/bin/python -m pytest backend/tests/test_naukri_background_queue.py backend/tests/test_application_queue.py backend/tests/test_naukri_submission.py -q
node --test extension/tests/naukri-date-sort.test.mjs extension/tests/naukri-queue.test.mjs
node extension/tests/naukri-queue.browser.mjs
python backend/scripts/verify_application_queue_postgres.py --url postgresql://postgres@127.0.0.1:DISPOSABLE_PORT/candidate_profile_test
pnpm -C extension build
```

The PostgreSQL verifier requires a fresh fictional loopback database and refuses
normal/production ports. Its temporary server was stopped; files were preserved.

## Concrete follow-up installation and remaining actions

Immutable candidate **aa47599a3bd8bfb2848844835fbc36654def361b** has an independent
source snapshot, own pinned Python environment, passing pip check and exact
22-file extension build. Prepared private inventory backs up the current execution
plist and extension 1.3.6, and hashes eight protected service/native/config files.
It is **not installed**; prior approval of `331ce177...` does not approve this SHA.

After exact owner SHA approval: stop/fence queue, verify no active/uncertain write,
revalidate inventories, stop only the old execution worker and confirm PID exit,
install its prepared plist, start the candidate worker, deploy same-ID 1.3.7 and
use ordinary Reload. **API stays 331; Telegram/frontend/native stay fc91.** Verify
unchanged account/resume/policy/receipts and genuine heartbeat, then resume the
standing one-application scope. No full frontend build or unrelated deployment.

Rollback: keep queue stopped, retain unknown outcomes, stop candidate worker,
restore exact fc91 execution plist and 22 extension 1.3.6 files, start/reload and
verify protected hashes. Never roll back the database, erase outcomes or replay Apply.
All historical releases, PDFs, configurations and rollback files remain intact.

| Acceptance requirement | Status | Remaining action |
| --- | --- | --- |
| Approved 331 API/1.3.6 installed; real API restart | PASS observed | Preserve exact inventory |
| Current approved profile account / local canonical PDF | PASS observed | Per-job fresh provider resume proof still required |
| Real recurring discovery / queue processing | PASS bounded | Continue finite recent-candidate inspection; do not equate URLs with applications |
| Less-than applicant parser on genuine pages | PASS observed | Actual parsed examples fail saved fit policy |
| At least one new eligible application and independent receipt | BLOCKED | No eligible inspected job; backlog uninspected; retain filters |
| Native/DB lock reliability | FAIL | Follow-up idle-lock fix built; broader transaction latency remains |
| Automatic Date sorting | BLOCKED installation | Exact aa47599 approval, then genuine installed observation |
| New questionnaire / unattended resume / receipt / Telegram result | NOT TESTED live | Need eligible job and supported flow; no false success notification |
| Recurring AUTOMATIC | BLOCKED | First genuine receipt plus critical acceptance; standing limits retained |
| Awake locked-browser submissions / extended reliability | NOT TESTED | 12 samples: 11 UNLOCKED, one UNKNOWN, none LOCKED; no locked-operation claim |

Raw evidence stays private; this report publishes sanitized counts, codes and
job URLs. No Gmail sending, other-platform activation, hosted Actions, PR merge,
destructive cleanup, production-data replacement or QTrino/unknown replay.
