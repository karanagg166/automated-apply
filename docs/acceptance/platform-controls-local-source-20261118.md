# Platform policy and portal session controls

Local branch `feat/rust-agent-runtime`, policy source `efb52e08852f9a57bca593d96f2b04d3b2060ad1` and portal session source `3da66f29e48b64a3a8ac3a1786d0989039d73cad`.

The existing dashboard policy route uses the saved version and writes one audit event for each accepted update. The policy and history row are checked together before commit. Browser fills, execution and Telegram previews read the same saved policy with the existing defaults. Dashboard users can list supported portal indicators, accept manual handoff and forget a saved indicator. The native extension can record a gesture observation and replay its result without restoring forgotten evidence. These observations record limited browser evidence. Identity, API connection and submission remain unverified.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source and formatting | PASS | `cargo fmt --all`, fixture formatting and `git diff --check` passed. |
| Policy route and event rollback | NOT TESTED | Two new disposable PostgreSQL fixtures cover stale edits, fixed preferences, extension denial, shared Telegram policy and late trigger drift. |
| Portal route, replay and rollback | NOT TESTED | Two new disposable PostgreSQL fixtures cover manual acceptance, clearing evidence, authenticated native observation, conflicting request IDs and late trigger drift. |
| Combined tests, deployment and resource measurements | NOT TESTED | Zero tests executed for these commits. Current browser and installed services were untouched. |
| Actual account and application acceptance | NOT TESTED | No provider calls, new application admissions, local install or queue change. The last recorded strict Naukri receipt count remains zero. |

Run the new fixtures through `uv run --no-project python rust/scripts/run_postgres_tests.py` at the combined local gate. The last validated baseline remains `9c4ace570535a5856184775f8045ee89eafdd05f`, with 193 standard Rust passes and 262 dedicated PostgreSQL passes. The estimate remains 58% complete and 42% remaining while this source awaits validation.

Continue with the dashboard connection report and remaining owner command and history routes, then reconcile the platform adapter coverage with the saved plan. Keep all code, validation and evidence on the owner’s laptop.
