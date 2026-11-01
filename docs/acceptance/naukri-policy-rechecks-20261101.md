# Naukri policy answers, durable rechecks and restart evidence — 2026-11-01

**OPEN. No new verified submission; recurring AUTOMATIC is not enabled.**
[PR #48](https://github.com/karanagg166/automated-apply/pull/48), base `main`,
implementation branch `fix/live-prepare-discovery-20261030`.

## Exact implementation and installed components

- [cd342bf4698c0d182a2f2cbc445760fa5ee693a7](https://github.com/karanagg166/automated-apply/commit/cd342bf4698c0d182a2f2cbc445760fa5ee693a7): explicit lower-bound applicant option, persistent dashboard policy question and bounded reconsideration of unattempted records after filter/new confirmed-profile changes. Installed API, frontend and Telegram remain this SHA.
- [9cf6cb6f3bda0973daca2a62d0b4ae63ef1fd401](https://github.com/karanagg166/automated-apply/commit/9cf6cb6f3bda0973daca2a62d0b4ae63ef1fd401): move retained-fact analysis outside the owner lock; revalidate authority, work revisions and receipt/uncertain-packet fences inside it. Native transport retries queue commands only after an explicit `X-Automated-Apply-Transaction: rolled-back` response. Installed native wrapper points to this exact immutable release.
- [713a8f31e25d3a03dc2a60d2cb80da585e3b490d](https://github.com/karanagg166/automated-apply/commit/713a8f31e25d3a03dc2a60d2cb80da585e3b490d): lower-priority rechecks use `FOR UPDATE SKIP LOCKED` and defer when owner work is busy. Other lock callers retain blocking behavior and transaction/savepoint cache rules. Installed execution worker is this SHA.
- Extension remains 1.3.17 / `ee7d045d3460994de1cb0831b937a7dd411e0b39`, all 23 files unchanged, stable ID unchanged. No Chrome reload, tab/window activation, keyboard or clipboard operation was used for these installations or frontend checks.

Previous exact releases, four-service and worker/native rollback inventories,
private configuration, application history and data remain retained. No migration,
new broker, connection-limit increase, application timeout increase, hosted Action,
merge, Gmail send or other-platform activation occurred.

## Behavior and permission boundary

The owner can select an applicant rule that accepts an explicit lower bound below
the threshold, such as `100+` against 1,000. The UI states that actual counts may
exceed the threshold. Entirely missing counts and ranges crossing the threshold
still require review with this option. Negative/reversed bounds are rejected;
counts at or above the threshold remain excluded. **Installation did not choose
this exception: live policy remains `needs_review`.** The once-asked owner decision
is pending; the new dashboard notification is deduplicated.

A filter edit or newly reviewed profile version requests batches of at most ten
held records. Rechecking reuses the existing requisition identity and cursor; it
never grants a packet, preparation or Apply from retained facts. Passing records
must receive a fresh ordinary listing read and complete current eligibility checks.
Any admitted action, packet/form, active lease, receipt existence, uncertain or
terminal packet, or previously applied job prevents reopening. Queue capacity,
current policy/profile revision and newer reconsideration requests are revalidated
under the existing owner fence. Busy owner work defers this maintenance operation.

## Validation: fixtures versus actual Mac/provider evidence

Counts below overlap and must not be added together as unique coverage.

| Check | Result | Evidence and limits |
| --- | --- | --- |
| Initial reconsideration regressions | PASS | 21/21 source, 14.66s; exact cd342 candidate 21/21, 2.76s. Fictional SQLite facts, no provider actions. |
| Race/transport regressions | PASS | 58/58, 4.80s; exact 9cf6 candidate 58/58, 5.13s. Covers Stop/profile/request/action/receipt races and all eight queue operations across explicit rollback, unmarked 503, timeout and retry exhaustion. No ambiguous response is retried. |
| Final deferred-recheck/cache regressions | PASS | 33/33 source, 3.80s; exact 713 candidate 33/33, 4.05s. Includes 27 reconsideration cases plus six timing/transaction-cache checks. Fixtures, not live application acceptance. |
| Frontend | PASS | 298/298 across 40 files, 17.36s; source typecheck, selected Prettier and regenerated API types passed. The pnpm script ran the whole suite despite requested filenames; no repeat full run was made. |
| Exact cd342 frontend production build | PASS | Build 13.519s; independent candidate virtual environment, pip check and frozen offline pnpm install passed. |
| Installed frontend | PASS | Actual cd342 LaunchAgent root verified; isolated headless local owner session rendered 14 days / 1,000 / score50, review rule, new explicit option, 30-minute profile polling, zero new receipts/one historical record. 19.988s, zero external requests and zero writes. Password-login flow not tested. |
| Four-service installation | PASS | STOP revision58, 496 records; API ready200, frontend login200, fresh execution heartbeat, all four service PIDs, full profile/account/policy equality and protected-file checks. Resumed RUNNING59 with unchanged SUPERVISED1/hour1. |
| Worker/native update | PASS | STOP60, 516 records, ready200, profile5/binding1/protected components unchanged; resumed RUNNING61 after fresh worker heartbeat. Framed native health succeeded in13.575s. |
| Deferred worker update | PASS | STOP62, 537 records, ready200, protected API/frontend/Telegram/native/extension unchanged; resumed RUNNING63 after fresh heartbeat. Native9cf framed health15.862s. |
| Stop latency | FAIL / improving | Actual STOP durations7.731s,17.950s,10.387s. These are not acceptable instant-control claims. No deadlines or pool limits were enlarged. |
| Lock/restart recovery | PARTIAL | A real native cycle failed `backend_not_ready`; API timing established a2.164s SQL lock timeout/explicit rollback rather than dependency readiness failure. Three independent ready probes returned200 in2.089/2.403/2.039s. Transport recovery and shorter/deferred maintenance added. Later real search completed18:06:38 and18:11:53UTC with no error; extended contention acceptance remains open. |
| Online deferred-lock measurement | PASS, bounded | Corrected instrumentation18:11:51UTC:6.382s whole transaction,11 pre-fence SQL round trips, owner fence not acquired, zero inside-fence statements, no work changed. This proves actual busy deferral, not successful-batch lock duration. |
| Durable rechecks | PASS, bounded | Actual online worker marker18:12:25UTC:460 records checked,3 fresh listing reads scheduled on existing identities; marker still pending.537 total records,322 skipped/182 held/32 discovery pending/1 historical. Zero admitted Apply actions and zero new receipts. Retained-fact checks are not460 fresh provider visits. |
| Repeated genuine profile/resume comparison | PASS, bounded | Actual18:08:43UTC portal comparison: canonical/provider PDF100,198bytes, `MATCHED_PDF_BYTES`; name/summary matched, national phone and education/employment presence remain details-unverified. Skills conflict and missing projects/location remain real questions. No provider Save. |
| Telegram | PASS, bounded | Actual17:25:44UTC identity-bound live poll, no error. Four-service update preserved approved channel data. New submission notification is untested because no new submission exists. |
| PostgreSQL resource sample | PASS, bounded | Actual18:12:25UTC:4 role sessions,0 lock waiters,2 idle-in-transaction sessions at the observation instant. Role cap5 unchanged; this snapshot does not prove absence of long transactions. |
| First new application + independent receipt | BLOCKED | No eligible application has completed all live prerequisites; unknown-count decision remains pending. No QTrino or uncertain submission replay. |
| Recurring AUTOMATIC / locked-screen forms | NOT TESTED | First new independently verified receipt and critical checks still required. Heartbeat/readiness is not proof of locked-screen filling/submission. |
| Apollo/SignalHire | BLOCKED / account investigation | No runtime API keys or live enrichment/draft. Owner requested free agent-led setup. Read-only account evidence establishes an existing SignalHire account with historical free-credit notices; current login, API entitlement and credits remain unverified. No duplicate account, purchase or password reset made. |

The current software has not demonstrated recurring applications. In addition,
the first-receipt prerequisite remains an operator acceptance requirement; this
report does not claim that changing every dashboard mode is already protected by
a new server-side first-receipt gate. That remains critical before AUTO activation.

## Failures retained and corrected

- Native `backend_not_ready` concealed a queue transaction lock timeout. Explicit
  rollback-only recovery now preserves the request payload/ID; unmarked responses,
  transport timeouts and disconnects remain uncertain and are not replayed.
- The first direct online measurement of9cf waited for a busy owner lock and
  aborted with `LockNotAvailableError`. Its transaction rolled back; lower-priority
  rechecks now defer instead. No successful timing was inferred from that failure.
- An observer queried an incorrect notification table name and rolled back;
  corrected read uses `owner_notifications`. No data mutation from that error.
- The first frontend acceptance helper used a nonexistent label and failed.
  Corrected helper used the actual rendered label; final verification above is
  from the corrected run. Raw DOM/error output stayed private.
- First deferred-lock instrumentation marked an attempted lock as acquired even
  when SKIP LOCKED returned no row. Corrected run explicitly records acquisition
  false; the earlier private artifact is retained and not used as lock-duration
  proof.

## Reproduction and remaining work

```sh
.venv/bin/python -m pytest backend/tests/test_queue_reconsideration.py backend/tests/test_native_queue_rollback.py -q
.venv/bin/python -m pytest backend/tests/test_request_timing.py backend/tests/test_agent_execution.py::test_owner_lock_reuse_ends_at_commit_or_savepoint_rollback -q
pnpm -C frontend exec vitest run tests/application-queue.test.tsx tests/profile.test.tsx tests/naukri-automation.test.tsx
pnpm -C frontend typecheck
pnpm -C frontend build
```

Do not run fixture tests against production PostgreSQL. Live observers require the
existing private pinned runtime configuration, one operator connection at a time,
and publish only sanitized summaries. Raw provider/profile/mailbox data and all
rollback material stay private.

Next: finish the existing recheck cursor, verify successful batch lock duration,
continue real discovery/eligible matching; honor the pending explicit count
choice without repeating the chat question. Complete supported profile updates
only with grounded facts and persistence evidence. Proceed once through a new
eligible supported form, independently reconcile persistent receipt, then evaluate
bounded recurring AUTO and genuine restart/locked-screen acceptance. Keep other
platforms disabled until Naukri is accepted. The project is not complete or mergeable.
