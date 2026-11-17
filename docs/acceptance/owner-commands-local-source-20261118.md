# Owner commands and operation history

Local branch `feat/rust-agent-runtime`, implementation `437e7a15629c1530b831e7fda1bce111a680df0a`.

The Rust API serves the existing owner command and history routes. URL previews, saved filters, saved discovery status, policy and connection reads reuse existing services. The authenticated extension can request URL previews and connection status. Matching actor, request ID and input hash return the retained response. Concurrent attempts keep one receipt and the write checks that receipt before commit. History returns the latest 50 summaries with status, operation identifiers and receipt metadata. The database retains the original receipts.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source and formatting | PASS | Rust formatting, standalone fixture formatting and Git whitespace checks passed. |
| Loopback and PostgreSQL fixtures | NOT TESTED | Two additions cover actor authentication, request conflicts, history redaction, concurrent receipt arbitration and late trigger drift. |
| Current build and combined run | NOT TESTED | Zero tests executed for this checkpoint. The last validated baseline remains `9c4ace570535a5856184775f8045ee89eafdd05f` with 193 standard Rust and 262 disposable PostgreSQL passes. |
| Live operation | NOT TESTED | Installed services, portal accounts, queue and provider budgets were untouched. |

Include `uv run --no-project python rust/scripts/run_postgres_tests.py` in the combined local gate. The new history projection omits URL and text payloads when listing receipts. The exact preview response remains available to the authenticated original caller through its matching request. The estimate stays at 58% complete and 42% remaining while new source awaits validation.

The platform source audit found a shared preparation gap. The saved-job tool covers all eight requested platforms. The packet selector currently recognizes only Naukri from that list. The two public feed ingestion paths retain destination links but cannot yet pass that selector. Continue with platform-specific packet preparation and the remaining adapter work before the combined gate. See the [completion plan](../plans/completion-execution-20261116.md).
