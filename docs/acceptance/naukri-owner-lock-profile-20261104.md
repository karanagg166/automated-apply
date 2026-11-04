# Real request profiling and prepared owner-lock improvement

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`. **Naukri remains OPEN; no new receipt.**

Actual installed request timing shows remote database round trips materially
contribute to native latency. Two recent native samples took2.834/3.311 seconds,
with11/14 reads taking1.701/2.170 seconds and two write-classified statements taking
0.462/0.465 seconds. Pool acquisition was0.0003/0.0002 seconds. These are individual
samples, not a latency benchmark or proof that contention is resolved. The actual
Stop response previously took10.052 seconds. No timeout/connection limit changed.

The shared owner-lock helper unnecessarily issued INSERT ON CONFLICT before
SELECT FOR UPDATE even when the permanent singleton existed. Prepared
[implementationa4e52e2](https://github.com/karanagg166/automated-apply/commit/a4e52e28fd7e598a6ad4b1a240e6b35b864340cd)
locks the existing row directly. Only an absent singleton needs initialization.
For SKIP LOCKED, an unlocked MVCC key read distinguishes an existing skipped row
from absence, preserving cold initialization and transaction/savepoint fencing.
The normal existing-row path removes one database statement without weakening
the PostgreSQL row lock. This candidate is **not installed**; first-application
work continues on the already installed API48fafb7/extension1.3.29/c7869af.

Validation:

- Exact immutable API candidate:105 timing/background/reconsideration tests passed
  in13.39 seconds; requirements installation and `pip check` passed. The initial
  source run had104 passes and one fixture-expectation failure: the test rolled
  back its singleton creation while expecting the existing-row query count. The
  corrected fixture commits initialization before testing savepoint reacquisition;
  all six focused timing tests then passed0.67 seconds. Counts overlap.
- Actual disposable loopback PostgreSQL17: four concurrency groups passed0.253
  seconds. They exercise simultaneous cold initialization, one-SELECT hot locks,
  real waiting/SKIP LOCKED behavior and rollback-to-savepoint lock release followed
  by genuine reacquisition. One fictional value survives; no provider/production
  connection is made. The private test server was stopped and its data retained.
- Ruff E9/F/I and diff checks passed. No production rows, credentials, policies,
  installed files, API contracts, grants or schema were changed by these checks.

Reproduce only on a dedicated disposable loopback PostgreSQL database whose name
ends `_owner_lock_test`; provide its URL privately through
`PROFILE_TEST_DATABASE_URL`:

```sh
.venv/bin/python backend/scripts/verify_owner_lock_concurrency.py
.venv/bin/python -m pytest backend/tests/test_request_timing.py \
  backend/tests/test_naukri_background_queue.py backend/tests/test_queue_reconsideration.py -q
```

Supabase's real advisories returned no security lints and informational findings
for12 unindexed foreign keys and21 unused indexes. They do not establish the cause
of the current native/control latency, so no speculative index changes/removals
were made. See the official explanations for
[unindexed foreign keys](https://supabase.com/docs/guides/database/database-linter?lint=0001_unindexed_foreign_keys)
and [unused indexes](https://supabase.com/docs/guides/database/database-linter?lint=0005_unused_index).
Statement statistics also showed substantial historical owner-lock/read time;
those cumulative figures span prior releases and are not a current-release result.

The20 minimum-only rechecks have actually completed:16 posting-age exclusions,
two saved-fit exclusions, one changed page and one unknown-count hold. A subsequent
genuine fresher search completed without error and discovered seven new identities.
They still require ordinary full-listing eligibility checks. Freshness-control DOM
capture and the first new supported application/independent receipt remain pending.

| Acceptance | Result | Limit |
| --- | --- | --- |
| Actual request/pool/SQL timing and advisory inspection | PASS | Read-only evidence; no claimed complete performance fix |
| Exact prepared lock candidate | PASS |105 regressions, four real PostgreSQL concurrency groups |
| Production installation / measured live improvement | NOT TESTED | Deferred while real new jobs are being checked |
| Genuine minimum-only rechecks and subsequent discovery | PASS |20 actual decisions; seven new search identities |
| First new application / recurring AUTO / locked acceptance | NOT ACHIEVED | Zero new receipt; first-receipt gate remains |

Next: give eligible live application work priority; install the prepared API only
under STOP with an exact48fafb7 rollback and preserved account/profile/history,
then measure comparable native requests. Do not infer locked-Mac application
support from an awake heartbeat. Current observations are UNLOCKED. No Gmail send,
other-platform activation, hosted Actions, merge, release deletion or cleanup.
