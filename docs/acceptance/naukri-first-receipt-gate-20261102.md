# Naukri recurring AUTO first-receipt prerequisite — 2026-11-02

**OPEN. No new verified live submission.** This closes a server-side prerequisite
gap; it is not a successful real application or recurring-AUTO acceptance.

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), base `main`, branch
`fix/live-prepare-discovery-20261030`.
Implementation [2ceea5e4ab5662e041a58c6ec7d4aa73e86d51f7](https://github.com/karanagg166/automated-apply/commit/2ceea5e4ab5662e041a58c6ec7d4aa73e86d51f7).
This supersedes the earlier report's remaining software first-receipt gap.

## Behavior

Enabling authorized Naukri AUTOMATIC, starting it from a saved policy, and
admitting any AUTO write now require a strict, independently persistent worker
receipt and its matching confirmed queue record. Proof must belong to the current
approved candidate/platform account/binding revision and include an admitted
Apply. The stored receipt must pass the existing two-document provider-history
validation. An Apply click alone, operator/historical observations, damaged
receipts, reconciliation without an admitted Apply, unknown work and an old or
different account do not qualify. Historical QTrino is never replayed or counted
as the first new worker receipt.

The initial supervised flow remains available. An AUTO edit rejected before the
first receipt does not fence, mutate or interrupt that first supervised lease.
Eligibility, fresh account/PDF evidence, daily/hourly reservations and replay
protections still run for each actual write. This prerequisite does not itself
claim completion of the critical live/restart/locked-screen acceptance checks
required before the agent activates recurring AUTO.

Proof lookup filters and joins the relevant receipt/work identities and streams
newest proofs in batches of ten, closing the cursor once proof is found. It does
not reload the complete growing history ledger. SUPERVISED does not run this
additional AUTO query. There is no testing-only production bypass, new schema,
broker, provider call, connection-limit increase or application-timeout increase.

## Exact installed state and rollback

API, execution and Telegram installed exact2ceea5e at19:03:18UTC on2026-11-01
(2026-11-02 in the owner's timezone). Frontend remains
`cd342bf4698c0d182a2f2cbc445760fa5ee693a7`; native remains
`9cf6cb6f3bda0973daca2a62d0b4ae63ef1fd401`; extension remains1.3.17 /
`ee7d045d3460994de1cb0831b937a7dd411e0b39`, same stable ID and23unchanged files.
The newest source/documentation commit must not be mistaken for every installed
component's SHA.

Replacement used STOP76 with541identities. Exact prior API2cea68b and
execution/Telegram76ba3b7 plists, runtimes, private configuration and rollback
inventory remain retained. Startup kept the full database schema/grant audit.
APIready200/frontendlogin200, fresh execution heartbeat, full profile/account/policy
readback equality and protected-file checks passed. No Chrome operation, reload,
activation, keyboard or clipboard use was needed. All historical releases,
credentials, confirmed facts, bindings and application outcomes remain preserved.
No database snapshot restoration or application replay is a rollback mechanism.

RUN77 resumed the unchanged SUPERVISED1/hour1 policy at19:04:39UTC after a fresh
worker heartbeat; framed native health passed in9.881s. Filters remain14days,
1,000applicants, score50, all company stages; unknown counts still require review.
No other job platform, Gmail sending, hosted Action or merge was enabled.

## Evidence matrix

Counts overlap and must not be summed as unique coverage. No fixture is live
provider acceptance.

| Requirement / check | Result | Evidence and limit |
| --- | --- | --- |
| Relevant shared queue/native/questionnaire regressions | PASS |151/151 source,27.05s, across eight affected files. One subsequently added first-supervised-preservation case passed separately1/1,0.53s. |
| Exact candidate | PASS |152/152,25.20s, independent candidate virtual environment; requirements install/pip check passed. Files: new AUTO proof tests, queue, native submission/background, questionnaires, rechecks, capacity, batch admission. |
| First supervised flow survives rejected AUTO edit | PASS, fixture |Real native/queue code over isolated fake pages leaves the leased first application and policy unchanged, then admits its supported Apply. Stored internal action ledger is checked directly rather than inferred from the public transport. |
| Proof can unlock later AUTO admission | PASS, fixture |First application uses actual supervised fixture pipeline, an admitted Apply and two independent fake provider-history documents; only then can policy become AUTO and the second fictional job receive admission. This is not a real employer receipt. |
| Historical/damaged/uncertain/account-mismatch proof | PASS, fixture |Historical prefix, nonpersistent receipt, missing admitted Apply, wrong account, changed binding revision, reconciliation-only, missing queue work and uncertain stage all fail. Previously saved AUTO cannot Start or write without proof. Failed admission consumes no daily reservation. |
| Existing limits and integrity | PASS, fixture |Daily/hourly caps, explicit lifetime supervised1 allowance, uncertainty/no-replay, current eligibility/PDF/account and bounded queue cases remain covered. Shared fixtures now model supervised initial applications rather than assuming receipt-less AUTO. The isolated multi-job fixture cap5 is not a production policy change; live cap1 remains unchanged. The hourly test uses cap2 below that fixture allowance to test the independent hourly limit. |
| Code checks | PASS |Ruff isolated E9/F/I on changed files and git diff whitespace check. No API contract/schema change or frontend code/build change. |
| Real online source predicate before install | PASS, negative |18:57:59UTC, PostgreSQL REPEATABLE READ READ ONLY,5.046s including connection: `automatic_first_verified_worker_receipt_required`;0policy mutations,0Apply actions. Explicitly source code at this point, not installed evidence. |
| Installed online prerequisite | PASS, negative |19:07:51UTC, exact installed API root checked, PostgreSQL READ ONLY,4.615s including connection. Same fixed denial; RUN77/SUPERVISED1/current review rule unchanged. No live AUTO policy change or submit was attempted to test rejection. |
| Installed readiness/data preservation | PASS |STOP76/541identities; API200/frontend200/profile5/binding1/full policy equality/protected files; all three service PIDs and new worker heartbeat. Raw values and rollback material private. |
| Stop latency | FAIL / unresolved |This replacement's Stop10.413s. Earlier5–13s variation remains; this work does not claim instant Stop or complete contention resolution. |
| Live discovery/profile behavior | PARTIAL |Previous installed releases have actual repeated discovery and approximately30-minute saved-PDF checks; current installed observation19:04:53UTC had a real leased search, no Apply. A leased search/heartbeat alone is not completion of that cycle. |
| First new genuine application/receipt | BLOCKED |0newverifiedreceipts/0admittedApply at the latest observation; first submission acceptance remains open. Existing applicant-count decision remains pending. |
| Recurring AUTO and locked-screen forms/submission | NOT TESTED |Not activated. No new live receipt; no locked-form acceptance claimed from readiness/heartbeat. |
| Remaining missing profile facts / portal writes | OPEN |Known summary/name and saved PDF match; skills differ, projects missing on portal, current location missing locally. Existing owner questions persist; no unsupported fact or save is invented. |

During development, one positive fixture used a disabled discovery source and the
hourly case initially collided with the fixture supervised limit; both fixtures
were corrected without weakening production guards. Two assertions also assumed
an APPLYING label or public action ledger that the existing direct-admission /
transport contract does not expose; corrected assertions inspect executing Apply
and persisted internal evidence. The final exact candidate passes all152. No
failing candidate was installed.

## Reproduction and next acceptance

```sh
.venv/bin/python -m pytest backend/tests/test_naukri_automatic.py backend/tests/test_application_queue.py backend/tests/test_naukri_submission.py backend/tests/test_naukri_background_queue.py backend/tests/test_naukri_questionnaires.py backend/tests/test_queue_reconsideration.py backend/tests/test_queue_capacity.py backend/tests/test_naukri_batch_admission.py -q
.venv/bin/ruff check --isolated --select E9,F,I backend/app/execution/naukri_automatic.py backend/app/execution/application_queue.py backend/app/execution/queue_preparation.py
```

Tests use isolated fictional data. Production proof inspection requires the
existing owner-approved private PostgreSQL configuration and one observer at a
time; never seed a receipt to enable AUTO. Do not issue a live AUTO mutation merely
to test that a guard should reject it. Raw profile/browser/mail/resume data,
credentials and private logs must not be published.

Continue eligible real discovery under the current policy and complete one
supported real application with an independently persistent receipt. The pending
count choice is not selected automatically and is not asked again. Independently
finish supported evidence-backed profile operations while missing personal facts
remain explicit. Then verify critical conditions and bounded repeated AUTO,
restart and genuine locked-Mac browser behavior before claiming Naukri complete.
The expanded project and other platforms remain unaccepted.

[Earlier actual discovery, capacity, Stop and profile evidence](naukri-policy-rechecks-20261101.md).
[Current complete execution plan](../plans/2026-11-01-real-automation-execution.md).
