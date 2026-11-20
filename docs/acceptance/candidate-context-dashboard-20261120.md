# Native candidate context dashboard, 2026-11-20

Follow-up source and tests now cover the Build action. [Native project evidence build report](candidate-context-build-20261120.md)

Source `26b555f7cb78661aeeb6af622ac523db6b235859` on `feat/rust-agent-runtime` restores six candidate-context operations in the Rust owner API. The source uses the existing configuration and project records, frozen validation schemas and approved-answer generator. Configuration saves retain revision checks and content hashes. Project approval requires explicit confirmation and accepts only evidence from the current candidate revision. A changed project configuration makes an earlier approval ineligible for new answers and preserves its saved history.

| Check | Result | Evidence |
| --- | --- | --- |
| Authenticated configuration, project list and detail, approval and answer flow | PASS | One disposable PostgreSQL HTTP regression covered all six operations. It verified the initial defaults, extension denial, method enforcement, deferred Drive sync, stale writes, inferred-fact refusal, duplicate approvals, retained prior approval, and citations to current reviewed evidence. |
| Answer query routing | PASS | The first fixture failed because the global route guard rejected the answer query. The correction admits that exact GET route to its own bounded query parser. The rerun accepted a valid question and rejected duplicate parameters. |
| Source hygiene | PASS | Workspace Rust formatting, formatting of the new included fixture, `git diff --check` and strict Clippy for all workspace targets passed. |
| Build new project evidence | NOT IMPLEMENTED | The existing Rust review flow can approve an already stored candidate. The project Build action still needs native readers for authorized local Git checkouts and template files. The installed Rust configuration currently supplies neither of those settings. |
| Combined release and live dashboard verification | PENDING | This source and the preceding Discover fix await the next clean combined acceptance and local installation. The installed services still run `d7d0484`. |
| Runtime observation | IN PROGRESS | Six healthy unlocked samples through `2026-11-20T17:04:11Z`. The runtime and dashboard PIDs stayed the same across these samples. Locked and elapsed 24-hour evidence is pending. |
| Fourth supervised Naukri admission and first strict receipt | BLOCKED | A fresh passive probe showed zero page targets in the dedicated Brave profile. This block remains separate from candidate-context source work. |

```sh
cargo fmt --all -- --check
rustfmt --edition 2024 --check rust/agent-runtime/tests/support/dashboard_candidate_context_pg.rs
uv run --no-project --python .venv/bin/python python rust/scripts/run_postgres_tests.py --filter dashboard_candidate_context_keeps_configuration_and_approval_bound
cargo clippy --locked --workspace --all-targets -- -D warnings
```

The fixture used fictional evidence and has no measured production timing or resource comparison. Current runtime, queue and rollback evidence remains in the [installed release report](local-rust-recovery-20261120.md).
