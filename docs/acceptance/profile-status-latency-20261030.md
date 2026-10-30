# Remaining profile-status latency: measured correction for review

Branch `fix/live-prepare-discovery-20261030`, base `main`; [PR 48](https://github.com/karanagg166/automated-apply/pull/48).
Installed and live-tested source:
[`5ca05d844fbaa7ca0ada093aa37556c831c89edf`](https://github.com/karanagg166/automated-apply/commit/5ca05d844fbaa7ca0ada093aa37556c831c89edf).
**New exact candidate, not installed:**
[`79ce5f6b514279e6d9022d85b659ad77fb31bd89`](https://github.com/karanagg166/automated-apply/commit/79ce5f6b514279e6d9022d85b659ad77fb31bd89).

## Actual live findings

The approved installed source completed three consecutive real read-only
Open → Prepare cycles in Profile 8. One followed both a graceful backend/worker
restart and an unexpected worker crash. Stop cancelled a queued Prepare and
restoring RUNNING did not resume paused tasks or replay terminal commands. All
three plans were accurately labeled read-only `NEEDS_INPUT`, with zero fields,
actions or approved fields. Four unrelated tabs retained their IDs/URL hashes.
A creation-time DB audit found zero new packets for the same job/candidate
across the three-cycle interval. The task is paused; no employer action occurred.

The two completed HTTP windows recorded **180 readiness samples: 177 HTTP 200,
3 ConnectError during the planned API restart, zero HTTP 503**. The remaining
failures were **three profile-status ReadTimeouts at 12s** and **two health
ReadErrors**. Server-side profile logs also showed requests exceeding 12s
(maximum 18.1437s in the inspected checkpoint). These failures are retained;
successful readiness does not erase business-request latency.

The owner explicitly deferred the locked-screen test. No locked DOM PASS or
complete 24/7 automation is claimed. See the [installed acceptance](readiness-isolation-live-20261030.md)
and [sanitized full metrics](readiness-live-final-metrics-20261030.json).

## Profile-status change and measured comparison

The current route uses five sequential remote reads for selection, profiles,
tasks, commands and receipts while occupying the sole business pool slot. The
candidate combines the same disjoint predicates with `UNION ALL` into one SQL
statement and one consistent database snapshot. It preserves response shape,
secret redaction and the existing command/receipt bounds. If expiry or offline
invalidation is needed, it still acquires the owner fence and obtains a new
snapshot before mutating; a concurrent cancellation cannot be overwritten by an
earlier status read. General pools, role limits and command deadlines do not change.

An actual remote PostgreSQL comparison ran the installed and candidate routines
sequentially through **one temporary operator connection**, with **five calls
each**, inside enforced `SET TRANSACTION READ ONLY` transactions. No API service
was started or replaced for this measurement. Stable public outputs matched,
excluding naturally changing heartbeat timestamps. No profile/command contents
were retained in the published comparison.

| Direct read-only routine | Read operations/call | Mean seconds | Maximum seconds |
| --- | --- | --- | --- |
| Installed five-read implementation | 5 | 0.8554 | 1.3599 |
| Candidate batched implementation | 1 | 0.1819 | 0.3031 |

This measures actual remote read cost, **not installed HTTP queue latency**.
It does not establish that the candidate eliminates every HTTP timeout under
native workload. That requires a newly approved installation and repetition of
the same workload. Connection checkout/setup/rollback are outside the timed
routine in both cases.

A separate fictional SQLite experiment injected 200ms per read: five calls
averaged 1.0136s before versus 0.2036s after. It checked equal sanitized output.
This is explicitly simulated round-trip cost, not an additional live benchmark.

## Health transport diagnosis and monitor correction

The original monitor polled every five seconds while its HTTPX pool and the
installed Uvicorn server both used a five-second idle keep-alive boundary.
Those defaults are documented by [HTTPX](https://www.python-httpx.org/advanced/resource-limits/)
and [Uvicorn](https://uvicorn.dev/settings/), and the installed Uvicorn default
was checked locally as 5 seconds; the launcher does not override it.

A paired live loopback test issued **30 health requests per client**, without
retries, while leaving server settings unchanged:

| Client idle expiry | Actual result | Maximum observed duration |
| --- | --- | --- |
| Default 5s | 26 HTTP 200; **4 ReadError** | 0.0218s |
| Conservative 2s | **30/30 HTTP 200** | 0.0092s |

All four traced failures reused an existing TCP connection and failed while
receiving response headers. The sanitized exception chain ended in
`ConnectionResetError`, **errno 54**, via `BrokenResourceError` and `ReadError`.
The independent 2s client succeeded at the same sample times. There was no API
restart in this paired experiment. This supports an idle-close/reuse race in
the polling transport; it is not evidence of a database outage. The older
untraced health errors cannot individually be assigned that cause with certainty.

The candidate monitor retires idle connections at 2s, below the observed server
boundary. It changes no server timeout, performs no hidden retry, and retains
any first-attempt failure. It still uses the 12s observer request deadline, so
the profile latency correction must actually pass that deadline after installation.

## Validation and status matrix

| Check | Status | Evidence / scope |
| --- | --- | --- |
| Full focused backend regression suite | PASS — **346 tests, 36.01s** | Isolated fictional fixtures and actual local process tests |
| Disposable PostgreSQL regression suite | PASS — **7 tests, 2.56s** | Actual local PostgreSQL 14.24, including contention, cancellation, budget, outage and recovery |
| Snapshot/profile focused subset | PASS — 37 tests, 8.23s | Included in the full count; not additional coverage |
| Read-only remote routine comparison | PASS for measured read cost/output | Five calls each; one operator slot; no installed source replacement |
| One-statement query budget and credential redaction | PASS | Regression checks one SELECT statement, unchanged selection/receipt/command output and no lease/hash leakage |
| Cancellation/expiry/unknown-outcome fences | PASS in existing regressions | Locked re-read retained; old terminal commands and ambiguous commands never reopened |
| Paired health transport diagnosis | PASS for reproduction | Four traced reused-socket resets at 5s; 30/30 healthy at 2s |
| Ruff E9/F/I and diff checks | PASS | Three changed Python files |
| New installed HTTP performance | NOT TESTED | Exact-SHA review and installation approval still required |
| Locked-screen native cycle | NOT TESTED | Owner requested pending; no repeated lock request |
| Real fill/submission/receipt | BLOCKED / NOT TESTED | Separate field/platform authorization and supported receipt mechanism still required |

No API contract, frontend asset, extension permission, schema, profile fact,
match threshold, mailbox scope or sending/submission gate changes in this
candidate. Installed `5ca05d8…` remains intact, with all rollback releases preserved.
No hosted CI, merge, cleanup or new background source workload was started.

## Reproduction and next action

```sh
.venv/bin/python -m pytest backend/tests/test_reliability.py \
  backend/tests/test_chrome_profiles.py -q
# Use the full regression command in reliability.md for the 346-test run.
# Requires disposable localhost candidate_profile_test, never the real DB.
.venv/bin/python -m pytest backend/tests/test_reliability_postgres.py -q -s
.venv/bin/python -m ruff check --isolated --select E9,F,I \
  backend/app/browser/chrome_profiles.py backend/scripts/measure_reliability.py \
  backend/tests/test_reliability.py
git diff --check
```

The sanitized measurements are in
[readiness-live-final-metrics-20261030.json](readiness-live-final-metrics-20261030.json).
Private logs are `profile-snapshot-regressions.log` and
`profile-snapshot-postgres.log` under `reliability-20261030`; direct routine,
simulated round-trip and paired health receipts remain under
`reliability-probe-upgrade-20261030T105557Z`. No raw private log, Gmail content,
candidate PII, tab URL, browser secret or screenshot is published.

After review, obtain owner approval of exact candidate `79ce5f6…` before replacing
production. Repeat HTTP-only monitoring alongside real native work, then publish
actual route latency and connection/resource results. Retain the owner-deferred
locked-screen status and all prior failures. Resolve this remaining latency
before adding continuous discovery workload.
