# Two genuine page holds diagnosed — Naukri OPEN

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`. Reviewed source was
`e8370026e696d8a3b163d4ea368777a5520790fe`; installed API remains
`0e75386259a4bf7ee3fefac8f123eb188b4ab7b1` and extension remains
`0c8b1d7eca0a1245ed02bebfeceb0b25c6457580` /1.3.23, stable ID unchanged.
Other component versions and rollback remain as recorded in the
[installation report](naukri-live-inspection-order-20261102.md).

## Actual diagnosis, November2 UTC

Two previously failed read-only listings each received one audited fresh
`inspect_job` request through the ordinary native queue. The owner fence,
RUN109, confirmed profile5, approved account binding1, permanent receipt fence,
empty admissions, absent packet/form and expected previous failure were checked
before each request. The prior record was preserved in a durable audit, with a
unique key preventing repeated diagnostic requests. Neither request authorized
Apply or altered policy. The first operator attempt hit the existing database
lock timeout before mutation and rolled back; the subsequent request committed.
Connection limits and timeouts were not increased.

At12:27:29, the specifically leased inactive internship page was captured. The
header's experience-shaped element actually contained **“6 months duration”**.
The page's structured experience supplied a one-month minimum, without a verified
maximum. Its internship presentation also differed from the full-time/permanent
employment metadata. Replaying the current parser against these captured DOM
sections reproduced `job_required_facts_unrecognized`. This is a captured-page
replay, not a fictional fixture or proof that the listing is eligible. Duration
must not be turned into required experience, and URL text cannot supply the
missing maximum. No fabricated range or employment value was inserted.

At12:33:00, the other specifically leased inactive tab had been redirected by
Naukri from the job URL to a search-results URL. The observer read that tab's URL;
it did not navigate, click, inspect another owner tab or bypass the document
check. The provider identity guard correctly returned `provider_context_changed`.
The redirect alone does not prove a specific expiration reason.

An independent database read confirmed both records returned to NEEDS_INPUT,
each with2 lifetime read attempts,0 admitted actions and no packet. Final failure
timestamps were12:27:35 and12:33:02. No submission or uncertain write was replayed.
These observations explain the two earlier holds; they do not establish a safe
parser change that would make either job eligible.

At12:30, a retained-facts diagnostic covered767 listings and found0 fully eligible.
Three otherwise passing records still had profile/skill exclusions; their actual
descriptions did not justify inventing missing competencies or ignoring target
roles. This diagnostic is not fresh provider verification for every listing.
At12:34:49, the live queue remained RUNNING109 with966 identities:544 SKIPPED,
269 NEEDS_INPUT,152 DISCOVERED and1 historical receipt. There were0 admitted Apply
and0 new verified submissions. PostgreSQL showed4 sessions,0 lock waiters and1
idle transaction; the earlier timeout means contention is not declared resolved.
The latest ordinary discovery cycle completed in15.593s, with0 new identities and
no recorded error. Its next scheduled time was12:38:16.

| Acceptance item | Result | Evidence / limit |
| --- | --- | --- |
| Diagnose actual missing-field hold | PASS |Specific fresh inactive page + captured-DOM parser replay |
| Diagnose actual changed-document hold | PASS |Specific owned inactive tab redirected to search results |
| Preserve history and action guards | PASS |Two unique audited read requests;0 admissions/packets; unchanged RUN109 policy |
| Support this internship's ambiguous metadata | BLOCKED |Duration is not experience; no verified maximum; no invented values |
| New eligible application / independent receipt | BLOCKED |0 new verified submissions |
| Recurring AUTOMATIC / restart / locked application | NOT TESTED |First receipt prerequisite remains unmet |

No production code or installed files changed in this follow-up. **0 automated
regression tests were rerun**; unchanged suites are not presented as new live
acceptance. One captured-page replay and two genuine provider reads are recorded
separately above. Raw DOM, audit records and logs remain private.

Reproduction uses the running worker's owned inactive tab, exact lease/revision
checks and current parser. Do not blindly repeat the diagnostic requests: their
durable audit keys already exist. Read the resulting history first. No owner
focus, keyboard or clipboard was used. No Gmail send, other-platform activation,
QTrino replay, hosted Actions, merge, installation or cleanup occurred.

Next: continue genuine scheduled discovery/inspection for a supported eligible
job under the existing single-application allowance. The once-asked unknown-count
policy decision remains pending; score50,14 days,1000 applicants and all other
checks remain in force. Do not substitute a heartbeat or a parser fixture for a
real first receipt or recurring application acceptance.
