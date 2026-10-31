# Genuine Naukri discovery beyond the first 20 links

Branch `fix/live-prepare-discovery-20261030` → `main`,
[PR #48](https://github.com/karanagg166/automated-apply/pull/48).
API implementation [99466234ab33cef09fd7389af440f8982066d0ed](https://github.com/karanagg166/automated-apply/commit/99466234ab33cef09fd7389af440f8982066d0ed).
Extension correction [f856d7322b83bdde0c9c48f079e42b40618319f1](https://github.com/karanagg166/automated-apply/commit/f856d7322b83bdde0c9c48f079e42b40618319f1).
Local date November 1; all times below are October 31, 2026 **UTC**.
[Sanitized measurements](naukri-bounded-discovery-pages-20261101-metrics.json).

**Naukri remains OPEN. The corrected page-2 cycle discovered 15 new durable jobs
while the Mac was locked. Zero new applications or receipts are claimed.**
The [score-50 installed acceptance](naukri-score50-live-20261101.md) records nine
actual browser rechecks: seven matching exclusions, two applicant-count holds,
and zero new Apply admissions/receipts. All other configured filters remain.

## Observed problem and bounded change

Discovery repeatedly visited the first search page and read only its first
20 posting links. Recent completed cycles returned zero newly distinct URLs.
At **22:39:13**, a read-only inspection of the exact leased, inactive search tab
observed the genuine Date-sorted provider pagination:

- `nav[aria-label="Pagination"]`;
- one selected anchor with `aria-current="page"`, page 1;
- ordinary same-origin numbered links to `/<role>-jobs-2`, `...-3`, through `...-10`;
- a visible enabled **Next** anchor to page 2, with no new-window target.

Only sanitized structure is public; raw DOM, private bindings and window/tab IDs
remain private. Inspection executed no click, field write, upload or Apply.

The existing API scheduler now uses the observed ordinary path pattern to read
page 2, then at most page 3, **only after a completed cycle returned zero newly
distinct URLs**. A cycle finding new jobs rotates to the next saved role. Page 3
always rotates roles. Failed/stopped/incomplete reads reset the sweep. The stored
previous URL must still match the same currently configured role before advancing;
changing roles cannot reuse a cursor for an unrelated search.

The initial navigation uses the observed ordinary path pattern. **Actual failure
at 22:50:21–22:50:37** then exposed a missing behavior: selecting Date on page 2
resets the SPA to page 1. The installed 1.3.11 guard reported
`provider_context_changed`, the worker admitted zero candidate URLs, and no
application action occurred. The private read-only probe separately observed
page 2 selected with 20 links and Recommended sorting before the reset. The
failure was retained, not called successful pagination.

Extension **1.3.12** now permits that explicit Date-triggered transition to the
same role's page 1, then clicks only the single visible enabled **Next** anchor
in its exact pagination navigation. Every destination must be same-origin,
the next expected role/page, without credentials, query/hash, alternate target or
disabled state. It confirms the provider's selected page, final exact pathname,
Date label and replaced listing links. Unchanged cards, ambiguous controls,
challenge/rate-limit pages, unexpected redirects or owner adoption refuse work.
The existing 40-attempt/200-ms sorting bound was not increased. No Apply or form
control is selected by this path.

This does not call private provider APIs, invent query parameters, remove filters
or use browser cookies outside the existing connection.
One page per existing **300-second** interval and **20 candidate links** per report
remain; PostgreSQL deduplication, backpressure, history fences and all application
admission checks still apply. No pagination number is a posting date or eligibility
fact. Page 2's actual job pages must still be independently inspected and matched.

## Exact installed components and rollback

| Component | Installed source |
| --- | --- |
| API | `99466234ab33cef09fd7389af440f8982066d0ed` |
| Execution worker, frontend, Telegram | `f90cfe7ea3dfc7ca20efe1a1995b3da26707a028` |
| Same-ID extension 1.3.12, exact 22/22 files | `f856d7322b83bdde0c9c48f079e42b40618319f1` |
| Native host, unchanged | `fc91a219d5b824f934bb733eaf20166661e1f08b` |

Under the owner's standing autonomous local-update authority in
[AGENTS.md](../../AGENTS.md), only the API process/reference was replaced.
At **22:43:59**, queue **STOPPED revision 29**, **297 records**, approved binding
revision **1**, zero leased/executing/unknown records or admitted application actions.
Stop plus paginated inspection took **21.535 s**; this is not standalone Stop latency.
The previous API exited **22:44:00** before reference replacement. At **22:44:27**
API/database readiness and frontend login returned **200**; the account, record
count, policy and protected extension/native/service/credential references matched.
The queue resumed **22:44:31**, revision **30**, same minimum **50**, SUPERVISED
cap **1**, hourly cap **1**. No recurring AUTOMATIC activation occurred.

The exact previous `f90cfe7` API definition, protected file hashes, 22-file
extension inventory and previous immutable release are retained in the private
installation plan. Rollback: Stop the queue, restore the previous API definition,
bootstrap and recheck readiness/account/policy/data. The previous API accepts 50;
no threshold or database rollback is needed. Never restore a database snapshot over
new outcomes. Rollback was prepared, not exercised; this cutover succeeded.

Extension-only correction: **22:55:17**, queue STOPPED revision **31**, same **297
records** and account binding. The exact **22-file** same-ID extension loaded at
**22:55:20** through its own inactive setup tab; integrity passed **22:55:32**.
All API/worker/frontend/Telegram/native/private references remained unchanged.
The original exact 1.3.11 bytes/source archive remain in the separate rollback
inventory. Native connection recovered without an owner popup/button. At
**22:55:44**, queue resumed **RUNNING revision 32**, with the Mac **LOCKED** and
the exact same score-50/SUPERVISED-1/hour-1 policy. No OS unlock or focus operation
was used. Rollback is a stopped restore of the 22 preserved 1.3.11 files plus an
ordinary Reload through the own inactive setup tab, never a record reset.

## Targeted checks versus genuine acceptance

Backend background-queue regressions: **40 passed in 4.59 s**, including five new
pagination/rotation/interval cases. The pinned candidate repeated the **same 40
in 3.92 s**, not 80 distinct tests. New test setup initially invalidated the
fixture profile confirmation, then used custom role preferences instead; a separate
millisecond-sensitive interval assertion was corrected to compare scheduler stamps.
These were test failures before installation, not production acceptance failures.
The five new cursor cases were then strengthened to cross fresh database sessions:
**5 passed in 0.77 s**, overlapping the same 40 cases. Installed API source remains
9946623; that follow-up changed only tests.

Actual isolated Chromium with the shipped unchanged extension: **11 passed in
62.613 s**, including the new page-2 background search. Provider DNS routing was
blocked: **0 live provider requests**, **0 unexpected requests**, **0 chooser
events**, **9 intercepted fixture requests**. Owner-tab preservation in this
isolated browser is fixture evidence, distinct from the real Mac. Ruff, whitespace,
pinned Python dependency checks passed. No API schema, frontend runtime or extension
runtime changed; their broad unchanged suites/builds were not repeated. No hosted
Actions were run.

That initial Chromium case did not model Date's page reset; its fixture success
did not establish genuine page-2 acceptance. The corrected fixture explicitly
models the observed page-2 → Date → page-1 → Next → page-2 transition. With
1.3.12, **41 focused Node cases passed in 1.158 s** and **11 isolated Chromium
cases passed in 63.959 s**, again **0 provider/unexpected/chooser requests** and
9 intercepted fixture requests. Both builds preserve the exact stable ID.
Only extension runtime changed in this correction; no new frontend build or
unchanged backend suite was repeated.

```sh
.venv/bin/python -m pytest backend/tests/test_naukri_background_queue.py -q
pnpm -C extension exec node tests/naukri-queue.browser.mjs
pnpm -C extension exec node --test tests/naukri-date-sort.test.mjs tests/naukri-queue.test.mjs
```

The first actual installed page-one cycle began **22:44:51**, and read-only samples
at **22:45:06** and **22:45:11** observed Date selected with 20 listing links.
The corrected **1.3.12** page-2 cycle began **23:00:57.380417**, after the unchanged
300-second interval. At **23:01:06**, the exact inactive page 2 showed Recommended;
at **23:01:11.796404** it showed **Date**, provider-selected page **2**, **20 listing
links**, and **LOCKED before and after** each observation. The work completed
**23:01:18.252185**, **20.872 s** after starting, with **15 newly distinct durable
jobs**, source admission count **284 → 299**, **no source error**. Total queue
records increased **297 → 312**, with the same historical receipt retained.

At **23:01:24**, all 15 new messages were DISCOVERED, awaiting their own genuine
job-page inspection, age/applicant filters, matching and packet prerequisites.
Neither source links nor successful Date sorting are job eligibility or receipts.
There were **0 admitted application actions and 0 new receipts**. Existing history,
uncertain-action, configured filter and first-attempt fences remain in effect.
Uninspected new jobs are not declared eligible or ineligible.

At **23:01:20**, front-window and every active-tab ID again matched the separate
**22:56:41** snapshot exactly. At **23:01:27**, API/database readiness **200 in
2.657 s**, frontend login **200**, native selected profile **CONNECTED**, queue
RUNNING **revision 32**, minimum **50**, **312 records**. At **23:01:28**, protected
service/native/private references and all **22 exact 1.3.12 files** matched their
installation inventory.

Actual new-job inspection is progressing while locked: at **23:04:12**, the
15-message cohort had **2 SKIPPED** for posting age, **3 NEEDS_INPUT** (one
posting-age precision hold, two conflicting experience observations), and **10
DISCOVERED** still awaiting inspection. This proves actual provider fact/filter
processing for those five messages, not a completed matching pass for all 15.
Zero application actions or new receipts had been recorded. The operator monitor
initially used a finish-time cutoff later than the enqueue transaction's timestamps;
its read-only cohort assertion failed, then was corrected to the cycle start and
froze the exact 15 IDs. No queue mutation or retry came from that monitor correction.

**Complete genuine 15-job cohort at 23:11:04.897105, screen LOCKED:**
**9 SKIPPED** for the saved posting-age limit; **6 NEEDS_INPUT** comprising three
posting-age precision holds and three conflicting experience observations.
**0 DISCOVERED remaining, 0 admitted application actions, 0 new receipts.**
Every newly queued job received its real individual listing inspection. None
passed those prerequisite gates, so no matching/packet, form, Apply or receipt
success is claimed for them. No hold was treated as an approved fact.

The final completion sample was **587.473 s after the enqueue transaction's
timestamp**, including native polling, browser loads, an interleaved source cycle
and 25-second monitoring intervals. This is an end-to-end cohort observation,
not pure per-job latency or a controlled throughput comparison. Discovery remains
RUNNING under the unchanged interval and cap-one policy; additional jobs must
independently meet the same saved conditions.

## Actual locked-Mac readiness and browser operation

The owner locked the Mac independently; the agent did not change its lock state.
At **22:53:22**, lock telemetry was **LOCKED before and after** a genuine
API/database `/ready` response: **200 in 2.685 s**. Three further serial current
samples, also LOCKED on both sides of each request:

| Time | HTTP | Seconds |
| --- | --- | --- |
| 22:56:14 | 200 | 2.262 |
| 22:56:16 | 200 | 2.146 |
| 22:56:18 | 200 | 2.158 |

These current results differ from the older release's three observed 503s, but
the release/state/time differ; this is not a controlled performance comparison
or proof that pagination caused a readiness improvement. No connection limit
or timeout was raised.

There is actual browser evidence beyond a heartbeat: **22:56:05**, the exact
own inactive search page showed **Recommended**, page 1, 20 job links; at
**22:56:11** and **22:56:16**, the same bound journey showed **Date**, page 1,
20 links. Every sample recorded **LOCKED before and after** the read. The shipped
background worker performed the ordinary Date selection; the observer only read
the resulting DOM. This establishes a bounded locked-screen search/sort operation,
not locked application filling or submission.

A separate read-only snapshot **22:56:41** matched the **22:46:35** Chrome
front-window and all active-tab IDs exactly, spanning maintenance/reload and the
observed source work. IDs remain private. This is a bounded before/after result,
not continuous observation of every instant or a claim about personal tab content.

## Actual database profile

One serial operator connection was used; the DOM monitor was paused for this
read-only profile so two operator observers would not compete for the capped role.
At **22:58:41**, the role had **4 connections including the observer**, limit **5**:
two idle, the observer active, one idle-in-transaction for **0.146 s**. All observed
locks were granted; no blocked lock or exhausted-role event was present in this
sample. This does not disprove intermittent contention during busier periods.

`EXPLAIN (ANALYZE, BUFFERS)` of the actual nonterminal queue read returned **72
rows**, **0.530 ms planning**, **5.307 ms execution**, **1,154 shared-buffer hits**,
**0 shared reads**. The same client call took **0.338 s**; a fresh connection took
**3.247 s**, and the activity query took **0.506 s** at the client. This sample
points to connection/roundtrip overhead beyond the server's queue-read execution;
it is not an attribution of the complete Stop/native path. Existing service pool
size **1**, overflow **0**, role limit **5**, and operator NullPool were preserved.
No arbitrary timeout or connection-limit increase was applied.

## Resource and operating limits

One actual **22:47:12** RSS sample, in KiB: API **16,208**, execution **41,440**,
Telegram **47,696**; frontend launcher **3,136** is only the Python wrapper and
excludes its Node process. There is no comparable baseline or improvement claim.
No pool/role/connection limit, timeout or power setting was increased.

The Mac was on AC power. The read-only power inspection showed system idle sleep
configured to **1 minute**, display sleep **10 minutes on AC**, and an existing
idle-system-sleep assertion at a separate sample. That transient assertion does
not guarantee future availability. No new sleep assertion or power configuration
was installed. Sleeping, offline or closed-browser periods do not support local
24/7 browser execution; awake/locked acceptance still requires actual browser
operations with definitive lock telemetry, not heartbeats.

The owner's saved company-stage/startup requirements remain enforced. A single
pending clarification asks whether unknown company stage may be allowed; no answer
or policy relaxation is inferred from elapsed time. Required skills, posting age,
applicant uncertainty, experience and other restrictions remain enforced.

## Acceptance status

| Check | Status | Evidence / limit |
| --- | --- | --- |
| Genuine pagination DOM identified | PASS | Exact own inactive leased tab, 22:39:13 |
| API-only stopped installation and rollback preservation | PASS | Exact candidate; 297 records and binding preserved |
| Configured minimum 50 and original caps | PASS | Queue RUNNING revision 32 after extension update, unchanged policy |
| Earlier page-2 compatibility attempt | FAIL | 1.3.11 Date reset; `provider_context_changed`, zero candidates admitted |
| Current locked API/database readiness | PASS | Three serial 200s with paired LOCKED readings |
| Actual locked background search/sort | PASS | Recommended → Date, 20 links, paired LOCKED DOM observations |
| Bounded focus preservation | PASS | Front/active IDs identical before/after; no continuous claim |
| Actual page-2 navigation/source candidates while locked | PASS | Date, selected page 2, 20 links, 15 new durable jobs; no source error |
| Actual new-job inspections/filtering while locked | PASS | All 15 finished: nine age exclusions, six genuine metadata holds |
| All 15 new jobs matched/prepared | NOT TESTED | None passed prerequisite age/metadata gates; no matching/packet success claimed |
| New eligible application, fill, Apply, independent receipt | BLOCKED | No qualifying inspected vacancy yet; no fabricated outcome |
| Recurring AUTOMATIC | BLOCKED | First new verified receipt and critical checks required |
| Questionnaire/Cohere/Telegram resumption | BLOCKED | Recurring form adapter still unfinished |
| Locked-screen applications and 24/7 submission reliability | NOT TESTED | Locked read/search evidence does not establish form/submission reliability |

Keep Naukri open until genuine recurring application acceptance passes. Preserve QTrino, all
historical/uncertain actions, credentials, account binding, canonical/provider
resume evidence and rollback inventory. No Gmail send, other platform activation,
focus/keyboard/clipboard action, merge, cleanup or release deletion is authorized
by this change.
