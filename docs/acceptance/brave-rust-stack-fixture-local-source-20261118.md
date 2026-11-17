# Combined Brave and Rust acceptance fixture

Local branch `feat/rust-agent-runtime`, implementation `b8180c625dfc05a183893655173a11c833fa0e7e`.

The combined gate now schedules the disposable PostgreSQL suite after the Brave build and includes a headless browser fixture. The fixture connects the built extension to the real Rust native host and Rust HTTP API. It checks owner profile selection, STOPPED queue status, refusal to Start with commands disabled, and persistence of a scoped observation from a fictional portal page. The fixture uses a temporary profile, a unique native host name, loopback API, and disposable data.

| Gate | Status | Evidence |
| --- | --- | --- |
| Combined plan ordering | PASS | The plan lists 32 stages, builds Brave before the native PostgreSQL stage, and explicitly includes the browser fixture. |
| Source and formatting | PASS | Rust formatting, extension Prettier and Git whitespace checks completed. |
| Actual browser fixture and orchestrator test | NOT TESTED | The new fixture and stage-order guard await the combined run. The existing standalone PostgreSQL harness excludes the browser case unless explicitly selected with the browser option. |
| Installed profile, focus and Naukri application | NOT TESTED | No production browser, credential, database or application was used. |

The combined entry point is `uv run --no-project python scripts/run_acceptance.py --run`. It retains the existing legacy and frontend browser stages. The engineering estimate remains 58% complete. This addition covers Rust browser integration during the fixture phase. The installed runtime and live receipt still need independent acceptance.
