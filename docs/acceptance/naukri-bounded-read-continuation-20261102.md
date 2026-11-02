# Bounded ordinary-read continuation — Naukri OPEN

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`. Exact installed extension implementation:
[`ec1a5b729edae259c5bc2db3992397c2f85d2f02`](https://github.com/karanagg166/automated-apply/commit/ec1a5b729edae259c5bc2db3992397c2f85d2f02),
version1.3.22. Times are UTC on November2. There are **zero new verified
submissions**. This report does not accept recurring automatic applications.

## Change and safeguards

After a confirmed ordinary listing or search read finishes, the consumer may
continue sequentially instead of always waiting for another wake. A wake starts
at most three rounds and starts no additional round after30seconds. This is a
scheduling window, not a longer native timeout or permission to parallelize work.
Each round repeats owner-activity, profile, permission, policy and lease checks.
The prior owned tab must be closed and its local in-flight record cleared first.

Uncertain finishes, challenges, forms and application execution yield. Stop or
owner activity prevents the next lease. Discovery remains at300seconds; profile
comparison remains at1800seconds. Database connections, provider controls,
submission quotas and filters are unchanged.

## Exact installation and real observations

The queue was STOPPED100 before replacement with769 retained identities.
All24 installed extension files match the exact candidate, retaining ID
`gdjbmkffcpicbpiikcohlmokkmcpipgp`, key and permissions. Readiness and frontend
returned200; a new native reconnect was observed. Profile5, approved binding1,
skills policy26, credentials, component files and history were preserved.
Front-window/active-tab snapshots matched. Installation completed10:38:17.
Prior1.3.21 bytes, protected-file hashes and exact rollback inventory remain
retained. No rollback was required. Queue resumed RUNNING101 with the same
SUPERVISED lifetime cap1/hour1; AUTOMATIC was not enabled.

Actual component versions remain separate:

| Component | Installed SHA |
| --- | --- |
| API | b3abc9e85b90866e64a6ff8026751e0b3c98f7f8 |
| Actual frontend launcher/runtime and native host | 414a260a01b94609bc71eddd2bb037fbb274c3b9 |
| Execution and Telegram | 2ceea5e4ab5662e041a58c6ec7d4aa73e86d51f7 |
| Extension1.3.22 | ec1a5b729edae259c5bc2db3992397c2f85d2f02 |

The next real discovery ran10:39:37–10:39:55 and added14 identities without an
error. Four fresh listing observations completed at10:40:22,10:40:55,10:41:18
and10:41:53. All four were rejected for excessive required experience. Completion
gaps were32.821,23.090 and35.049seconds. **A throughput improvement is not proven**
by these observations; native/backend overhead and scheduling still need work.
Locked-state samples accompany actual provider work, not just a heartbeat.

At10:42:16 there were783 identities:118 awaiting inspection,218 needing input
or evidence,446 skipped and1 historical application. At10:49:32 a fresh snapshot
had791:113 awaiting inspection,225 held,452 skipped and1 historical application.
Search10:45:11–10:45:28 had added8. Both snapshots reported LOCKED. No Apply was
admitted, no new receipt was recorded and the historical application was not
replayed. These counts describe discovery/history, not completed applications.
The later database sample had4 role sessions and0 lock waiters; it is not proof
that contention is solved. The combined Stop-and-snapshot operation took16.849s;
it was not an isolated Stop latency measurement.

## Validation

| Check | Result | Evidence and limits |
| --- | --- | --- |
| Targeted Node regressions | PASS | 87 tests, source1.023s; exact candidate approximately1.1s |
| Isolated Chromium background cases | PASS | 17 cases, source30.749s; candidate31.169s;0 external/provider requests or choosers |
| Candidate build and formatting | PASS | 24 files; seven loaded modules and three test drivers byte-compared before using canonical tester dependencies |
| Installed readiness, identity/policy/history and focus preservation | PASS | Exact files/reconnect/200s; unchanged protected components and SUP1 |
| Real discovery and rejected listing processing | PASS, bounded | Two further search cycles and fresh listing exclusions above |
| Real throughput improvement | NOT PROVEN | Completion gaps above; no controlled comparison |
| Fast Stop, full contention/native-timeout resolution | OPEN | No new claim of acceptance |
| New real submission and independent persistent receipt | BLOCKED |0 new submissions; no admitted Apply |
| Recurring AUTO, restart and locked application completion | NOT TESTED / OPEN | Requires first receipt and critical checks |

The browser cases establish three sequential reads then continuation on a later
wake, yielding on a challenge, and preserving the owner tab. Unit regressions
also cover lost finish, scheduling-window expiry and checks before another lease.
An initial test-counter error was corrected; no production guard was weakened.
Counts overlap prior runs. Unchanged backend/frontend suites were not repeated.

Reproduction:

```sh
pnpm -C extension exec node --test tests/naukri-observation.test.mjs tests/naukri-queue.test.mjs
pnpm -C extension exec node tests/naukri-queue.browser.mjs
pnpm -C extension build
```

[Prior genuine locked reads and current description parsing](naukri-locked-reads-and-real-details-20261102.md)
remain separate evidence. Account binding and actual saved-PDF byte verification
are retained. All company stages, score50, posting age14days, applicant threshold
1000 and unknown-count review remain enforced. The once-asked lower-bound-count
decision is still pending; no exception or upper bound has been invented.

Next: improve suitable fresh discovery and complete the first eligible supported
application with independent receipt, then bounded recurrence and real
restart/locked application acceptance. Other platforms remain OFF, Gmail remains
read/draft-only, all rollback files remain retained, and no hosted Actions or
merge was requested or run.
