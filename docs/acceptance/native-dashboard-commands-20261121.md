# Native dashboard owner commands

Local implementation `bb05b2bd377976b345b5ab2f8ebc1ccc68f10698` on
`feat/rust-agent-runtime` restores the Agent page command box on Rust. It
searches saved jobs, resolves a numbered selection and prepares a draft with
a link to the packet. The deterministic interpreter uses the existing
saved-data services and a separate dashboard selection. Python retains its
campaign entry point.

| Check | Result | Evidence |
| --- | --- | --- |
| Dashboard HTTP workflow | PASS | One new disposable PostgreSQL fixture covered owner authentication, origin and browser-extension rejection, search, draft creation, reset and duplicate requests across two servers. |
| Atomic receipt and retained authority | PASS | A fixture trigger suppressed the receipt and the transaction rolled back selection and draft. After removing the trigger, two requests returned one receipt and one unapproved packet. The queue remained STOPPED, Telegram selection matched exactly and the fixture retained zero submission records and Apply reservations. |
| Focused compatibility | PASS | 13 PostgreSQL tests passed across dashboard commands, local owner commands, Telegram and conversation memory. |
| Frontend and contracts | PASS | All 12 tests across Agent, Submission Review and Browser Plans passed. TypeScript, strict workspace Clippy, Rust formatting, HTTP policy drift and Git diff checks passed. |
| Installed runtime sample | OBSERVED | The existing `d7d0484` release returned four HTTP 200 results in 54 observations through `2026-11-20T19:29:29Z`. Sampling saw 51 unlocked, two unknown and one locked screen state. Passive Brave inspection found the owned extension worker and zero page targets. |
| Combined release and live dashboard command | PENDING | Updated source awaits the combined release gate, local installation and live command verification. The first supervised Naukri receipt awaits the signed-in dedicated Brave profile. |

```sh
uv run --no-project --python .venv/bin/python python rust/scripts/run_postgres_tests.py --filter dashboard_commands --filter owner_commands --filter conversation_memory --filter telegram_local
pnpm -C frontend test tests/agent.test.tsx tests/submission-review.test.tsx tests/browser-plans.test.tsx
pnpm -C frontend typecheck
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
uv run --no-project python scripts/sync_http_security.py --check
```
