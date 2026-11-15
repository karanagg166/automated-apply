# Explicit Rust packet generation — 2026-11-15

Implementation [`7538875b9b0018e4b1095b589d2d7beeb6b85f88`](https://github.com/karanagg166/automated-apply/commit/7538875b9b0018e4b1095b589d2d7beeb6b85f88),
branch `feat/rust-agent-runtime`, [draft PR50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling`. Extends the [packet edits](rust-packet-edits-20261115.md).

POST `/api/v1/application-packets/{packet}/questions/{field}/generate` now performs
explicit grounded drafting in Rust. Closed input permits only expected revision and
optional rewrite; it cannot inject answers, provider settings or approval. A consistent
preflight checks packet, field, saved profile/material and multiple-selection capability.
It ends before the existing grounded answer service reserves/calls a model. The bounded
generation connection and shared request/model permit keep ordinary owner controls and
edits available during inference.

After drafting, a fresh packet/material claim checks revision, context digest and exact
original field before archive/CAS/field/event commit. A concurrent owner edit wins. A
saved grounded draft may remain unattached after a rejected packet update, matching the
existing answer lifecycle. Consumed model requests and cooldowns are never refunded.
One confirmed post-model packet serialization rollback can retry the packet transaction
using the same prepared result; inference is not reissued. Unknown outcomes remain
unknown. Manual uploads stay manual, environmental defaults remain unconfirmed, and
generated fields always require applicable review; no approval or receipt is created.

| Acceptance | Result | Exact evidence / limits |
| --- | --- | --- |
| Full standard Rust suite | PASS | **141 passed,0 failed,164 ignored PG cases**,10.58s sum of test bodies |
| Full native disposable PostgreSQL suite | PASS | **164 passed,0 failed,0 ignored**,38.56s test body |
| Distinct executed tests | PASS | **305**; suites are disjoint |
| New actual Python builder/input oracles | PASS | 7,128 explicit-generation mappings across rewrite modes and19 request DTO cases inside two tests; cases are not extra test counts |
| Six new native PG cases | PASS | Actual owner HTTP extractive drafting/upload gates; bounded loopback model success/concurrent profile correction; provider429 cooldown; responsive STOP and owner edit during inference; failed packet write retains model request/draft; post-model serialization retries only packet transaction |
| Existing preparation oracle | PASS | 3,240 fixture cases unchanged after sharing the explicit/non-explicit mapping implementation |
| All-target Clippy | PASS | `-D warnings`,4.54s |
| Format/diff/Ruff/new and existing oracle drift | PASS | Commands below |
| Live commercial/local model calls with owner key | NOT TESTED | Model tests use actual loopback HTTP with fictional credentials and attributed fictional facts; no real provider request in this milestone |
| Actual Mac platform/account/application behavior | NOT TESTED | No browser, owner database, account creation or submission action here |
| Physical browser/account handoff | BLOCKED | Separate retained owner unlock/profile-open or Brave sign-in step remains pending |
| Installed Rust / full production role grants | NOT TESTED | No installation/migration; packet guard fixtures are not the full production grants/RLS matrix |
| Whole-system CPU/RSS/GPU/latency improvement | NOT TESTED | Test times are not a Python/Rust resource comparison |
| Full autonomous multi-platform project | FAIL | Remaining acceptance below; no100% claim |

Sanitized failure evidence: changed saved profile after the model call returns
`packet_context_changed` without applying its result. An owner answer saved while the
model waits advances the packet; the later generation returns409 and preserves that
owner answer. Parallel generation returns429 while STOP remains responsive and no API
connection stays idle in a transaction. Provider429 causes exactly one request and
retains its cooldown/count. Injected packet event failure returns `packet_database_error`
with the preceding packet/history/archive intact, while its already-saved draft and
consumed request remain. Injected SQLSTATE40001 retries the packet once and still records
exactly one model call, one draft, one prior revision archive and one generated event.

```sh
cargo test --locked --workspace
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
git diff --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.packet_generation_corpus --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.packet_fields_corpus --check
uv run --no-project ruff check --isolated --select E9,F,I rust/scripts/packet_generation_corpus.py rust/scripts/packet_fields_corpus.py rust/scripts/packet_contract_corpus.py
```

Ignored logs: `.local/rust-packet-generation-{full,all-pg,clippy}.log`; focused six-case
native run passed in1.12s. Python is used only for isolated test oracles/harness, not the
runtime route. No dependency or production schema change in this milestone.

Next finish exact human packet review/approval with execution-owner fencing and
transactional notifications, manual handoff/outcomes/tracking, browser intake/worker,
Gmail/Drive/legacy Telegram/CLI/fallback/rearranger/AGY, and native adapters/accounts for
the [expanded platforms](../plans/expanded-platforms-20261115.md). Require actual employer
receipts, installed STOP/rollback/focus and resource comparisons before full acceptance.
Retain STOPPED162, supervised4/hourly1, three uncertain jobs and zero strict worker
receipts from the operational handoff; these were not freshly sampled or changed here.
No hosted Actions, merge, cleanup, new source/build copy or external message occurred.
