# Cached-feed intake and combined acceptance runner — 2026-11-16

Branch `feat/rust-agent-runtime`, base `chore/uv-python-tooling`, [PR50](https://github.com/karanagg166/automated-apply/pull/50).
Implementation [7500f9a08466112f4f5afbfe05fb0d71b7879fd5](https://github.com/karanagg166/automated-apply/commit/7500f9a08466112f4f5afbfe05fb0d71b7879fd5),
runner timeout corrections [a56e512c3dd79513a3ff86063ddc5e8712bd89cc](https://github.com/karanagg166/automated-apply/commit/a56e512c3dd79513a3ff86063ddc5e8712bd89cc) and [3e8c3409d99ea323bba013e536ca93f11b78eb5f](https://github.com/karanagg166/automated-apply/commit/3e8c3409d99ea323bba013e536ca93f11b78eb5f).
This implements the first remaining discovery slice of the approved completion plan;
it is not implementation or acceptance of the entire plan.

## Changes

Discover responses now expose their server-issued `batch_token`. Authenticated owner
POST `/api/v1/rust-agent/platforms/{himalayas|we_work_remotely}/ingest` accepts only
`{"batch_token":"UUID"}`. It performs no network request and accepts no caller-supplied
jobs, policy, approval or identity. The two explicit MCP ingestion tools advertise
`readOnlyHint=false`; existing read tools remain read-only. These are additions to the
Rust owner API, not routes installed into the running legacy service.

Intake validates the saved platform, token, freshness, source URLs and bounded content.
It uses the existing ingestion advisory lock240204, source observation identity and
canonical URL identity. It does not merge companies from display names or merge different
employer destinations using similarity. Ambiguous canonical identities fail closed.
Expired listings are skipped; original application URLs remain separate from canonical
identity. Existing job titles, status, destinations, scores and owner decisions are not
rewritten. Truncated previews stay in metadata with the complete-description column
NULL; unknown posting age, applicant count and skills remain unknown/unverified.
Company names are retained as observed metadata without inventing a company association.

Jobs, source observations and a per-platform/batch replay ledger commit atomically.
Suppressed writes fail acknowledgement and roll back. Concurrent calls return the same
committed result; exact replay does not rebuild or overwrite later owner decisions.
A database/commit error closes the API connection rather than advertising write replay.
No application preparation, submission, quota admission or worker receipt is created.

`scripts/run_acceptance.py --plan` lists the combined local stages without running them.
`--run` sequences contract drift, Rust format/tests/disposable PG/Clippy, full backend,
frontend tests/typecheck/format/build, extension tests/Brave+Edge builds, browser guards,
continuity tests and diff checks. Builds finish on the Brave target. Private per-stage
logs and atomically replaced status JSON are retained under a unique ignored run path.
The runner stops at the first failure, leaves later stages NOT TESTED, has a45-minute
per-command timeout that terminates its owned test process group, and never dispatches hosted CI, installs, production DDL or live
applications. A passed runner explicitly means local fixture acceptance, not live
platform acceptance. Long fixture commands may launch isolated test browsers.

## Evidence

| Check | Result | Exact count / qualification |
| --- | --- | --- |
| Standard Rust workspace | PASS |158 passed,0 failed;185 PG tests ignored at that earlier compile point |
| Complete disposable PG rerun | PASS |187 passed,0 failed,46.94s; includes six new intake cases |
| Additional HTTP integration | PASS |1 additional distinct native PG case,0.08s;188 PG cases covered across runs |
| Distinct Rust cases executed | PASS |346 =158 standard +188 PG; no claim of a single188-case full run |
| Intake focused PG run | PASS |6 passed,0.43s; overlaps complete187-case run |
| Local acceptance runner | PASS |4 Python tests,0.09s: stop on failure, missing command, timeout/privacy and actual process timeout |
| Clippy / format / diff / Python Ruff | PASS |All-target warnings denied; final Clippy4.78s |
| Combined runner plan | PASS |Stage manifest generated; no full combined run performed |
| Initial full PG attempt | FAIL |186 passed,1 failed: MCP catalog expected old15 tools; corrected to17 with explicit write annotations |
| Live intake / owner DB writes | NOT TESTED |All database evidence is disposable fictional PG |
| Installed service / browser changes | NOT TESTED |No install, restart, browser action or production migration in this slice |
| Full plan and multi-platform automation | NOT TESTED |Remaining ports and real acceptance still open |

The catalog failure was a real integration failure: new ingestion tools cannot be
advertised as read-only. The corrected actual stdio MCP handshake validates the full
17-tool catalog and read/write annotations. New native tests also cover stale/changed
batches, forged destinations, atomic suppressed-observation rollback, concurrent intake,
new-batch deduplication preserving archived jobs, expiry and partial descriptions,
owner HTTP401/405/422 behavior and committed readback. No extra test count is assigned
to assertions inside a case. Backend/frontend/extension prior counts are not reruns.

No provider request, candidate upload, email/message, Apply, quota change, production
schema change, hosted Actions, merge, cleanup or source/release copy occurred. Current
installed identities and STOP162/cap4/hourly1/three uncertain jobs are retained handoff
findings, not freshly sampled live state in this slice. Source tests do not satisfy
Naukri's first strict worker receipt or the pending physical owner account step.
No speed/RSS improvement is claimed: test-body timings are not paired resource benchmarks.

```sh
cargo test --locked --workspace
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests --filter feed_intake
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
uv run --no-project --python .venv/bin/python python -m pytest tests/test_acceptance_runner.py -q
uv run --no-project --python .venv/bin/python python scripts/run_acceptance.py --plan
# Run the complete fixture cycle after the remaining implementation is integrated:
uv run --no-project --python .venv/bin/python python scripts/run_acceptance.py --run
```

Next finish automatic discovery scheduling/filter integration, remaining browser/execution,
account/Gmail/Drive/provider/CLI/Telegram parity and platform-specific real acceptance.
Then run the combined fixture cycle, reviewed STOP-only whole-writer-family cutover,
rollback/focus/restart/locked tests and24-hour observation under existing quotas. The
failed Brave window-creation path remains suspended. Brave is primary; Edge is the
explicit alternative; Safari is outside this accepted completion scope.
