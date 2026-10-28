# Phase 3.5 integrated engineering conclusion

**ENGINEERING PASS. External activation PARTIAL.** Verified locally on 2026-10-28 without waiting for PR #39 to merge. This report supersedes the preparation-only gate in `phase35-final-integration.md`.

Tested final implementation: `cbbc1d8bef148ea4953322d19e27c03c4371fa29`. Resolve the report-inclusive final head with `git rev-parse integration/phase35-final-20261028`. Worktree: `/Users/karanagg/Desktop/Projects/automated-apply-phase35-integrated`, linked to the original repository. The primary checkout, source-agent branches and private configuration were preserved.

History-preserving merges include PR #39 head `e57178b22e453119f4ba449dae28f36c01b6edc5`, complete Codex head `e84e45bf70a62871d04c0fd3c147c4df50e400fb`, preparation head `0721857b766a8eac0a34262117164766075884d2` (including actual Gmail persistence fix `709c814` and preflight `ae84afc`), and final AGY head `cc903b71daf05fe260ca72b64e1de61ea06f3fed`. Every pin is an ancestor; no cherry-picks or duplicate implementation commits were introduced. The three merges had no conflicts.

| Combined local check | Final result |
| --- | --- |
| Full backend with disposable PostgreSQL 17, actual restart enabled | **2,546 passed**, zero failures/errors/skips; 724.08s; two existing PDF deprecation warnings |
| Gmail migration readiness, both schemas, replay/drift/rollback/RLS | Passed |
| Full frontend Vitest | **185 passed**, 25 files |
| Actual production frontend + FastAPI + PostgreSQL Chromium | **17 passed** |
| Full dashboard Chromium suite, isolated fictional SQLite fixture | **12 passed** |
| Extension units and MV3 build | **49 passed**, build passed |
| DOM races | **25 passed**; zero external requests/submissions |
| Actual installed React in isolated CDP worlds | **4 passed**; zero form POSTs/submissions |
| Popup and durable unanswered-field browser journeys | Both passed |
| Actual MV3/native/FastAPI/PostgreSQL Chromium | **23 passed**; zero form submit events/POSTs; 22 history rows all `submitted:false` |
| Final frontend typecheck/format, production build | Passed |
| Changed Python Ruff; full-app Bandit; unchanged-baseline secret scan/private-artifact check | Passed |
| Pinned Python and production frontend dependency audits | No known vulnerabilities |
| OpenAPI export and regenerated TypeScript | Byte-identical to committed API types |
| Hosted workflow policy | All three unchanged; workflow_dispatch only; no jobs dispatched/rerun |

Focused checks are included in, rather than added to, the complete totals. Backend full regression ran at `4fbb789c52520a0bea3cbfffca2de1522283ca83`; subsequent changes are the browser-test corrections, one isolated dashboard-fixture country value and documentation. Backend application and extension source trees stayed unchanged. Affected browser checks and final typecheck/format/security were rerun on the final implementation. Heavy groups ran sequentially using the existing inode and `fcntl.flock` at `/tmp/automated-apply-heavy-tests.lock`. The native harness acquired that lock itself to avoid nested-lock deadlock.

## Defects and failed-run accounting

Integrated fixes include durable Gmail failed-import rejection/retry, React-controlled checkbox/radio events, stale DOM/option and one-shot fill fences, bounded discovery timings, and AGY's final frontend corrections.

Combined verification additionally corrected:

- Restart fixture safety allowlist: the new owned disposable container/port was initially refused. Added only its exact pair; focused restart/recovery then passed.
- Browser refresh assertion: prior journeys advance packet revisions. Assert the revision returned by the real PATCH response instead of hard-coding revision 2.
- Pipeline assertion: several fictional packets share a company. Assert the exact packet link in Needs Input and its absence from both submitted columns.
- Compensation assertion: prior journeys legitimately approve compensation facts. Assert that legal consent remains incomplete/manual, regardless of factual answer availability.
- Indian startup fixture: the new explicit country filter requires country evidence. Added `country="India"` to the fictional company observations; retained exact 2–10 size filtering.

Initial failed runs are retained, not counted as passes: one restart-fixture failure (20 other cases passed), browser revision and locator failures, a combined compensation-state failure (16 other journeys passed), and an initial dashboard country-fixture failure (six passed, five serial successors did not run). Final complete affected suites passed. No product assertion was weakened to accept a submitted application or invented answer.

## Timeout evidence

The current instrumented fictional Greenhouse/PostgreSQL benchmark committed 3/27/100 jobs in 1.36/8.86/31.76 seconds with simulated 30ms SQL and 100ms provider latency. The 27-job case spent 8.54s in ingestion, 0.12s in the provider, acknowledged both commits, and left zero pool connections checked out. This is a latency sensitivity experiment. The historical 27-job, approximately 95.06s live failure lacked phase timings; its original bottleneck remains undetermined.

## External activation and publication

No live DDL, new Gmail consent/message access, provider collection, Apollo lookup, deployment or genuine employer autofill/submission occurred. Existing genuine activation receipts are historical; they were not refreshed by these fictional engineering suites. Gmail schema/runtime activation, each account's scope/selection/compliance review, provider rights/current credits/bounded authorization and genuine permitted applicant gestures remain separate external gates. See [exact Gmail operator steps](phase35-gmail-operator.md).

One local PR draft is [prepared here](phase35-integration-pr.md). PR #39 remains owner-reviewed; do not auto-merge it. Once its merge is independently verified, fetch actual main, reconcile its ancestry with this ready candidate, compare source trees and rerun only checks affected by changed source. Publish this one integration PR before the dependent Phase 4 PR. Do not repeat preparation on another branch.

Private receipts, runner logs, JUnit, failed traces, audit outputs and API comparison are outside Git at `~/Library/Application Support/Automated Apply/phase35-integrated-evidence/`. No mailbox identities, private candidate facts, credentials or resume bytes are committed.
