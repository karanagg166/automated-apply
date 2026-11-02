# Focused ordinary fresher searches — Naukri OPEN

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`. Exact API implementation and installation:
[`8473bdc85588863f55c10b0b941e19b849eb9815`](https://github.com/karanagg166/automated-apply/commit/8473bdc85588863f55c10b0b941e19b849eb9815).
Extension fix and installation:
[`0c8b1d7eca0a1245ed02bebfeceb0b25c6457580`](https://github.com/karanagg166/automated-apply/commit/0c8b1d7eca0a1245ed02bebfeceb0b25c6457580),
version1.3.23, same stable extension ID.
All times below are UTC on November2. No new submission or recurring AUTO
acceptance is claimed.

## Problem and resulting behavior

Real inactive search DOM showed a Date-sorted frontend-role search with many
senior and unrelated jobs. Inspecting every such listing delays suitable work.
For a confirmed profile with less than one year of verified experience, discovery
now interleaves an ordinary `<target role> fresher` keyword search with every
original target-role search. An existing fresher query is preserved without
appending the same word. Custom role searches use the same rule.

This is a search hint. It does not change the saved target titles, verified
experience, required skills, match scoring, age/applicant limits, unknown-count
review, application authorization or any other eligibility guard. Original
searches remain because suitable jobs need not use the word fresher. Full listing
facts, matching, deduplication and independent preparation/write checks still
apply. Existing durable cursor, three-page bound and300-second interval remain.
The source does not call a private provider API or invent an experience fact.

## Actual provider evidence changed the implementation

A genuine owned inactive fresher search at11:13:16, while the Mac reported LOCKED,
showed the recognized Recommended control and20 initial candidate links. Their
visible experience labels included multiple0–1/0–2-year and junior roles. This
capture preceded the existing Date-sort step, so it was not accepted as improved
final discovery.

The same search actually completed11:13:25 without an error, adding3 identities.
All3 were senior-role URLs and **none overlapped** the captured initial20 links.
This is an observed semantic failure, not permission to relax eligibility. It
also does not establish the cause inside Naukri or prove the entire final result
set changed, because only newly added identities were compared.

Extension1.3.23 now preserves the recognized Recommended control for fresher
keyword searches, including the validated second-page path. An unknown order
requires review. Original-role searches retain complementary Date behavior.
Full job-page age and every eligibility check remain enforced; relevance order
never establishes freshness or application suitability. Isolated Chromium cases
model the actual relevant-before/unrelated-after-Date transition, verify that
only the initial relevant link is reported, validate page two and reject unknown
ordering. The old search-order implementation was not called successful merely
because a query URL loaded.

The installed extension then completed a genuine keyword search at
11:25:08–11:25:24 without error, adding17 new identities. The owned inactive
page at11:25:17 displayed Recommended; the Mac reported UNLOCKED, with no agent
activation or input. All17 newly added URLs match the captured20-link Recommended
set, independently compared through the durable queue API. Unlike the prior
Date-sorted cycle, the relevant ordering was preserved. However this particular
rare-role query still returned many senior jobs. This proves candidate-set
preservation, **not improved fully eligible yield or a new application**. All17
were still awaiting full inspection at the comparison; no card label established
eligibility. A later queue snapshot had869 identities:131 awaiting inspection,
245 held,492 skipped and1 historical application.

## Validation and exact deployment

| Check | Result | Evidence and limits |
| --- | --- | --- |
| Targeted source backend tests | PASS |59 tests,6.95s, including6 added scenarios |
| Exact candidate backend tests | PASS |59 tests,7.19s, own environment |
| Dependency consistency, Ruff and diff | PASS | Independent environment; no broken requirements; E9/F/I checks |
| Exact API installation | PASS | STOP102,835 records, new API process, ready200/frontend login200/worker online |
| Identity/profile/policy/history and protected components | PASS | Profile5, binding1, verified skills/PDF state and other components preserved |
| Resume | PASS | RUNNING103; SUPERVISED lifetime cap1/hour1 and all filters unchanged |
| Genuine initial keyword page versus completed Date-cycle | FAIL, diagnosed | Junior initial set;3 newly added senior identities with0 overlap |
| Targeted Node extension regressions | PASS |89 tests,1.343s;2 added cases |
| Isolated Chromium extension cases | PASS |20 cases,42.293s;3 added ordering cases;0 live/provider requests or choosers |
| Exact extension cutover | PASS |24/24 files, STOP104/841 records, same ID, fresh native reconnect, ready200/frontend200, protected files and focus snapshots equal |
| Fresh installed keyword-preserving cycle | PASS | Genuine11:25:08–11:25:24 cycle added17; all17 match the captured Recommended candidate set |
| Improved suitable-job yield | NOT PROVEN | Requires actual resulting listings and eligibility |
| New real application and independent receipt | BLOCKED |0 new submissions /0 admitted Apply at last acceptance snapshot |
| Recurring AUTO, restart and locked application completion | NOT ACCEPTED | First-receipt and critical-check prerequisites remain |

The added scenarios cover verified experience0/sub-year/one year/four years/
unknown, fresh-session durable query rotation, custom queries, preserved originals
and exhausted-page continuation. An initial fixture confirmation used the
pre-flush profile version; flushing the fixture before confirming its actual
version corrected the failures without weakening the production confirmation.
Tests are isolated fixtures, not provider submission evidence. Counts overlap
previous queue regressions; unchanged large suites were not repeated.

Candidate environment creation took2.102s, dependency installation15.571s,
`pip check`0.664s; the whole pytest subprocess12.037s includes startup, while
pytest reported7.19s. API startup completed11:07:14 and installation verification
completed11:07:29. The9.349s Stop-and-following-queue-snapshot measurement is not
an isolated Stop latency and does not close the performance blocker.

The API installation replaced only APIb3abc9e with8473bdc. The later extension-only
installation replaced1.3.22/ec1a5b7 with1.3.23/0c8b1d7 at11:18:52, preserving
all24 files' exact inventory, key and permissions. Actual frontend/native remain
414a260; execution/Telegram remain2ceea5e. The extension installation preserved
API8473bdc, profile/account/skills policy and all841 records. Queue resumed
RUNNING105, same SUP1 policy. Exact previous1.3.22 bytes, protected-file hashes and
rollback inventory are retained. No service was restarted for this extension cutover.
Its8.530s control-plus-snapshot duration is also not an isolated Stop latency.

Extension candidate build used byte comparisons of the seven loaded modules and
three test drivers against the tested source before reusing canonical tester
dependencies; no dependency symlink was installed and no identical browser suite
was repeated merely to change its label. Build and exact24-file audit passed.
Exact previous APIb3abc9e plist/runtime, protected-file hashes and rollback plan
are retained. No browser activation, keyboard, clipboard, owner-tab change,
credential edit, history deletion or database restore was used. Rollback would
stop the queue, unload the new API, restore its exact previous plist/runtime,
verify integrity/readiness and retain every release. No rollback was needed.

Reproduction:

```sh
.venv/bin/python -m pytest backend/tests/test_naukri_background_queue.py -q
.venv/bin/ruff check --isolated --select E9,F,I backend/app/execution/naukri_native.py backend/tests/test_naukri_background_queue.py
pnpm -C extension exec node --test tests/naukri-observation.test.mjs tests/naukri-queue.test.mjs
pnpm -C extension exec node tests/naukri-queue.browser.mjs
pnpm -C extension build
git diff --check
```

Next: inspect full listing results and address inspection backlog scheduling
without delaying application progress/reconciliation behind new discovery,
complete the first supported eligible application with independent persistent
receipt, then bounded recurrence and actual restart/locked application acceptance.
The once-asked unknown-count decision remains pending, not silently allowed.
Other platforms remain OFF, Gmail read/draft-only, hosted Actions manual-only,
and PR #48 remains unmerged.
