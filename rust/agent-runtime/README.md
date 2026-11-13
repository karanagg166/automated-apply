# Durable specialist-agent coordinator

This library is under development and is not installed in the owner's runtime.
It has five roles: discovery, matching, answers, review and execution. Each role has a
fixed tool subset and a fixed next-role transition. Model proposals are strictly typed,
can reference saved job IDs and observed evidence, and cannot supply a browser URL,
recipient, policy change, shell command, credentials or approval flag.

The coordinator persists model/input/output token reservations before inference, and
stable effect IDs before tool dispatch. Reserves survive a lost model response. Expired
read-only work can be retried within its original call budgets; interrupted external
writes become `outcome_unknown` and require reconciliation. Completion describes the
agent workflow, not proof of an application receipt. Submission remains explicitly
unavailable until its guarded adapter is migrated and accepted.

`Store` borrows one PostgreSQL connection. Claims use a transaction advisory lock and
one global active-lease constraint; CAS revisions and random lease tokens fence obsolete
workers. Run state and sanitized audit events update atomically. Context is private,
limited to16KiB/observation and64KiB/run, and never copied into the event table. The new
SQL tables use RLS with no client policies; public/anon/authenticated access is revoked.
Deployment must explicitly review application-role grants and existing target identity.
No process applies this SQL automatically or connects to the owner's database.

```sh
cargo test --locked --workspace
cargo clippy --locked --workspace --all-targets -- -D warnings
# PostgreSQL17 binaries are already available on this Mac; no Docker/service changes.
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
```

The dedicated harness starts and stops its own fictional localhost PostgreSQL cluster.
It compiles before startup, uses at most8connections and16MiBshared buffers, rejects
nonfixture database URLs, and never reads the project's env files. Default workspace
tests deliberately skip these integration cases; the dedicated harness runs them all.

The current end-to-end test uses scripted model proposals and simulated tool adapters.
Live provider consent, shared monthly usage/cooldowns, verified-context retrieval,
Telegram pairing, browser execution, queue admission, dashboard integration and real
receipt acceptance remain to be ported. Nothing in this library grants new submissions,
turns on recurring AUTOMATIC or starts Ollama/GPU inference.

Library references: [Tokio](https://docs.rs/tokio/latest/tokio/),
[SQLx PostgreSQL](https://docs.rs/sqlx/latest/sqlx/),
[Cargo profiles](https://doc.rust-lang.org/cargo/reference/profiles.html).
