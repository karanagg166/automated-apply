# Native project evidence build, 2026-11-20

Source `56317e0512d4650be9b6922c9a3ec312288f56a3` on `feat/rust-agent-runtime` restores the candidate-context Build action. It reads configured Markdown templates and regular Git blobs from an explicitly mapped local checkout. It checks the checkout origin, pins one Git commit and derives bounded, attributed facts. A build creates pending evidence for owner review. Existing approvals, history and application authority retain their original checks. [Candidate-context setup and review](candidate-context-dashboard-20261120.md)

The runtime releases its database connection before reading evidence. It reacquires the owner fence and compares the configuration and project records before saving. An unrelated Git commit updates the last-checked commit and preserves the pending candidate's existing revision. Relevant source changes create a fresh candidate and retain the prior approval for review.

| Check | Result | Evidence |
| --- | --- | --- |
| Markdown template build and review | PASS | The authenticated disposable PostgreSQL fixture built owner-supplied facts with file hashes and references, approved the selected fact, and required fresh review after the template changed. It refused aliases, missing frontmatter delimiters and a symlinked intermediate directory. |
| Local Git build and provenance | PASS | The fixture read a committed file over its modified worktree version, attributed TOML and source imports, kept README prose inferred, rejected an unlisted repository and a changed origin, and distinguished unrelated commits from evidence changes. |
| Concurrent configuration change | PASS | The fixture waited for Build to reach the persistence fence, verified that readiness still returned 200, changed the configuration, then verified a 409 and identical saved project evidence. The first assertion timed out because its observer used the transaction holding the lock. The passing fixture uses a separate connection to observe the wait. |
| Focused verification | PASS | All three candidate-context HTTP fixtures passed in 0.79 s on disposable PostgreSQL. Strict Clippy for all workspace targets, Rust formatting and `git diff --check` passed. |
| Live source configuration | OBSERVED | A read-only database check found four named projects, three repository-backed projects, zero projects with template paths and four retained knowledge records. The installed runtime has no configured checkout mappings or template root. |
| Combined validation and installed Build | PENDING | The installed runtime still runs `d7d0484`. Live Build requires the next combined release and configured local sources. |
| Runtime observation and Naukri | IN PROGRESS / BLOCKED | Eleven healthy unlocked observations through `2026-11-20T17:19:19Z` on the same Rust and dashboard PIDs. The last passive probe still showed zero page targets in the dedicated Brave profile. |

```sh
cargo fmt --all -- --check
rustfmt --edition 2024 --check rust/agent-runtime/tests/support/dashboard_candidate_context_pg.rs
uv run --no-project --python .venv/bin/python python rust/scripts/run_postgres_tests.py --filter dashboard_candidate_context_
cargo clippy --locked --workspace --all-targets -- -D warnings
```

The Build fixtures used fictional sources. No live repository build, periodic evidence refresh, application admission or production performance comparison was measured in this batch. Runtime source configuration is documented with the existing operator setup. [Rust configuration](../../rust/README.md)
