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
Browser manifests may also point directly to the Rust executable. In that mode the
browser supplies the extension origin and the executable reads only its adjacent
`automated-apply-native.private.env` file. This file must be owner-owned, regular,
private and contain the existing explicit native endpoint/token/extension settings.
No shell wrapper, ambient environment or current-directory configuration is needed.
Operating-system file permissions still apply to the executable and private file.
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
Optional Cohere/Gemini generation shares the existing monthly usage ledger and bounded model
concurrency with the graph agents. It makes one request per reservation, releases read
locks before inference, rechecks evidence before saving, and cannot submit applications.
One transient generation connection keeps owner controls responsive; no database pool is
added. Gemini also requires its separate approved monthly request count and candidate-data
grant; it accepts one complete text-only structured result and never follows generated tools.
Explicit `LLM_PROVIDER=ollama` with `OLLAMA_ENABLED=true` now uses the existing optional
provider ledger (`owner_preferences`, `ai:ollama:YYYY-MM`), including consumed requests,
cooldowns and unknown retained fields. It never silently selects a model, starts a daemon,
pulls weights or falls back to a remote service. The production endpoint is fixed to
`http://127.0.0.1:11434`; fixture overrides work only in explicit fictional mode.
Before candidate text, `/api/status` must report `cloud.disabled=true` and `/api/show`
must contain local model metadata without remote routing. Older daemons fail closed.
The request asks for two threads, a 2,048-token context, at most 256 output tokens and
`keep_alive=0`; these are daemon options, not measured resource guarantees. The serialized
request is capped at 5,000 bytes and responses at 128KiB. A shared transport deadline
bounds metadata and generation together. Incomplete results are rejected rather than
continued. The runtime shares one generation permit with graph inference; operators
must also enforce `OLLAMA_NUM_PARALLEL=1` for any other daemon clients.
No real Ollama generation has been accepted yet. The separate legacy
`OLLAMA_GENERATION_AUTHORIZED` rearranger, local fallback and CLI/application service
ports remain in progress; this port implements the explicitly enabled optional structured
draft path. Conservative grounding, context rechecks and owner review still apply.

The private dashboard notification inbox, mark-read receipts and saved delivery history
also run directly on the existing PostgreSQL connection. They retain fixed50/100-row
pages, private field projections and commit-before-ACK read receipts, with no delivery
dispatch or application authority. Notification preferences and synchronization remain
on the legacy path until their separate ports are complete.
