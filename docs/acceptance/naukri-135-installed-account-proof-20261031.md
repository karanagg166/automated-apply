# Extension 1.3.5 installed; real discovery continues; submission remains OPEN

Branch `fix/live-prepare-discovery-20261030` → `main`, [PR #48](https://github.com/karanagg166/automated-apply/pull/48).

**Zero new Apply admissions, submissions or receipts in these observations.**
The one retained historical application was preserved and never replayed.
Recurring AUTOMATIC is not activated. The standing first-application policy is
SUPERVISED, maximum one new submission, maximum one per hour, with Telegram
notification on a confirmed receipt. This is not full end-to-end acceptance.

## Exact installed and proposed versions

- Installed API/execution/Telegram/frontend/native:
  [`fc91a219d5b824f934bb733eaf20166661e1f08b`](https://github.com/karanagg166/automated-apply/commit/fc91a219d5b824f934bb733eaf20166661e1f08b).
- Installed same-ID extension **1.3.5**:
  [`3644b65aa7c2d3707a58b35f64df266807746a6d`](https://github.com/karanagg166/automated-apply/commit/3644b65aa7c2d3707a58b35f64df266807746a6d), owner approved.
- Built **API plus extension 1.3.6 candidate, NOT INSTALLED**:
  [`331ce17711667d21bc96c42d8dc74793d670095f`](https://github.com/karanagg166/automated-apply/commit/331ce17711667d21bc96c42d8dc74793d670095f).

The earlier [real PDF/account evidence](naukri-real-pdf-location-fix-20261031.md)
and [fc91 installation/readiness evidence](naukri-fc91-installed-live-20261031.md)
remain applicable to their stated observations; their version status is superseded here.

## Actual Mac installation and live evidence

At **15:24:24 UTC, 2026-10-31**, all 22 exact approved extension files were
deployed to the existing stable directory and Chrome's ordinary Reload control
was used. At **15:24:26**, installation verification passed with the queue
**STOPPED, revision 8**. Stable extension ID/key/permissions were unchanged; all
six protected service/config/native references matched the pre-install inventory.
Two earlier setup-page JavaScript timeouts happened before any file replacement;
the queue remained stopped. Only the existing setup page was reloaded, with no
active-tab/front-window change. No historical release or backup was deleted.

Chrome subsequently reported version 1.3.5. Developer diagnostics retained two
older errors from an operator attempt to access an unavailable runtime API on
the settings page; they were not erased or represented as background-worker errors.

Eighty-six proven read-only metadata failures were retried, excluding any admitted,
packet-associated or uncertain action. PREPARE_ONLY resumed first. After the
canonical PDF proof, installed extension and approved Profile 8 binding were
rechecked, the owner's standing first-application scope was enabled at **15:40:24**:
queue **RUNNING, revision 11**, SUPERVISED cap **1**, hourly cap **1**. Global daily
preferences remained unchanged. No broader recurring submission authorization
was enabled. The optional compare-only profile sync was temporarily disabled:
its auto-write setting was already false and its approved-fields list empty;
the original preference was saved privately. Account/profile/resume records were
not changed by this operational pause.

Repeated genuine discovery continued at **300 seconds**, growing from 73 to
220 unique admitted URLs. At the **16:20:32 consumer snapshot**, the last search
cycle ran **16:17:04–16:17:17**, added zero duplicates, and had no source error.
Queue stages were:

| Actual stage/reason | Count |
| --- | ---: |
| DISCOVERED queued / leased | 157 / 1 |
| SKIPPED: posting_outside_age_limit | 48 |
| SKIPPED: current_profile_preferences_or_required_skills_exclude_job | 2 |
| NEEDS_INPUT: backend_not_ready | 4 |
| NEEDS_INPUT: job_required_facts_unrecognized | 4 |
| NEEDS_INPUT: posting_age_requires_review | 2 |
| NEEDS_INPUT: applicant_count_requires_review | 5 |
| Historical SUBMITTED_RECORDED | 1 |
| READY_TO_APPLY / new confirmed submission | 0 / 0 |

These are queue records, not eligible applications. At least one actual matching
evaluation scored **15** and was excluded by current profile preferences/required
skills. No threshold, age, applicant or experience filter was relaxed to create
a submission candidate.

An ordinary **Sort → Date** interaction on the worker's own inactive genuine
search tab yielded **20** cards: one Just now, four Few hours ago, six Today and
nine 1 day ago. The SPA did not add a query parameter. Existing durable admission
accepted only **3** new URLs under its 200-pending backpressure limit; **11** of
the 20 were present for prioritized safe reads. Another **186** queued read-only
metadata items were deferred for **20 minutes**, with original availability
values saved privately. No work was deleted or unsafe action retried. This was
an operator-assisted live discovery check; automatic Date sorting is still open.

Real modern listings now produced nonempty location, experience, skills and job
description. Some structured dates were genuinely in 2025 and correctly failed
the configured two-day limit on the Mac's 2026-10-31 date. Unknown or ambiguous
facts continued to require review.

## Genuine blockers behind the next candidate

One actual listing showed **Applicants: Less than 10**, experience **0–1 years**,
17 extracted skills and a 926-character description. The installed parser treated
that applicant label as unknown. The candidate represents it as bounds **0–9**,
never an invented exact count. A separate actual **50+** label remains lower
bound 50 with unknown upper bound. Malformed or competing labels remain unknown.

Actual job pages had **zero visible account-email nodes**. Opening their genuine
profile-menu control also exposed no email. These observations establish absence
of usable identity evidence on those pages, not a different account. The menu
closure was not independently observed before the worker closed its own tab.

The candidate obtains a genuine profile-page identity observation, checks it
against the separately approved platform account, and carries it for at most
**two minutes** through the exact work ID, selected profile/version, browser
session, window and owned tab. A different, expired, future-dated or malformed
proof blocks admission. A visible mismatching or ambiguous email still blocks;
a candidate contact input is not treated as the platform login identity.

History reconciliation first refreshes the same profile identity in the same
owned tab, then navigates to history. It requires two distinct actual history
documents before confirming a receipt. The new `verify_account` operation can
continue only to reconciliation, never Apply. Unknown actions retain their
existing Apply fence, with bounded identity/history reads. The existing yield
when the owner activates Naukri remains intact.

## Targeted validation: fixtures separated from live acceptance

| Check | Exact result | Scope |
| --- | --- | --- |
| Submission, identity, profile sync, queue backend regressions | **59 passed, 9.18 s** | Isolated fixtures |
| Observation/queue/native protocol Node tests | **37 passed, 4.606 s** | Isolated fixtures/native offline bounds |
| Chromium execution regressions | **23 cases passed, 10.275 s** | Fictional pages, zero live/unexpected requests or choosers |
| Chromium queue regressions | **4 cases passed, 6.399 s** | Fictional pages, zero provider/chooser requests |
| Fresh disposable PostgreSQL 14.24 journey | **2 passed, 0.595 s** | Native/worker commit and independent receipts; zero real applications |
| Exact candidate own-venv smoke | **4 passed, 15 deselected, 1.90 s** | Complete journey, lost result, identity refresh and bounded failure |
| Ruff E9/F/I, Prettier, diff, build, pip check | PASS | Changed files and own candidate environment |
| API type regeneration | PASS, no tracked contract/type change | Existing work descriptor remains opaque |

An additional backend invocation used a nonexistent `test_profile_sync.py`
path and collected zero tests; the corrected command above passed all 59. Counts
are overlapping checks, not a combined claim of unique tests. No full frontend
suite/build or hosted Actions was run for these backend/extension-only changes.
Disposable PostgreSQL used its own fresh loopback server and database; that
server was stopped and its fixture files preserved. Production was not used.

Reproduction from the candidate checkout:

```sh
.venv/bin/python -m pytest backend/tests/test_naukri_submission.py backend/tests/test_naukri_identity.py backend/tests/test_naukri_profile_sync.py backend/tests/test_application_queue.py -q
node --test extension/tests/naukri-observation.test.mjs extension/tests/naukri-queue.test.mjs extension/tests/native-protocol.test.mjs
node extension/tests/naukri-execution.browser.mjs
node extension/tests/naukri-queue.browser.mjs
pnpm -C extension build
.venv/bin/python -m pip check
```

Browser fixture runners need the existing development Playwright dependency;
production extension building uses Node core modules and no dependency install.

## Performance limits and rollback

Live native/database observations still included `lock_timeout` / SQLSTATE
**55P03**, HTTP 503 and extension `backend_not_ready`. Some poll transactions
performed roughly **24–30 statements** while holding the owner lock for about
**7–16 seconds**. A separate snapshot found zero blockers, API transaction age
0.747 s and idle execution/Telegram connections; this does not disprove the
intermittent contention. Temporarily disabling the optional compare work removes
its extra reads but is not a database-performance fix. No connection limit,
timeout or queue-integrity protection was increased. CPU/RAM were not benchmarked.
The 13-second search cycle and earlier differently loaded cycles are observations,
not a controlled performance comparison. Slow Stop/readiness remain open.

A subsequent **read-only production EXPLAIN ANALYZE** of the actual active-queue
selection shape returned **170 rows**, planning **0.726 ms**, server execution
**1.718 ms**, **316 shared-buffer hits / 0 reads**. Three separate clock-query
round trips took **326.88 / 163.22 / 162.63 ms**. The role cap remained **5**;
the snapshot contained four connections including the sole temporary operator,
zero blockers, idle execution/Telegram connections and API waiting for its client
inside a transaction. The operator connection was closed after the probe.

The last **40** retained request timings containing profile authorization
(a mixture of native operations, not 40 polls) all had HTTP **200**. Their request
latency was **1.539 / 3.044 / 10.263 s min/median/max**, SQL read count
**3 / 11 / 25**, SQL-read duration **0.454 / 1.828 / 8.687 s**, owner-lock stage
**0.908 / 0.997 / 3.525 s**, and connection occupancy
**1.072 / 2.520 / 9.754 s**. Pool acquisition was at most **1 ms** in this sample.
The owner-row insert stage alone had median **0.779 s**, versus median **0.165 s**
for the row-lock stage. These observations identify repeated remote statements
and lock occupancy as optimization targets; they do not establish a controlled
before/after improvement or resolve earlier 503s. Review reducing redundant reads
and the existing-singleton insert round trip while retaining transaction-scoped
locks, missing-row creation, savepoint handling and admission fences. This probe
made no source, installed runtime, SQL schema or capacity change.

Candidate `331ce17` has clean immutable source, its own venv with matching pinned
dependencies and passing `pip check`, plus **22/22** exact extension build files.
Private inventory preserves the current API plist and all **22/22** installed
1.3.5 files, with hashes for six protected service/config/native references.

Proposed cutover, **after owner approval of the exact full SHA above**: stop the
queue and verify no active/uncertain write; keep it stopped while replacing only
the API runtime reference and exact same-ID extension build; restart API and use
ordinary extension Reload; verify services/native/database/profile binding,
unchanged policy/data and retained receipts. Only then resume the standing one
eligible supervised application. Execution/Telegram/frontend/native remain fc91.
Public schemas/native command names are unchanged; the internal read operation
uses existing opaque work data and the existing PROFILE_OBSERVED result. The
execution worker prepares packets and does not admit Apply; candidate API owns
admission and receipt handling. No migration, credentials or new permission.

On failure, keep the queue stopped; restore the exact previous API plist and
1.3.5 extension files, restart/reload and verify the protected inventory. Preserve
any observed or uncertain outcome for read-only reconciliation. Never restore a
database snapshot over new outcomes, erase history or replay Apply. All older
releases, full fc91 rollback, private evidence and canonical/provider PDFs remain.

## Acceptance matrix and next actions

| Requirement | Status | Practical limit / next action |
| --- | --- | --- |
| Intended Profile 8 binding | PASS observed | Approval persisted independently of contact email |
| Provider-saved canonical resume | PASS supervised bytes | Actual Download produced matching 100,198-byte PDF; unattended capture still unaccepted |
| Approved extension 1.3.5 installation | PASS | Same ID, exact files, stopped cutover, protected references |
| Repeated real discovery/deduplication | PASS bounded observations | 220 URLs; Date sorting still operator-assisted |
| Real metadata/filter/match decisions | PASS exercised exclusions | Less-than label and missing job-page account evidence block eligible progression |
| Next account/applicant fixes | PASS fixtures / BLOCKED installation | Exact-SHA owner approval required for API plus 1.3.6 |
| Slow native/DB/Stop | FAIL unresolved | Intermittent lock failures remain; no limit inflation |
| New supported fill/questionnaire/upload/Apply | NOT TESTED live | No eligible ready item or new action admission yet |
| Independent new receipt/Telegram accuracy | NOT TESTED live | No new receipt; historical fence preserved |
| Recurring AUTOMATIC | NOT ACTIVATED | First actual receipt and critical checks required |
| Restart/locked-Mac recurring submissions | NOT TESTED | Heartbeat/readiness alone is insufficient |
| 24/7 completed Naukri automation | OPEN | Mac awake/connected; genuine supported submissions and recurrence still required |

Next: install the reviewed candidate after exact-SHA approval, re-observe genuine
fresh candidates, verify unattended saved-resume capture, then complete the first
eligible supported real application and independent history receipt. Continue
questionnaire/Cohere/Telegram-resumption, replacement-upload support if needed,
automatic Date sorting, SQL-lock profiling and actual restart/locked acceptance.
No Gmail send, other-platform activation, QTrino replay, uncertain Apply retry,
merge, hosted job or cleanup occurred.
