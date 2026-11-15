# Private runtime transport — qualified checkpoint

Branch `feat/rust-agent-runtime`; implementation
[`e841b7d0c9ab48e0504a41ac3f887046471bc034`](https://github.com/karanagg166/automated-apply/commit/e841b7d0c9ab48e0504a41ac3f887046471bc034),
[PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`.
The complete approved plan remains active and incomplete. This is internal milestone
acceptance, not installed production acceptance or an application success report.

The production configuration requires TLS while the MCP/native clients use numeric
loopback HTTP. The Rust host now optionally serves the same API over an owner-private
Unix socket. Kernel peer UID, bearer, origin and Host are checked independently; IPC
never asserts forwarded TLS. Ordinary TCP TLS enforcement is unchanged. Shared API
state, request permits and the existing DB connection preserve the connection ceiling.
MCP requires IPC with production TLS. Native forwarding and both Next.js gateways support
explicit sockets and never fall back to TCP after a configured socket failure. Native
Chrome command dispatch remains unported; this transport does not activate that service.

Paths must be canonical absolute, at most100 UTF-8 bytes, with owner-owned0700 parent and
0600 socket. The private parent protects initial creation; explicit chmod follows bind,
without changing the process-wide umask. Runtime locks precede socket binding. Recovery
requires a refused connection and matching socket inode; active/uncertain sockets and
replacement files/symlinks are retained. Shutdown removes only its own unchanged socket.
Locked external dependency versions/edges are unchanged; one internal workspace crate
shares filesystem checks. No duplicate build/release was created.

| Check | Result | Exact evidence / limits |
| --- | --- | --- |
| Full standard Rust workspace | PASS |177 passed,197 ignored PG cases; ignored cases are not passes |
| Actual Unix owner API and MCP stdio | PASS |2 disposable native PG cases,0.46s; includes protocol handshake/catalog/saved-job tool; one existing MCP case was changed to IPC |
| New filesystem/runtime/native/config regression cases | PASS |7 cases within the177, not additional; initial Unix mode mismatch corrected |
| Full frontend unit suite | PASS |317 tests /45 files,28.32s; includes8 IPC/gateway cases |
| Frontend typecheck / production build / formatting | PASS |`tsc`, Next production build and Prettier; not an installed dashboard check |
| Rust formatting / all-target Clippy | PASS |Clippy9.99s, warnings denied |
| Existing complete PG suite | NOT TESTED |This checkpoint ran the2 targeted cases; prior196-case PG baseline is qualified in its preceding report |
| Production service/account/browser changes | NOT TESTED |No installed service/config/profile/queue/provider or schema operation |
| CPU/RSS/latency comparison | NOT TESTED |Test durations are not performance/resource acceptance |
| Full plan / Rust installation / real receipts | BLOCKED |Remaining source ports and whole-family cutover/live gates remain open; pending owner browser login and missing strict worker receipt retained |

Sanitized initial failures: Rust borrowed-path type mismatch and fixture borrow lifetime
failed compilation; corrected. macOS socket modes differed from the umask assumption;
creation now uses private-parent protection and explicit0600 chmod, and5 filesystem/runtime
cases pass. A test used nonexistent `/status` and expected200, then used the actual
`/capabilities` route. MCP's literal private-config fixture initially stripped JSON quotes;
quoted values fixed it. Final targeted transport checks pass. No failed attempt sent a
provider request, touched owner browser tabs or created an application admission.

Reproduction from this checkout:

```sh
cargo test --locked --workspace
uv run --no-project python -m rust.scripts.run_postgres_tests --filter actual_mcp
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all --check
pnpm -C frontend exec vitest run
pnpm -C frontend typecheck
pnpm -C frontend build
pnpm -C frontend format:check
```

Private logs remain ignored under `.local/ipc-*`; they contain fictional test evidence.
Only this sanitized summary is published. No new UI screen was introduced. Continue
Gmail consent/account-generation/refresh fencing, remaining browser/execution/provider/
CLI/Telegram/Drive/platform ports, then the final sequential acceptance cycle, reviewed
STOP-mode whole-family migration, rollback, focus/restart/resource and real receipts.
No hosted Actions, merge, provider sending, recurring activation or data cleanup occurred.
