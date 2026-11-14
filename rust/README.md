# Rust migration

This workspace replaces Python components incrementally. It is not yet the production
backend. See [the migration plan](../docs/plans/2026-11-14-rust-agent-migration.md).

Develop and build from the canonical repository only. Local runtime data and preserved
private evidence live under ignored `.local/`; the old Library path is a compatibility
symlink. See [storage evidence](../docs/acceptance/storage-cleanup-20261115.md).

```sh
cargo test --locked --workspace
uv run --no-project python rust/scripts/run_postgres_tests.py
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo build --locked --release --workspace
```

`automated-apply-native /absolute/private.env chrome-extension://<stable-extension-id>/`
reads one length-prefixed Chrome frame and returns one frame. It uses the existing
loopback backend contract. It does not open tabs, start local inference or submit jobs.
The public command schema is generated from current Python contracts; check it with:

```sh
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r backend/requirements-runtime.txt
uv run --no-project --python .venv/bin/python python -m rust.scripts.export_native_schema --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.benchmark_native --iterations 20
```

The Rust host reads only its explicit private env file (no ambient configuration override),
requires a regular owner-owned file with no group/other access, refuses symlinks, and
accepts only a numeric IPv4 loopback HTTP endpoint with a port. Remote proxies,
redirects and network schema retrieval are disabled. JSON schema validation is stricter
than Python coercion; valid typed extension requests are the compatibility target.
Cross-field Python validators remain authoritative until their Rust ports are complete.
Never swap the installed native wrapper without STOP, immutable release/rollback
inventory and account/policy/history/readiness acceptance.

The agent host includes direct factual answers, deterministic grounded extraction,
reviewable saved drafts, signed exact-context owner answers and scoped reusable answers.
Optional Cohere generation shares the existing monthly usage ledger and bounded model
concurrency with the graph agents. It makes one request per reservation, releases read
locks before inference, rechecks evidence before saving, and cannot submit applications.
One transient generation connection keeps owner controls responsive; no database pool is
added. Other provider and application service ports remain in progress.
