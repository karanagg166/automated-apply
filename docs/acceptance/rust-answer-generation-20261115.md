# Rust answer generation checkpoint, 2026-11-15

Implementation: [`e7573605545b3ab1a1e6a1515d2e72711ac00f63`](https://github.com/karanagg166/automated-apply/commit/e7573605545b3ab1a1e6a1515d2e72711ac00f63),
branch `feat/rust-agent-runtime`, [PR #50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling` ([PR #49](https://github.com/karanagg166/automated-apply/pull/49)).
Whole-project acceptance remains **IN PROGRESS**. This is component evidence, not the
owner's final completion report.

Rust now handles direct factual answers, grounded extraction, draft persistence, exact
approved missing answers, scoped reuse grants/revocation and historical opportunity
evidence. Optional Cohere writing shares the existing usage ledger and concurrency gate
with the graph agents. It commits a reservation before one HTTP attempt, holds no profile
transaction during inference, validates the structured response and rechecks the complete
context before saving a reviewable draft. A bounded request-scoped connection keeps Stop
responsive during provider waits. It grants no application or email-send authority.

| Check | Result | Actual evidence |
| --- | --- | --- |
| Standard Rust suites | PASS | 116 tests, zero failures; 109 PostgreSQL cases skipped by this command |
| Native PostgreSQL suites | PASS | 109 tests, zero failed/ignored, 27.27 seconds |
| Combined distinct test count | PASS | 225; differential comparisons are counted inside their containing tests |
| Legacy direct-answer comparisons | PASS | 2,442 fictional cases across factual/link/upload/unknown branches and output limits |
| Legacy reuse comparisons | PASS | 840 intents, 11 raw draft digests and 48 public approval DTO cases |
| Atomic generation and provenance | PASS | Actual local SQL and HTTP; independent-connection reads, deferred commit rollback, no orphan draft or application packet |
| Exact owner answers | PASS | Current approved answer retains the same reviewed draft; profile/evidence changes require fresh review |
| Reuse grants | PASS | Signed owner proof, nonce transaction, current reviewed draft and evidence; cross-job/stale/tampered/revoked reuse refused |
| Employer evidence | PASS | Same-job scope required; disabled/stale context refused; historical excerpt reads verify full digest despite shortened storage key |
| Slow-model control responsiveness | PASS | Local HTTP model deliberately held; Stop200 while generation remains pending; parallel generation429; no idle-in-transaction API connection; released generation200 |
| Provider accounting/recovery | PASS | Fictional Cohere endpoint; one committed reservation per attempt; 429 cooldown persists with no automatic retry; facts changed during response produce no new draft |
| Format / Clippy / Ruff / fixture drift / diff | PASS | Workspace all-targets warnings denied; two corpus checks reproduce checked-in bytes |
| Real Mac execution | PASS | Native Rust executables, loopback HTTP and disposable PostgreSQL17 on this Mac; all candidate/provider responses fictional |
| Live provider/account/browser/submission | NOT TESTED | No owner data, real model request, application, Telegram send, browser interaction or installed service replacement |
| Full service/provider/API migration | NOT TESTED | Other providers, private PDF/storage, browser/application/Gmail and remaining Telegram/service ports still pending |
| Whole-project performance/install/receipt | NOT TESTED | No new CPU/RSS/GPU comparison, install or genuine worker receipt |
| Hosted Actions / merge | NOT TESTED | No dispatch or merge performed |

The first run of the expanded PostgreSQL suite had 108 passes and one fixture failure:
`42883` from timestamp/interval operator precedence in test setup. Parenthesizing the
timestamp expression fixed that fixture; the complete 109-case rerun above passed.
No production SQL or stored data was involved. Sanitized behavioral failures include
`generation_context_changed`, `output_length_exceeded`, `answer_reuse_context_changed`,
`answer_reuse_exact_job_required`, `owner_approval_required` and `rate_limited`.

Reproduce from the canonical repository:

```sh
CARGO_INCREMENTAL=0 cargo test --locked --workspace
CARGO_INCREMENTAL=0 uv run --no-project python rust/scripts/run_postgres_tests.py
CARGO_INCREMENTAL=0 cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.direct_answer_corpus --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.answer_reuse_corpus --check
uv run --no-project ruff check --isolated --select E9,F,I rust/scripts/direct_answer_corpus.py rust/scripts/answer_reuse_corpus.py
git diff --check
```

The Python commands generate differential test artifacts using existing locked local
dependencies; the Rust generation path imports no Python. Current debug/test artifacts
measure approximately 1.1GiB after this milestone; no like-for-like whole-project storage
or performance improvement is inferred from test duration or accumulated build sizes.
See [the completed storage cleanup evidence](storage-cleanup-20261115.md).

Next: remaining provider and service ports, complete API/browser/tool contracts, then
STOP-mode installation, rollback and real policy/history/PDF/focus/resource/receipt
acceptance. External provider failures must remain explicit and cannot trigger duplicate
application actions. Full Python removal is not yet accepted.
