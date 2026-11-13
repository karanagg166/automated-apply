# Rust migration

This workspace replaces Python components incrementally. It is not yet the production
backend. See [the migration plan](../docs/plans/2026-11-14-rust-agent-migration.md).

```sh
cargo test --locked --workspace
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
