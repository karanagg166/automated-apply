# Installed bounded dashboard reads — Naukri OPEN

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`; implementation
[`b3abc9e85b90866e64a6ff8026751e0b3c98f7f8`](https://github.com/karanagg166/automated-apply/commit/b3abc9e85b90866e64a6ff8026751e0b3c98f7f8).
This improves current database usage, not real application acceptance.

Actual installed timings showed requests spending10–24 seconds waiting for the
single API pool connection, even when the queries themselves took far less time.
A separate PostgreSQL observation found four sessions, two briefly idle in a
transaction, no blocking PIDs and no lock waiters. These snapshots do not prove
all causes of contention. Pool size, connection caps and timeouts were unchanged.

Profile status now reads its candidate confirmation, policy, current work and
latest audit reference without selecting resume resources or making separate
serial preference lookups. Queue status aggregates filtered totals with global
stage counts, batches current preferences and preserves exact pagination, search,
location, score filters, quotas and history. No queue/admission/write guard changes.

## Measurements

Read-only probes used one NullPool observer, with database connection setup outside
the measured service calls. Retained674 identities were present in both samples.

| Service | Before SQL statements / time | After source SQL statements / time |
| --- | --- | --- |
| Profile status | 6 /1.565s | 2 /0.808s |
| Queue listing, limit1 | 8 /1.812s | 5 /1.584s |

These are sequential real-database samples, not a controlled throughput benchmark.
The SQL statement reduction is verified; exact latency improvement is not a
universal claim. Installed HTTP checks at09:46:07UTC returned both200:
profile2.601s, queue1.689s. Request-ID-correlated API instrumentation confirmed
2 and5 SQL reads respectively. Profile connection occupancy0.663s, queue1.350s;
profile pool acquisition still1.602s. Performance remains OPEN.

## Exact deployment and validation

API-only candidate built in its own environment. **66 targeted tests passed7.25s**
on the exact candidate, including filtered totals vs global counts, pagination,
no resume query for status, existing queue and profile-save/reload guards.
The same66 source tests passed7.09s; do not sum overlapping runs. Ruff and diff
checks passed. No hosted Actions were run.

Installation used STOP96 with674 records. Full startup database audit completed;
ready200, frontend login200, worker online, profile5, approved account binding1,
current skills-only profile policy and all protected component files were verified.
API installed at09:45:25UTC. Queue resumed RUNNING97 under unchanged SUPERVISED
cap1/hour1, all stages, score50, age14days, threshold1000 and unknown-count review.
Previous API plist/runtime and exact rollback inventory remain retained. No
rollback was required and no data/history/release was deleted.

| Check | Result |
| --- | --- |
| Exact candidate tests, relevant static checks/build | PASS |
| Real installed API and status query counts | PASS |
| Protected profile/account/history/policy/other components | PASS |
| Genuine skills Save from earlier acceptance | PASS, preserved `SYNC_VERIFIED` |
| Real new application/independent receipt | BLOCKED, zero new verified receipts |
| Recurring AUTOMATIC | NOT ENABLED / NOT ACCEPTED |
| Full responsiveness / Stop / locked/restart acceptance | OPEN / NOT ACCEPTED |

Only API is now b3abc9e. Actual frontend launcher and native host remain
414a260a01b94609bc71eddd2bb037fbb274c3b9, extension1.3.20 remains
23c9fdbb374e40920b6a22df0c59b6d199d08039 with stable ID, and execution/Telegram
remain2ceea5e4ab5662e041a58c6ec7d4aa73e86d51f7. Other platforms and Gmail sending
remain disabled. No Chrome focus operation was needed for this API replacement.

Reproduce the relevant regressions:

```sh
.venv/bin/python -m pytest backend/tests/test_queue_dashboard_reads.py backend/tests/test_profile_skills.py backend/tests/test_naukri_profile_sync.py backend/tests/test_application_queue.py -q
```

Next: continue fresh eligible discovery and the first supported genuine application,
independently verify its receipt, then bounded recurrence and actual restart/locked
checks. Preserve the once-asked applicant-bound decision and missing facts;
no exception or personal information is invented to manufacture acceptance.
