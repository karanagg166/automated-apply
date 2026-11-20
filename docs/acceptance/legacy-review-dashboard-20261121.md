# Saved campaign and browser review, 2026-11-21

Local source `265de1925bd94abeaad03e07cdf3f681b7c98cfb` on `feat/rust-agent-runtime` restores owner reads for campaign list and detail, agent status, submission history, and browser review and operation status for a saved application packet. The routes use the existing retained PostgreSQL records. The Agent page links to the native Workflow and displays the native worker's actual mode. The Rust dashboard's legacy history views are read-only. Python retains its existing command, fixture submission and isolated-browser controls.

| Check | Result | Evidence |
| --- | --- | --- |
| Saved history and authentication | PASS | One disposable PostgreSQL HTTP fixture covered all six reads. It verified bearer authentication, denial of extension clients, the GET-only boundary, compound identity validation, the shared Cohere ledger, retained uncertain submission state and zero new receipts. |
| Dashboard | PASS | 18 focused frontend tests passed across four files. TypeScript passed. Tests exercised native workflow navigation, saved browser history without an executor, and separate legacy UI controls. |
| Source and combined test plan | PASS | Strict workspace Clippy, saved DTO contract drift check and `git diff --check` passed. The local plan includes a 37th stage for campaign and submission contract drift. |
| Combined release and live dashboard | PENDING | The installed release is still `d7d0484`. No new production release was activated in this batch. Manual URL intake and legacy executor mutations require separate coverage. |
| Installed runtime and queue | OBSERVED | 47 of 47 unlocked samples were healthy through `2026-11-20T19:08:17Z`. An independent read-only database comparison matched the earlier 3,018 jobs, 35 packets, queue STOPPED revision 162, zero active leases, three quarantined outcomes and three Apply reservations. The 24-hour observation remains in progress. |
| Fourth supervised Naukri attempt | BLOCKED | The dedicated Brave profile had zero page targets. The project MCP reported that fresh account binding, extension and focus verification are required. |

```sh
uv run --no-project python -m rust.scripts.export_review_contracts
uv run --no-project python rust/scripts/run_postgres_tests.py --filter legacy_review_http
cargo clippy --locked --workspace --all-targets -- -D warnings
pnpm -C frontend test tests/agent.test.tsx tests/submission-review.test.tsx tests/browser-assistant-improvements.test.tsx tests/discover.test.tsx
pnpm -C frontend typecheck
```

The test gate used fictional data. The live comparisons were read-only and contain no measured application dispatch, provider activity or performance improvement. [Installed runtime report](local-rust-recovery-20261120.md)
