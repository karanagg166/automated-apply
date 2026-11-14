# Rust model adapter checkpoint, 2026-11-15

Implementation: [`132e586d1f7bd5e6725d743dffab1144795368e0`](https://github.com/karanagg166/automated-apply/commit/132e586d1f7bd5e6725d743dffab1144795368e0),
branch `feat/rust-agent-runtime`, [PR #50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling` ([PR #49](https://github.com/karanagg166/automated-apply/pull/49)).
Whole-project acceptance is **IN PROGRESS**. No runtime installation or real generation
was performed.

Gemini writing now uses Rust's existing bounded HTTP transport and shared grounding/save
pipeline. Configuration requires the saved enable flag, separate approved monthly request
count, candidate-data authorization, explicit model and key. Requests use Google's native
[GenerateContent API](https://aistudio.google.com/api-reference/generate-content/generate-content)
with a JSON schema and no tools, URL retrieval, redirects or automatic retries. The key
stays in a header rather than a URL. Exactly one complete model text result is accepted;
blocked, truncated, tool-bearing and malformed results cannot become drafts. Reported
output usage includes thinking tokens. Existing Cohere and Gemini ledger rows stay distinct.

Concurrent-budget validation found an earlier ledger error path that relied on SQLx
transaction Drop. Drop queues rollback until connection reuse; a rejected but quiet caller
could therefore retain the advisory lock. Rejected reservations now await rollback before
returning. The regression keeps the rejected connection open while another provider reserves
under a two-second deadline. This fix also applies to Cohere.

| Check | Result | Evidence |
| --- | --- | --- |
| Standard Rust workspace | PASS | 119 tests, zero failures; 114 dedicated PG cases ignored by this command |
| Dedicated native PostgreSQL | PASS | 114 tests, zero failed/ignored; 28.82 seconds |
| Combined distinct count | PASS | 233, including three new unit and five new PG tests |
| Native Gemini request/response | PASS | Actual loopback HTTP with fictional model, key and candidate; structured payload, header auth, current-facts recheck, saved review draft |
| Budget continuity | PASS | Existing count retained, separate approved cap enforced, concurrent last-slot claim has one winner, Cohere row unchanged, no refund |
| Durable Retry-After | PASS | Fixture429 records120 seconds; fresh connection rejects another call without reservation and returns remaining delay |
| Transport/grounding rejection | PASS | Redirect, oversize, truncated result, unsupported accomplishment and changed profile produce no saved draft; one consumed request per actual attempt |
| Pre-dispatch configuration/input checks | PASS | Disabled provider/data grant, zero approved cap, invalid model, oversized input and wrong fixture destination use no provider request or ledger reservation |
| Lock release after rejected reservation | PASS | Rejected caller remains open; next independent provider reservation completes within two seconds |
| Clippy / format / Ruff / diff | PASS | Workspace all-targets warnings denied; harness lint/format/diff clean |
| Actual Mac versus fixture | PASS | Rust HTTP and PostgreSQL17 ran natively on this Mac; all generated content and data fictional |
| Live model/account/browser/Telegram/application | NOT TESTED | No paid request, private prompt, owner DB, browser action, notification or submission |
| Whole-project resource/install/receipt acceptance | NOT TESTED | No new CPU/RSS/GPU comparison, installed cutover or genuine worker receipt |
| Complete provider/service migration | NOT TESTED | Local/CLI models and remaining PDF/storage/browser/application/Gmail/Telegram/services still open |
| Hosted Actions / merge | NOT TESTED | No dispatch or merge |

Initial validation exposed the lock hang above; only that disposable test process was
terminated and its harness stopped its own cluster. A focused rerun then had two passes
and three fixture assertion failures (two INT4/INT8 reads and one expected error-code name).
After correcting those expectations, all five focused cases and the complete final suites
passed. One new unit fixture initially lacked required claim references; its valid fixture
was corrected. No production data or configuration was changed by these corrections.

Reproduce:

```sh
CARGO_INCREMENTAL=0 cargo test --locked --workspace
CARGO_INCREMENTAL=0 uv run --no-project python rust/scripts/run_postgres_tests.py
CARGO_INCREMENTAL=0 uv run --no-project python rust/scripts/run_postgres_tests.py --filter gemini_
CARGO_INCREMENTAL=0 cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all --check
uv run --no-project ruff check --isolated --select E9,F,I rust/scripts/run_postgres_tests.py
git diff --check
```

No model SDK or second orchestration runtime was added. Response-size and connection
bounds remain explicit; no end-to-end speed gain is inferred from test duration. Continue
the [migration plan](../plans/2026-11-14-rust-agent-migration.md) through remaining service
ports and real installation/resource/focus/policy/identity/PDF/receipt acceptance.
