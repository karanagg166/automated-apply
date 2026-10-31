# Owner-requested threshold 50: installed and running on real Naukri

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030` → `main`.
Implementation: [f90cfe7ea3dfc7ca20efe1a1995b3da26707a028](https://github.com/karanagg166/automated-apply/commit/f90cfe7ea3dfc7ca20efe1a1995b3da26707a028).
Local date November 1; observation times below are October 31, 2026 **UTC**.
[Sanitized measurements](naukri-score50-live-20261101-metrics.json).

**Naukri remains OPEN. The actual saved minimum score is now 50 and the durable
queue is RUNNING. No new application or receipt is claimed.** The one-new-eligible
application authorization remains enabled with supervised cap 1 and hourly cap 1.
Recurring AUTOMATIC still requires the first genuine receipt and critical checks.

## Change and exact installed release

The API previously rejected a minimum score below 80. Its policy contract now
accepts 50–100, and the dashboard input permits 50. Defaults for unconfigured
installations stay 80. The actual owner policy was changed from **80 to 50**;
every other policy field was verified equal. Age, applicant, skill, location,
experience, salary, exclusion, identity, resume, prior-application and quota
checks still apply. A score alone is not submission authorization.

| Component | Current exact source |
| --- | --- |
| API, execution worker, frontend, Telegram | `f90cfe7ea3dfc7ca20efe1a1995b3da26707a028` |
| Stable-ID extension 1.3.11, unchanged 22/22 files | `33a132edce50252693b17dd2e6cf176a53f24710` |
| Native host, unchanged | `fc91a219d5b824f934bb733eaf20166661e1f08b` |

Autonomous local installation follows the owner's standing authorization in
[AGENTS.md](../../AGENTS.md). No new SHA/extension consent was requested.
No Chrome focus, keyboard, clipboard or extension maintenance action was used
for this update. Other platforms and Gmail sending were not activated.

## Actual cutover and policy evidence

- **22:20:38**: STOPPED revision 24, **297 queue records**, approved account
  binding revision 1. Stop plus paginated inspection took **18.816 s**; this is
  not a standalone Stop latency measurement or a performance improvement claim.
  No leased/executing/unknown work or admitted application action remained.
- Previous execution, API and frontend processes exited before replacing their
  references. The pinned build has its own Python environment, frontend package
  links and production output; installed historical releases were preserved.
- **22:21:08**: exact candidate installed; API/database readiness **200**,
  frontend `/login` **200**, execution process running. Queue remained STOPPED;
  all 297 records and the approved binding were verified unchanged.
  Protected Telegram/native/credential references and extension files matched.
- **22:21:40**: owner API compare-and-swap saved only
  `global_limits.minimum_match_score: 80 → 50`, then started the queue at
  **revision 26**. Naukri remained enabled, SUPERVISED, submission-authorized,
  cap 1/hour 1. This enables an eligible first real attempt without a per-job
  prompt; it does not establish a submitted application.
- **22:21:53–22:22:13**: actual installed discovery cycle completed, **0 newly
  distinct jobs**, no source error. Durable discovery admission count remained
  284. Zero new jobs in this cycle is not proof of new-job discovery or submission.
- **22:22:52**: nine unprepared, previously matching-rejected records were queued
  for fresh ordinary UI inspection under the new threshold. Each was checked
  against prior-application/uncertain history; none had a packet or admitted
  action. No historical receipt, uncertain submission, age rejection or missing
  metadata hold was reopened. Fresh listing facts and all admission checks still
  determine the outcome.
- Telegram's installed command handlers also import the queue policy contract.
  Polling alone did not establish compatibility with 50. That dependency was
  caught during continuation review: **22:27:41**, queue STOPPED revision 27,
  all **297 records** and zero admitted/uncertain actions verified. The old
  Telegram process exited; its same pinned `f90cfe7` replacement passed scoped
  reference/integrity checks at **22:27:54**. No message was sent as an acceptance
  shortcut. Queue resumed at **22:27:58**, revision **28**, with the exact same
  score-50 policy and caps. An in-progress read-only search was fenced by Stop;
  `global_stop` is a retained cancellation, not a successful discovery cycle.
- **22:25:06**: post-install API/database readiness **200 in 2.315 s**;
  frontend login **200**, selected native profile **CONNECTED**, commands enabled,
  recent heartbeat. These readiness checks are not locked-screen browser proof.
- **22:30:30**: after all four services were updated, readiness again **200 in
  2.134 s**, frontend **200**, native **CONNECTED**, queue **RUNNING revision 28**,
  minimum **50**, **297 records**. **22:31:04**: all four process references and
  protected native/credential/rollback/22-file extension integrity rechecked.
- **22:33:30**: all nine fresh browser rechecks finished: **7 SKIPPED** for
  current preferences/required skills; **2 NEEDS_INPUT** for applicant-count
  ambiguity. Across the complete queue: **224 SKIPPED**, **72 NEEDS_INPUT**, and
  the **1 retained historical receipt**. **0 admitted application actions,
  0 new receipts**. No submitted or uncertain record was retried.
  Completion was observed **638.619 s after requeue**, including the Telegram
  cutover, source cycles and observation intervals; this is not pure job latency.
- **22:33:46**: the actual HTTP-served queue JavaScript returned **200** and
  matched the pinned candidate bytes exactly, including the minimum-50 input.
- **22:33:56**: the exact installed Telegram queue handler successfully read the
  real online database with the saved threshold 50. This was a direct read-only
  handler call, **not** a bot-message roundtrip; no message was sent.
- Additional actual completed discovery cycles: **22:28:21–22:28:42** and
  **22:33:23–22:33:45**, both with zero newly distinct URLs and no source error.
  Final **22:34:28** snapshot remained RUNNING at 50 with the same 297 records,
  zero admitted actions/new receipts, and a fresh live Telegram poll without an
  error. Screen telemetry had become **UNKNOWN**, which is not a locked sample.
- **22:34:57** final readiness: API/database **200 in 2.373 s**, frontend **200**,
  native **CONNECTED**, queue RUNNING revision 28 at 50. These are individual
  observations, not a controlled performance comparison. Resource limits and
  timeouts were not raised; no CPU/RSS benchmark or contention fix is claimed.

The approved platform binding and two genuine provider PDF-byte matches from the
[previous installed acceptance](naukri-real-resume-background-20261101.md) were
preserved. They are not reused as Apply permits: each eligible application still
requires fresh bound account/resume/prior-status evidence.

## Real eligibility, limits and remaining failures

The **22:21:48** read-only diagnostic evaluated **282 actual persisted listing
fact records**, using the new saved threshold. **12 scored at least 50; all 12
failed the posting-age check. Zero was fully eligible.** Recent inspected matching
rejects also had unsupported required skills and, for some jobs, title mismatch.
Required company-stage/startup evidence was absent. These overlapping reasons
were retained; lowering a score threshold did not approve unknown facts.

This diagnostic did not click Apply, grant an action, invent company data,
change a candidate profile, or replace an independent provider receipt. Fresh
browser rechecks are tracked separately from this persisted-fact calculation.

| Acceptance | Result | Evidence / remaining action |
| --- | --- | --- |
| Saved threshold 50 across API/worker/dashboard | PASS | Compatible pinned build; actual owner API read-back |
| Queue running, first-attempt cap preserved | PASS | Revision 28 after Telegram update; SUPERVISED 1/hour 1 |
| Protected records, binding, credentials and extension | PASS | Stopped cutover, record counts and protected hashes |
| Actual discovery after restart | PASS | Completed 22:21, 22:28 and 22:33 cycles; zero newly distinct URLs |
| Nine actual fresh browser rechecks | PASS | Seven matching exclusions, two applicant holds; no Apply |
| Eligible new application | BLOCKED | No qualifying job; other configured requirements still apply |
| New Apply and independently verified receipt | NOT TESTED | No eligible submission admitted |
| Recurring AUTOMATIC and receipt notifications | BLOCKED | First verified new receipt still required |
| Questionnaire/Cohere/Telegram answer resumption | BLOCKED | Recurring questionnaire adapter still unfinished |
| Locked-screen browser/application acceptance | NOT TESTED | Earlier UNLOCKED samples, final UNKNOWN telemetry; no verified LOCKED sample |
| Stop latency and DB contention improvement | NOT TESTED | No controlled performance comparison or timeout/limit tuning in this change |
| Continuous 24/7 real submissions | NOT TESTED | Do not describe running discovery as completed application automation |

## Targeted verification and reproduction

- Backend queue regressions: **18 passed in 1.75 s**, including the new boundary
  and unchanged-limit regression. Pinned candidate repeated those same **18 in
  1.96 s**; these are overlapping fixture cases, not 36 independent tests.
- Frontend queue tests: **7 passed**, including saving 50 while preserving other
  limits. These are isolated fixtures, not provider acceptance.
- Telegram URL enqueue and pause/resume guards at thresholds **50 and 80**:
  **2 passed in 0.32 s**. This follow-up changes only tests; installed runtime
  implementation remains exactly `f90cfe7`. It is not a Telegram message roundtrip.
- API export/type regeneration, frontend typecheck, changed-file Prettier,
  Python Ruff, Git whitespace check, pinned Python dependency check and pinned
  frontend production build passed. No broad unchanged suites or hosted Actions
  were run. API type regeneration produced no TypeScript contract diff.

```sh
.venv/bin/python -m pytest backend/tests/test_application_queue.py -q
.venv/bin/python -m pytest backend/tests/test_naukri_submission.py::test_telegram_job_url_uses_same_queue_and_pause_fence -q
pnpm -C frontend test tests/application-queue.test.tsx
pnpm -C frontend typecheck
pnpm -C frontend build
```

In the authenticated dashboard, set **Global minimum match score = 50**, save,
then Start Queue. Verify the returned configuration and unchanged platform caps;
watch actual source-cycle timestamps, queue outcomes and provider receipts.
Do not reset a submitted/uncertain record to reproduce processing.

## Rollback retained

A private exact-SHA installation plan and separate Telegram plan preserve all
four previous LaunchAgent definitions, frontend launcher, credential/native/
reference hashes and all 22 extension hashes. Previous API `82d46e3`, worker
`cfd28af`, frontend and Telegram `fc91a21` remain intact. Old policy consumers
reject 50: rollback must first Stop, restore
only the threshold to 80 through the compatible API, verify it, then restore the
previous service definitions. Preserve all outcomes; never restore a database
snapshot over intervening applications. The installer restores prior service
references on cutover failure before saving 50. This cutover succeeded; rollback
was not exercised. No historical release or rollback file was deleted.

Next: continue discovery and admit only a qualifying new job,
complete its supported form once, independently verify history on separate
documents, then consider bounded recurring AUTOMATIC. Keep first-receipt,
questionnaire and locked-Mac gaps visible until genuine acceptance exists.
