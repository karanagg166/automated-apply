# Experience-guided listing inspection — Naukri OPEN

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`; exact installed API implementation
[`0e75386259a4bf7ee3fefac8f123eb188b4ab7b1`](https://github.com/karanagg166/automated-apply/commit/0e75386259a4bf7ee3fefac8f123eb188b4ab7b1).
Times below are UTC on November 2. No new submission is established by this report.

## Real bottleneck and change

At12:10:08 the live queue contained942 identities:524 SKIPPED,255 NEEDS_INPUT,
162 DISCOVERED and1 retained historical submission. No Apply had been admitted.
The observed discovery cycle added9 identities and completed without an error.
PostgreSQL had4 role sessions,0 lock waiters and0 idle transactions in that sample.

A subsequent durable backlog read found167 pending inspections.31 ordinary URL
slugs advertised a zero-year minimum;136 advertised at least one year. The18
previously recovered listings still occupied positions99–116 with zero attempts.
These are scheduling observations, not verified requirements or eligible jobs.

The API now checks all active/expired leases before sorting. Application and
receipt operations retain first priority. Listing inspections waiting at least
two hours come next in FIFO order. Among newer inspections, a URL experience
range containing the saved verified experience gets priority; unknown/malformed
hints and missing profile experience keep FIFO. Each lane is stable. Aging limits
bypass by incoming hints; it is not a guarantee against delays from browser
availability or application work.

URL hints never populate job facts, change matching or authorize a write. Every
listing still requires genuine full-page extraction and all configured checks.
No candidate data, filters, quotas, historical fences or submission permissions
were changed. The change adds one scalar profile query only when an inspection
claim is possible, with no new connection, pool, worker or schema.

## Targeted validation and exact installation

Source: **88 passed in10.56s**. Independent exact candidate: **88 passed in11.07s**.
Six added scenarios cover junior/senior experience hints, unknown profile facts,
reversed/unsupported ranges, aging and fresh-session claims; each checks no facts
or admissions are fabricated and another claim cannot cross the active lease.
The existing application-priority, expired-write, quota and identity/resume checks
also ran. These are isolated fixtures, not provider application evidence.
Ruff E9/F/I, dependency consistency and diff checks passed.

API-only installation: STOP108 at12:16:06 with949 retained records; startup
completed12:16:28; verification passed12:16:49. Backend readiness and frontend
login returned200, the worker was online, profile5 and approved account binding1
were unchanged, and profile-sync configuration/protected file hashes matched.
The15.726s Stop-plus-follow-up-snapshot duration is not pure Stop endpoint latency.
RUN109 restored the identical SUPERVISED lifetime allowance1/hour1.

Extension remains1.3.23/0c8b1d7 with the same ID. Actual frontend/native remain
414a260; execution/Telegram remain2ceea5e. The prior APIa02c352 runtime, exact
LaunchAgent and protected-hash inventory are retained. Rollback stops the queue,
unloads the new API, restores the prior plist/runtime and checks readiness and
state; it never restores an old database snapshot or replays an application.
No Chrome activation, keyboard, clipboard, profile save or extension reload was
needed. No rollback was required.

## Live observation

The unchanged queue resumed12:17:08. Five durable native claims were recorded
12:17:43–12:19:38; all finished by12:20:03. Their ordinary URL hints were0–1,
0–2,0–1,0–1 and0–4 years. Three were from the recovered cohort previously at
positions99–116. This establishes actual installed selection, not better total
throughput or eligibility from a URL.

The five outcomes were one each: `provider_context_changed`,
`current_profile_preferences_or_required_skills_exclude_job`,
`job_required_facts_unrecognized`, `posting_outside_age_limit`, and
`applicant_count_requires_review`. The genuinely inspected0–2 listing advertised
fewer than10 applicants but required unrelated regulatory/operational skills, so
it was correctly excluded. Zero Apply admissions occurred. Parser/context holds
remain unresolved; unknown applicant counts were not silently permitted.

A guarded read of an actually leased inactive listing at12:20:27 succeeded while
the Mac reported LOCKED. Its visible header said3+ weeks and100+ applicants and
its button led to the company site. That page does not qualify under the age
policy and does not explain the earlier unrecognized-page failure. No navigation,
click or owner focus change was performed by the observer.

At12:22:03 the live queue was RUNNING109 with955 identities:534 SKIPPED,
262 NEEDS_INPUT,158 DISCOVERED and1 historical receipt;0 admitted actions and
0 new verified submissions. PostgreSQL again showed4 sessions,0 lock waiters,
0 idle transactions. The20-record recovered cohort independently remained unique:
13 DISCOVERED,4 NEEDS_INPUT and3 SKIPPED. Five of its18 previously waiting records
had now been inspected. This is real progress through checks, not application
acceptance or proof of locked filling/submission.

| Requirement | Result | Evidence / remaining limitation |
| --- | --- | --- |
| Scheduling, restart and guards | PASS |88 isolated regressions in source and exact candidate |
| Exact API install / preservation | PASS |STOP108/RUN109,949 records, readiness200, binding/profile/policy hashes preserved |
| Actual prioritized inspections | PASS |5 native claims;3 recovered candidates reached inspection |
| First new supported application / receipt | BLOCKED |All5 failed or were held;0 admitted Apply |
| Parser/context compatibility | FAIL |2 page/context holds in this observed cohort; cause not yet established |
| End-to-end performance improvement | NOT TESTED |One extra scalar query; no claim of improved total throughput or Stop latency |
| Recurring AUTOMATIC / restart / locked application | NOT TESTED |First receipt prerequisite remains unmet; read readiness is insufficient |

Reproduction:

```sh
.venv/bin/python -m pytest backend/tests/test_application_queue.py backend/tests/test_naukri_background_queue.py -q
.venv/bin/ruff check --isolated --select E9,F,I backend/app/execution/application_queue.py backend/tests/test_application_queue.py
git diff --check
```

Score50,14-day age,1000-applicant threshold, all company stages and unknown-count
review remain configured. The once-asked lower-bound-count decision remains
pending. No QTrino/uncertain replay, other-platform activation, Gmail send, hosted
Actions, merge or cleanup. Next: finish eligible real applications and independent
receipts, then bounded recurring and actual restart/locked application acceptance.
