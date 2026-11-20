# Dashboard application URL intake, 2026-11-21

Local source `37c8acaceeb7edd252beb2d312bc41df2ff36b58` on `feat/rust-agent-runtime` enables both existing dashboard URL forms on the Rust runtime. The Jobs form uses `POST /api/v1/application-packets/intake` and the Applications form uses `POST /api/v1/browser-applications`. The server applies the existing manual-page URL policy, binds the company and role to the selected URL, and saves a local draft. Pasted jobs retain their owner-selected provenance and unverified employer status. The intake transaction cannot advance the application queue or grant submission authority.

| Check | Result | Evidence |
| --- | --- | --- |
| Native draft, duplicate prevention and rollback | PASS | Two disposable PostgreSQL HTTP fixtures passed. Concurrent requests through two separate servers returned the same packet. The checks covered non-owner denials, disallowed destinations, conflicting company and role evidence, and rollback of a new company and job after a reused request key. Exactly one packet creation event was recorded, with zero submission evidence or Apply reservations. |
| Transaction isolation | PASS | The first run exposed that intake used read committed while the answer service required repeatable read. Intake now shares packet preparation's repeatable-read transaction and can retry a confirmed serialization rollback at the owner fence. |
| Dashboard intake form | PASS | 50 focused tests passed across three frontend files, including retry with the same request key after a lost response and a new key after editing the job. TypeScript, strict workspace Clippy and `git diff --check` passed. |
| Installed runtime and data | OBSERVED | 51 healthy API and dashboard observations through `2026-11-20T19:20:23Z`. macOS lock telemetry reported unlocked or unknown. Read-only database comparison matched the earlier 3,018 jobs, 35 packets and STOPPED queue revision 162 with zero active leases, three quarantined outcomes and three retained Apply reservations. |
| Combined release and live intake | PENDING | The installed services still run `d7d0484`. The new intake and earlier dashboard changes await the combined gate and local installation. The installed data checks did not create a live draft or dispatch an application. |

```sh
uv run --no-project python rust/scripts/run_postgres_tests.py --filter packet_intake_http --filter packet_flow_http_
cargo clippy --locked --workspace --all-targets -- -D warnings
pnpm -C frontend test tests/browser-assistant-improvements.test.tsx tests/applications.test.tsx tests/job-discovery.test.tsx
pnpm -C frontend typecheck
```
