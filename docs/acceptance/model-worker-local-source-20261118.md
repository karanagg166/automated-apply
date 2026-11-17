# Independent scheduling during Cohere planning

Local branch `feat/rust-agent-runtime`, implementation `b74e107ccfe6c6b4fbbcf13c4e32382f844f08e6`.

The configured planner saves its model intent and shared monthly reservation before the HTTP request. Only the bounded provider transport runs in a separate task. The worker retains its single PostgreSQL connection for application scheduling, public feed intake, and heartbeats. Permit contention defers the decision without charging the run. Accepted responses account for provider usage and pass the existing planner role checks before the leased run can change.

The worker can cancel the request after a matching run control, global control change, or shutdown. A consumed reservation stays charged. Late responses cannot save to a changed or expired lease. Local tool execution and persistence still use the worker connection.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source formatting and whitespace | PASS | Rust formatting and Git whitespace checks completed. |
| Disposable PostgreSQL and actual fixture process | NOT TESTED | New case holds the first loopback Cohere response, checks durable run/monthly reservations and a later heartbeat, then resumes the existing approval workflow. |
| Runner cancellation and provider policy | NOT TESTED | Existing suites cover interruption, role restrictions, budgets, accounting, and compatibility. |
| Current combined gate | NOT TESTED | Zero tests executed for this checkpoint. Prior baseline `9c4ace570535a5856184775f8045ee89eafdd05f` had 193 standard Rust and 262 disposable PostgreSQL passes. |
| Actual installed behavior | NOT TESTED | No provider, production database, browser, or application calls took place. No latency or resource measurement is claimed. |

Include the locked Rust workspace and `uv run --no-project python rust/scripts/run_postgres_tests.py` in the combined local run. The estimate remains 58% complete. Provider-specific application acceptance and final installation remain open.
