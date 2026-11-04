# Accurate uncertain-outcome notices and guarded API update

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`.
Implementation/API installed:
[498dfe7](https://github.com/karanagg166/automated-apply/commit/498dfe7ddf2abbd358e4b8c36a68efd646175563).
**Naukri remains OPEN: one new Apply attempt, zero new verified receipts.**

After three bounded account/history checks fail to verify a sent receipt, the
queue now creates one dashboard notice and one opted-in Telegram outbox delivery.
It explicitly says the submission remains unconfirmed and Apply will not be
repeated. It does not create a receipt, refund a reservation, reset an admission
or restart the uncertain application. Stable notification/delivery keys and a
persisted marker prevent duplicate notices across polls and restarts. Notification
preferences and the existing Telegram delivery/recovery rules remain enforced.

Actual first-attempt evidence: the exact lost-tab job stayed SUBMISSION_UNKNOWN
with one Apply and no answer admission. Its notice was admitted through the new
service under the owner transaction; the already installed Telegram worker
changed its delivery from pending to sending to **sent at17:45:27 UTC**. There is
exactly one corresponding dashboard notice and one Telegram delivery after the
API update and resumed polls. This is a genuine uncertainty notice, not an
application success or employer acknowledgment.

The exact independent API candidate passed **53 targeted backend tests in17.32
seconds**, including three new notification cases, normal submission/receipt
fences, questionnaire recovery, Stop/Start reconciliation and timing locks.
The source notification/submission group passed23 tests in6.89 seconds; those
counts overlap. Requirements installation, `pip check`, Ruff E9/F/I and diff checks
passed. These fixtures make no real application or Telegram request; the live
notice evidence above is separate.

The update stopped the queue **atomically under the owner lock only after checking
that total Apply admissions remained one**. Another admitted attempt would have
refused maintenance without stopping/replacing anything. This prevents an update
from interrupting the newly authorized second attempt after its Apply grant.

Actual installation completed17:48:56 UTC:

| Component | Installed implementation / evidence |
| --- | --- |
| API | `498dfe7ddf2abbd358e4b8c36a68efd646175563`, full catalog readiness200 |
| Extension1.3.30,25 files | `dc47f9448cdf5dfc3ed81c80e360d70c35206264`, unchanged stable ID |
| Execution / Telegram / native | `b6b069051cdddc26683e67ef64646a90a2a7f753`, unchanged |
| Frontend | `ae66975691a75cb0a3a43010dcfdba26a5100128`, login200 and actual Start verified |
| Data / policy |2,057 records preserved under STOP133; profile5, binding1 and protected files unchanged |
| Resume of automation |Actual frontend RUNNING134; lifetime2/hour1, score50, any-skill,14days/1,000 applicants; other platforms OFF |
| Browser effect of this update |No browser operation, extension reload, tab/window change, keyboard or clipboard action |

Rollback retains the exact API581ec79 plist and catalog003-compatible release;
the extension/native/other-service/environment hashes are protected. No database
snapshot restore,003 narrowing, release deletion or cleanup occurred. The owner
explicitly approved one additional **different** eligible supervised attempt;
that approval does not permit repeating the lost-tab job or a third attempt.

A subsequent real ledger sample contained2,063 work records, **zero duplicated
requisitions**, one Apply admission, zero worker receipt records, one uncertainty
notice and a sent delivery. Discovery had completed another actual cycle with six
new identities and no source error. These identities still need full eligibility
checks. No second Apply was admitted in that sample. Unknown50+/100+ applicant
upper bounds remain held under the unchanged policy.

The current30-minute portal policy remains enabled for verified skills at
profile5, with PDF verification. A real comparison at17:18:02 returned
SYNC_VERIFIED. A later readiness check returned200 while the screen was UNLOCKED;
it does not prove locked filling/submission. The API581 interval before this
update recorded179/179 HTTP200 responses;130 authorized native requests had median
2.814s and maximum17.922s. Mixed requests and a finite sample do not establish that
all latency issues are solved. One read-only operator audit initially used an
incorrect Telegram table name; using the ORM table metadata corrected it without
DDL or an application-schema change.

The corrected registered DevTools MCP connection also passed a direct native
`list_pages` call showing its separate owned `about:blank` browser. See
[DevTools setup](../chrome-devtools-mcp.md). It uses the distinct testing-browser
bundle and does not attach to the owner's signed-in Chrome profile.

| Acceptance | Result | Limit |
| --- | --- | --- |
| Truthful uncertainty notice, durable dedup and actual Telegram send | PASS |Exactly one notice; no success receipt invented |
| Exact API tests/install/readiness/preservation/rollback | PASS |53 overlapping targeted fixtures;2,057 preserved records |
| Guard against maintenance after another Apply grant | PASS live guard |Observed one admission before STOP; no active new attempt interrupted |
| Repeated real discovery and durable dedup | PASS bounded sample |Six new identities; zero duplicate requisitions in2,063 records |
| First verified new application / recurring AUTOMATIC | NOT ACHIEVED |Second distinct eligible attempt remains authorized; first receipt absent |
| Real locked filling/submission and complete project acceptance | NOT TESTED / OPEN |No heartbeat or fixture substitute |

Next: leave discovery/application workers running, use the remaining supervised
allowance only for a different fully eligible job, complete its supported form and
verify two genuine persistent history documents before bounded AUTO. Keep the
original uncertain job quarantined. Other platforms, Gmail sending, hosted
Actions, merge and cleanup remain disabled/unused.
