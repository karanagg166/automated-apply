# Scheduled public feeds and the application worker

Local branch `feat/rust-agent-runtime`, implementation `adca6e9cf9077d13f295a6776707a60206b5cb03`.

The worker reserves each scheduled feed fetch on its existing PostgreSQL connection. The HTTPS fetch runs in one tracked network task. The worker can use its connection for heartbeats and application preparation while the task waits. The scheduler processes cache and intake when the worker next reaches a database boundary. Feed work uses no additional PostgreSQL session.

A global control change can cancel the network wait. The durable reservation and provider cooldown survive cancellation. If a completed fetch returns after a Stop and Resume, the ingestion transaction compares the original control and schedule revisions under the corresponding database locks. A subsequent tick can reuse the completed cache under the current revisions. Feed intake cannot dispatch applications.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source formatting and whitespace | PASS | Rust formatting and Git whitespace checks completed. |
| Disposable PostgreSQL | NOT TESTED | One new fixture covers connection reuse between reservation and completion, duplicate reservation prevention, stale control authority and cache reuse after Resume. Existing cases cover stopped and revised intake authority. |
| Worker cancellation and timing | NOT TESTED | Existing cancellation fixtures cover matching and unrelated control notifications. No live Stop latency or throughput measurements were taken. |
| Current combined gate | NOT TESTED | Zero tests executed for this checkpoint. Prior baseline `9c4ace570535a5856184775f8045ee89eafdd05f` had 193 standard Rust and 262 disposable PostgreSQL passes. |
| Live operational acceptance | NOT TESTED | The worker was not installed or started. No real feed, provider, browser or application operation ran. |

Include `uv run --no-project python rust/scripts/run_postgres_tests.py` and the worker cancellation cases in the combined suite. Engineering estimate remains 58% complete. Model-step waits can still delay worker database boundaries. Provider-side discovery, account proof and the first Naukri strict worker receipt still need acceptance.
