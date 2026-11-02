# Application scheduling and recovered real discovery — Naukri OPEN

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`; exact API implementation/installation
[`a02c3520630422843ec37ee490cf901fad8deb68`](https://github.com/karanagg166/automated-apply/commit/a02c3520630422843ec37ee490cf901fad8deb68).
All times are UTC on November 2. Zero new submissions are verified.

## Behavior and validation

The shared browser queue previously considered older discovery inspections before
newer application checks and receipt reconciliation. It now checks and recovers
**every active/expired lease first**, then prioritizes existing application work
before `inspect_job`. Stable ordering preserves FIFO within each lane. Operation
selection, source checks, availability, exclusive browser leases and all write
admission/identity/resume/quota checks still apply. There are no additional SQL
queries, connections, workers, timeouts, schema changes or submission grants.

Source targeted tests: **82 passed in 9.10s**. Independent exact candidate:
**82 passed in 9.09s**. Four added cases cover three application/read operations
across a fresh session and refusal to cross an active discovery lease. Existing
expired-write, quota and identity/resume guards remain in the targeted suites.
These are isolated regressions; no real application priority handoff or receipt
is claimed from them. Ruff E9/F/I, dependency consistency and diff checks passed.
Unchanged browser/frontend suites were not repeated.

## Real recovered discovery

The genuine owned inactive frontend-fresher document captured at11:13:16 before
Date sorting contained20 candidate URLs. The earlier Date-sort behavior omitted
that set from final discovery; its correction is documented in the
[previous live report](naukri-focused-fresher-discovery-20261102.md).

Under the existing owner authorization, approved binding1 and confirmed profile5,
those actual observed URLs were passed through the normal bounded deduplicating
`enqueue_batch` path, including permanent history/uncertainty checks. No candidate
was labeled eligible from a card or URL. A capture-checksum audit records the
operation and prevents an accidental duplicate recovery.

The initial private audit key exceeded the existing50-character column limit
(SQLSTATE22001), so its entire transaction rolled back. The key was shortened
within that limit, with the complete checksum retained and checked in its value.
No schema was widened and no partial enqueue was assumed successful. The corrected
transaction committed at11:32:01: **18 new identities**,2 already retained.
An independent later read verified exactly20 unique records:18 DISCOVERED,
1 NEEDS_INPUT (`experience_requirement_evidence_conflict`),1 SKIPPED
(`posting_outside_age_limit`),0 admitted actions and0 new confirmed submissions.
The18 new records still require fresh full-listing inspection and eligibility.

## Exact installed state and rollback

The API-only replacement used STOP106 with898 records. Startup completed11:34:53;
verification passed11:35:08: ready200, frontend login200, worker online, profile5,
approved binding1, skills policy and protected component/environment files intact.
Queue resumed **RUNNING107**, identical SUPERVISED lifetime allowance1/hour1.
The7.689s control-plus-snapshot duration is not an isolated Stop latency measure.

Extension remains1.3.23/0c8b1d7, stable ID unchanged. Actual frontend/native remain
414a260; execution/Telegram remain2ceea5e. Exact previous API8473bdc runtime,
LaunchAgent bytes, protected hashes and rollback inventory remain retained. No
rollback was required. Rollback unloads the new API under STOP, restores its exact
previous plist/runtime and verifies readiness/data/account/policy; it does not
restore old database data or replay applications. No Chrome activation, keyboard,
clipboard, extension replacement, credentials edit or release deletion occurred.

| Acceptance | Result | Evidence / limitation |
| --- | --- | --- |
| Queue priority and lease/admission regressions | PASS |82 targeted tests in source and exact candidate; overlapping counts |
| Real missing candidate recovery and dedup | PASS |18 added;20 unique independently verified; full inspection pending |
| Installed API readiness and protected state | PASS |898 records; STOP106/RUN107; exact rollback retained |
| Real application-priority handoff | NOT TESTED |No eligible application yet reached this path |
| First new genuine application/receipt | BLOCKED |0 new verified submissions; no Apply admitted |
| Fully eligible retained-facts diagnostic | No eligible result |717 fact records of898 identities at11:36:06; diagnostic is not a fresh provider read |
| Recurring AUTOMATIC / locked application / restart recovery | OPEN |First receipt and remaining critical checks still required |

Reproduction:

```sh
.venv/bin/python -m pytest backend/tests/test_application_queue.py backend/tests/test_naukri_background_queue.py -q
.venv/bin/ruff check --isolated --select E9,F,I backend/app/execution/application_queue.py backend/tests/test_application_queue.py
git diff --check
```

Next: inspect suitable candidates in the real backlog, complete the first eligible
supported application and verify its independent persistent receipt. The once-asked
unknown-count decision remains pending. Score50,14-day age,1000-applicant threshold,
all company stages and remaining filters are retained. No QTrino/uncertain replay,
other-platform activation, Gmail send, hosted Actions or merge.
