# Dashboard connection report

Local branch `feat/rust-agent-runtime`, implementation `8d6acf369065eeef3e9f44470766ab4f030dd16a`.

The Rust owner API serves the existing dashboard connections endpoint. The read-only query reports the current database and API request, saved browser and portal evidence, Telegram poll and receipt metadata, version-bound profile review, local PDF integrity, saved Gmail evidence and provider configuration. The dashboard uses the selected browser language and shows provider cost separately from connection status. The optional `RUST_CONNECTION_EVIDENCE_DIR` setting lets the report use existing owner-only CLI and MCP receipts as historical evidence.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source and formatting | PASS | Rust formatting, dashboard Prettier formatting and the Git whitespace check passed. |
| Loopback and PostgreSQL fixtures | NOT TESTED | Two additions cover authorization, reads while the owner fence is held, stale evidence, PDF mismatch, metadata redaction and safe handling of private receipt files. |
| Current build and combined run | NOT TESTED | Zero tests executed for this checkpoint. The last validated baseline remains `9c4ace570535a5856184775f8045ee89eafdd05f` with 193 standard Rust and 262 disposable PostgreSQL passes. |
| Live Mac, Telegram, browser and provider acceptance | NOT TESTED | Installed services and queue controls were untouched. Current code uses passive evidence and no provider calls. |
| Timing and memory | NOT TESTED | The snapshot reuses the owner connection and bounds receipt files, the Telegram receipt lookup and the local PDF read. Measurement remains part of the combined gate. |

Include `uv run --no-project python rust/scripts/run_postgres_tests.py` and the existing frontend connection view tests in the combined gate. Local installation needs explicit selection of the historical receipt directory if those receipts are to be shown. The engineering estimate stays at 58% complete and 42% remaining while the new source awaits validation. Continue the owner command and history routes, then reconcile the platform adapter coverage with the saved plan.
