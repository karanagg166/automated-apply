# Packet preparation contracts, destinations and transactional fields — 2026-11-15

Implementation [`0171faddbca9613c6390b125e9323ffae2869336`](https://github.com/karanagg166/automated-apply/commit/0171faddbca9613c6390b125e9323ffae2869336),
branch `feat/rust-agent-runtime`, [draft PR #50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling`.

The Rust preparation foundation now validates owner questions and idempotency inputs,
evaluates the existing platform destination rules locally, and assembles checklist fields
from saved facts. Inputs cannot provide candidate identity, snapshots, provenance or
approval. Narrative drafts remain explicit; an upload field retains manual-upload status.
ATS recognition remains separate from a browser origin grant or submission authorization.

The new internal factual resolver uses the packet caller's PostgreSQL transaction. It
does not commit, save narrative drafts or dispatch inference. An actual disposable native
PostgreSQL test observes a missing question inside that transaction, sees none from a
second connection, forces a later SQL failure, and verifies rollback preserves the profile,
draft inventory and zero inference usage. Another test checks all five narrative categories
and an upload field produce no draft, missing question, packet or model call implicitly.

| Check | Result | Evidence and limits |
| --- | --- | --- |
| Request contracts | PASS | 237 actual Python DTO comparisons inside one Rust test; extra trust fields, bounds, coercion, UUIDs, Unicode options and duplicate choices |
| Destination rules | PASS | 4,968 comparisons against actual AST-extracted adapter definitions, 132 deduplicated outputs; all ten registry entries, exact ATS identities, source conflicts, expiry and explicit fixture/origin policies |
| Field mapping | PASS | 3,240 comparisons against the actual builder with an injected fictional answer service, 200 deduplicated outputs; all core fields, absent profile, public/private resumes, option/length constraints, provenance and unknown provider rejection |
| Transaction boundaries | PASS | Two new native PostgreSQL tests; no independent answer-service commit or implicit narrative/attachment authority |
| Rust workspace | PASS | Fresh 133 standard tests, zero failures; the initial standard command ignored the then-existing 140 PostgreSQL tests |
| PostgreSQL suite | PASS | Fresh 142 passed, zero failed or ignored, in 34.15s after the two new cases were added |
| Combined verified Rust tests | PASS | 275 distinct tests: 133 standard + 142 native PostgreSQL; oracle comparisons are not counted as extra tests |
| Clippy / Cargo format / whitespace | PASS | Workspace all targets, warnings denied; final Clippy 3.54s |
| Oracle reproducibility / Ruff | PASS | Three exporters `--check`, E9/F/I; AST-only imports explicitly reject loading runtime settings or ORM |
| Packet context, creation/replay and seven HTTP routes | NOT TESTED / incomplete | This foundation is not a completed packet service; the material context, persistence and endpoint integration remain next |
| Installed application / real submissions | NOT TESTED | No new install, production query/write, provider request, browser action, application or receipt in this milestone |
| Whole-system Mac performance | NOT TESTED | Standard test-body times sum to 5.94s; these unpaired fixture timings do not establish CPU/RSS/GPU or installed latency improvements |
| Existing live browser prerequisite | BLOCKED / unchanged | Retained handoff requires the owner's physical profile-open/sign-in step; this work did not infer it occurred |

No new dependency, connection pool, source worktree or release copy was created. All work
uses the canonical repository and its existing build directory. Hosted workflows remain
manual-only. Installed legacy API/execution `8e985c9`, STOP revision162, supervised4/hourly1,
three quarantined uncertain applications and the first strict worker-receipt gate were not
changed. No whole-migration completion or merge approval is claimed.

Sanitized failure codes enforced here include `invalid_packet_preparation`,
`invalid_packet_field_record` and `packet_explicit_generation_required`. Raw fictional
test logs remain in ignored canonical `.local/`; no owner data or private logs are published.

```sh
uv run --no-project --python .venv/bin/python python -m rust.scripts.packet_contract_corpus --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.packet_platform_corpus --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.packet_fields_corpus --check
uv run --no-project ruff check --isolated --select E9,F,I rust/scripts/packet_contract_corpus.py rust/scripts/packet_platform_corpus.py rust/scripts/packet_fields_corpus.py
cargo test --locked --workspace
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
git diff --check
```

Continue the [complete seven-route packet slice](../plans/application-packet-rust-slice.md):
material-context fingerprints, current snapshot construction, atomic creation/idempotent
replay, shared-lock reads, readiness lifecycle overrides, list/events and owner-only HTTP
integration. Preserve Python Decimal/datetime digest representations, explicit resume
selection and immutable audit/worker guards. Full runtime, live and measured installed
acceptance remain required.
