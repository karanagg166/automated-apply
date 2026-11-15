# Packet review, public feeds and runtime boundaries — 2026-11-15

Implementation [`2b6c4e1cc16452172627129e4cd761280b91f134`](https://github.com/karanagg166/automated-apply/commit/2b6c4e1cc16452172627129e4cd761280b91f134),
with byte-preserving fragment correction
[`c57b7e4035d2d34f900821c3dd362cd8fda9ecc0`](https://github.com/karanagg166/automated-apply/commit/c57b7e4035d2d34f900821c3dd362cd8fda9ecc0),
branch `feat/rust-agent-runtime`, [draft PR50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling`. This is source acceptance, not a complete runtime cutover.

## Resulting behavior

Rust now supports revision-bound packet review/approval, explicit resume/destination
confirmation, manual handoff and owner-reported submission/outcome tracking. Execution
bindings, reviewed-answer revisions, packet events and preparation notices participate
in the same transaction. Conflicting revisions, suppressed writes and commit failures
cannot advertise success. Manual reports remain self-reported and unverified; they
cannot create a strict worker receipt, consume/refund an Apply admission or mark a
saved job as provider-confirmed. Review and notification gates preserve STOP, terminal,
stale, owner-preference and automation-revision checks. No browser submission is added.

Public Himalayas JSON and We Work Remotely RSS discovery now has closed platform
selection, fixed HTTPS endpoints, response/depth/field limits, source attribution,
deduplication and durable per-platform reservations/cache/cooldowns. Unknown applicant
counts and geographical restrictions remain unknown/source data. XML doctypes and
foreign listing destinations are rejected. Website descriptions remain untrusted text.
These tools return listings; ingestion, account/eligibility verification and actual
applications remain unfinished. New feed code was tested with fictional data, not
against those providers in this checkpoint.

`contracts/http-security.json` supplies package-local Python/Next.js policy copies and
Rust owner-approval patterns. Tests compare generated copies, exact registered API
dependencies and gateway behavior. Bearer authentication, session/CSRF, separate owner
HMAC proof, method/path/body binding and nonce protections remain. Composition/lifecycle,
HTTP boundary/error handling, Rust handlers, frontend application UI and extension DOM
sources now have domain modules. Extension fragments retain one private closure and
the exact generated executor bytes; builds/tests reject drift.

Cooperating Python processes hold a shared target-specific writer-family lease; the
replacement Rust host acquires it exclusively before connecting. Existing service
leases remain. This is a single-host source fence. Older installed releases and
standalone writers still require an explicit stop/inventory before cutover. The
[ownership and connection budget](../architecture/runtime-ownership.md) identifies
current/replacement writers and a calculated Rust ceiling of four database connections
with Telegram, including the shared transient document/generation permit. This is not
a fresh hosted pooler/role capacity measurement or a distributed database fence.

## Validation matrix

| Check | Result | Exact evidence and limit |
| --- | --- | --- |
| Standard Rust workspace | PASS | **152 passed,0 failed**,181 PG cases ignored here; dedicated run below |
| Native disposable PostgreSQL | PASS | **181 passed,0 failed,0 ignored**,45.42s; fictional isolated database |
| Distinct Rust cases | PASS | **333** across the two disjoint suites |
| Review/notice/tracking parity | PASS |32 owner review requests,45 actual Python notice cases,71 tracking/report requests; comparisons inside tests, not additional test counts |
| Complete sequential Python rerun | PASS | **3,364 passed,64 skipped,2 deprecation warnings**,963.55s |
| Focused boundary and policy/lock checks | PASS |95 and32 passes; overlap the full Python run, do not add to its count |
| Frontend unit suite | PASS | **305 passed**,41 files,22.40s |
| Frontend typecheck/build/format | PASS | Recorded final checks; production build succeeded |
| Extension unit suite after fragment correction | PASS | **399 passed,0 failed**,9.796s; generated executor unchanged |
| Clippy/format/Ruff/policy and oracle drift/diff | PASS | All-target Clippy with warnings denied; changed Python files checked with E9,F,I |
| Actual running API | PASS | Fresh loopback health200 and ready200; authenticated saved queue STOPPED revision162 |
| Actual running Brave native bridge | PASS | Extension-origin native health matched request ID, Naukri site permission true; selected owned tabs unchanged |
| Full desktop focus acceptance | NOT TESTED | No fresh bounded installation path; long-interval desktop comparison differed as qualified below |
| Actual Naukri sign-in / strict worker receipt | BLOCKED | File permission/native health does not prove account sign-in; no new Apply or receipt |
| Current Cohere connection | PASS | Recorded official model metadata authentication and configured model availability; generation flags disabled, no generation performed |
| New public-feed provider requests / job ingestion | NOT TESTED | Fictional transport/parser/database cases only; ingestion not implemented |
| Rust production migration/installation | NOT TESTED | Legacy API/execution remain on8e985c9; full Rust host not installed |
| Whole-system CPU/RSS/GPU/latency improvement | NOT TESTED | Test durations and calculated connection ceilings are not a paired production benchmark |
| Fully autonomous multi-platform acceptance | FAIL | Remaining work below; do not call the project100% operational |

The first full Python run had3,357 passed,64 skipped and6 failed in916.56s. Three
search failures exposed static `/jobs/search` being registered after `/jobs/{job_id}`;
composition order was corrected and an explicit route-order regression added. A stale
online-profile fixture omitted the now-required window ID. Two isolated browser
dropdown cases failed under fixture load. The six targeted cases then passed in10.10s;
only the subsequent complete sequential3,364-pass run establishes the clean full result.
Earlier metadata coverage saw zero route dependencies because of nested FastAPI route
composition; the test now uses actual route contexts and verifies all eight guarded
dependencies. No protection was removed to satisfy the test.

The final staged diff found trailing blank lines in four new extension fragments.
The follow-up makes separators explicit, removes those blank lines and verifies that
the assembled executor is byte-for-byte unchanged. All399 extension tests were rerun.

## Actual Mac limits

The owner confirmed granting Brave's macOS file permission. A later check attached to
the existing owned browser with Playwright `noDefaults`, used its already-running
extension worker for native health, queried the Naukri origin grant, and compared
selected tab/window IDs before/after. It did not create a browser/profile/tab, navigate,
reconnect the profile, enable commands, change policy or execute Apply. Existing owner
cookies were not exported or copied. Site login was not inspected by this check.

A passive desktop sample initially matched foreground/window order. Comparing that
same sample again across the interruption and subsequent work differed in both values.
The interval includes owner activity; causation is not established. Do not treat this
as a passed bounded focus test, and do not activate/restore windows to force a pass.
The narrower extension-selected-tab comparison did pass. No new installation or
unattended maintenance acceptance is claimed.

Saved STOPPED162 was freshly read; supervised4/hourly1, three quarantined uncertain
admissions and zero strict worker receipts are retained operational findings from the
prior checked handoff, not newly audited counts here. The remaining allowance must
never be inferred from a reset daily count. No quota, profile, account binding, resume
or application history mutation occurred in this verification. Existing workers may
continue their previously authorized background work; this is not an assertion of
zero mailbox activity. Gmail sending remains outside this work.

No hosted Actions, merge, cleanup, production database DDL, new runtime installation,
model generation or outbound message was performed in this source checkpoint.
Private logs/configuration/browser data remain ignored; only sanitized summaries
and fictional contracts are published.

## Reproduction and next work

```sh
cargo test --locked --workspace
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
uv run --no-project --python .venv/bin/python python -m pytest backend/tests -q --durations=12
uv run --no-project --python .venv/bin/python python scripts/sync_http_security.py --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.packet_review_corpus --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.packet_tracking_corpus --check
pnpm -C frontend test
pnpm -C frontend typecheck
pnpm -C frontend build
pnpm -C frontend format:check
pnpm -C extension test
pnpm -C extension build --browser=brave
git diff --check
```

Continue Rust discovery ingestion, browser/intake/execution, account/Gmail/Drive,
legacy CLI/Telegram/fallback/AGY service parity and platform-specific account/form/
receipt acceptance. Preserve the physical owner account step; file access is a
different prerequisite. Finish production schema/access review, whole-family STOP
cutover/rollback, exact installed identity/history/PDF/focus verification, restart/
locked operation and paired resource measurements. The first strict Naukri worker
receipt remains required before recurring AUTOMATIC. Every additional platform
needs its own actual acceptance; a public listing is not an application receipt.
