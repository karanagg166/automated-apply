# Browser unavailable after continued discovery — Naukri OPEN

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`. Reviewed source:
`7842fd5c4f7f6f66fa77375720f5cbdd109cb8e8`. No production code or installed
component changed in this observation. Installed API remains0e75386, extension
1.3.23/0c8b1d7, frontend/native414a260 and execution/Telegram2ceea5e.
Exact installation and rollback remain in the
[installed inspection report](naukri-live-inspection-order-20261102.md).
All times below are UTC on November3.

## Authoritative current evidence

At17:26:18, the live PostgreSQL queue contained1,585 durable identities:
1,024 SKIPPED,515 NEEDS_INPUT,43 DISCOVERED,2 FAILED_RETRYABLE and1 historical
submission. There were0 admitted actions and0 new verified submissions. Queue
RUN109 retained SUPERVISED lifetime allowance1/hour1, score50, age14 days,
applicant limit1000 and unknown-count review. Other platforms remain disabled.

The latest browser consumer poll was12:22:12; the last search ran
12:21:46–12:22:07 and added19 identities. Backend worker heartbeat17:26:05 and
Telegram polling17:26:16 remained fresh. These heartbeats do not prove browser
availability, discovery after12:22, filling or submission.

The authenticated browser-profile endpoint independently reported the selected
approved binding as **PROFILE_OFFLINE**, with last extension heartbeat12:21:37
and its former bound window absent. A read-only Chrome window observation found
two different current window IDs, neither with an active Naukri tab. This does
not authorize using either window as the approved account or changing focus.
No tab/window activation, navigation, keyboard or clipboard action was performed.

The existing fixed-profile launcher deliberately refuses to open/reuse a profile
while another normal Chrome instance is running. Its behavior cannot be treated
as successful recovery. Owner reopening of the existing Profile8 on a non-Naukri
tab was requested once for this new closed-profile condition. No popup/button
was requested. Work depending on that connection remains pending; the queue was
not stopped or given additional write authority.

A retained-facts diagnostic at17:26:41 covered1,449 listings and found0 fully
eligible by the saved evidence. This is not a fresh provider check of every job.
Unknown counts and unsupported requirements were not silently allowed.

Three real database samples17:29:03–17:29:12 showed three service sessions with
no blocking PIDs or lock waiters. Observed open execution transactions were
0.310–1.363 seconds old; idle-in-transaction phases sampled were0.074–0.153
seconds old. No sampled long abandoned transaction was established. Connection
limits/timeouts were unchanged. Browser workload was unavailable during these
samples, so contention/performance under active discovery is not declared fixed.

| Acceptance | Result | Evidence / limit |
| --- | --- | --- |
| Durable discovery records since prior report | PASS |966 records previously;1,585 now; permanent queue/history retained |
| Current browser availability | BLOCKED |Selected approved profile is offline; former bound window absent |
| Discovery running now | FAIL |Last consumer poll12:22:12 despite fresh backend heartbeat |
| First new application / independent receipt | BLOCKED |0 admitted Apply;0 new verified submissions |
| Database contention under active browser load | NOT TESTED |No blockers in3 samples while browser unavailable |
| Recurring AUTOMATIC / restart / locked application | NOT TESTED |First-receipt prerequisite still unmet |

**0 automated tests were rerun.** No implementation change or fixture success is
presented as application acceptance. Raw profile state, database samples and
candidate diagnostics remain private. Sanitized observations are published here.
No Gmail send, other-platform activation, QTrino/uncertain replay, hosted Actions,
merge, installation, release deletion or cleanup occurred.

Next: after the requested Profile8 reopening, independently verify its fresh
extension heartbeat, approved binding, consumer polling and actual inactive-page
work. Then pursue the first eligible supported application and persistent receipt
under the existing single-application authorization. The once-asked unknown-count
decision remains pending; do not repeatedly ask or assume approval.
