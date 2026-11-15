# Native browser command broker — qualified acceptance

Branch `feat/rust-agent-runtime`; implementation
[`35cf48e38db12c88333abc781a6afa086506bec3`](https://github.com/karanagg166/automated-apply/commit/35cf48e38db12c88333abc781a6afa086506bec3),
[PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`.
This extends the [profile lifecycle checkpoint](native-browser-profiles-20261116.md).
The approved full plan remains in progress; no installation or real application is claimed.

The existing owner enqueue and native poll/start/ack paths now run in Rust. Inputs preserve
the Python declaration-order idempotency hash, UUID normalization, bounded revisions and
five existing actions. A duplicate request returns its original command, including terminal
or unknown state. One selected live, opted-in profile can lease one command; concurrent
pollers cannot deliver it twice. Leased/executing commands never return to queued after
expiry or a session/profile change. Acknowledgement records only command completion,
failure or uncertainty, with `submitted=false`; it is not an application receipt.

Enqueue/start reread the confirmed candidate, locked current packet/material, destination,
eligible job, automation mode and platform policy. Retained receipt keys block replay even
when their evidence is damaged; uncertain historical packets also match alternate URL
slugs with the same requisition. A quarantined original admission cannot be reopened.
No quota, identity/resume or first-receipt requirement is relaxed. Start checks liveness
and lease expiry again after material lock waits. The regression holds a real job row
past lease expiry and proves that the command becomes unknown rather than executing.

Owner enqueue's offline denial commits old-authority revocation before returning. Failed
lease writes finish rollback without delivering a command. All mutation acknowledgements
remain checked; no automatic unknown-write replay is introduced. The existing native
binary is exercised through actual framed stdin/stdout against a Rust localhost HTTP host
for poll, start and acknowledgement. This is a fictional Mac process/transport fixture,
not a real browser interaction or installed extension/application validation.

Status now uses one coherent SQL statement without the execution owner lock for the normal
read. Only required expiry/offline revocation reacquires that lock and rereads state.
Live inventory excludes closed history, and commands/receipts stay limited to30 records.
A regression retains10,001 completed commands plus10,001 terminal tasks while dispatch,
status and restart revocation continue. Another holds the owner row locked and verifies
ordinary status still succeeds with a100ms database lock timeout. These are source/query
and functional contention results; no whole-runtime CPU/RSS/latency gain is asserted.

Explicit browser fixtures can select only their exact numeric-loopback HTTP origin under
both testing environment and Rust fixture mode. Production, credentials, DNS aliases,
paths/queries in the origin, alternate origins and HTTPS fixture origins are refused.
Ordinary production destinations still use the existing verified public-URL adapter.

| Check | Result | Exact evidence / limits |
| --- | --- | --- |
| Complete standard Rust workspace | PASS |192 passed;250 dedicated PG cases ignored and not counted as passes |
| Complete native disposable PostgreSQL suite | PASS |250 passed in56.39s;442 distinct Rust tests with standard suite |
| New broker PostgreSQL cases | PASS |15 within250; prior10 lifecycle cases also pass |
| Actual legacy Python command/hash parity | PASS |24 request cases inside one new standard test; prior42 profile projection cases retained |
| Actual native executable / Rust HTTP | PASS |Three framed process invocations lease, start and acknowledge one fictional command; no GUI or provider call |
| Concurrency / failures / replay | PASS |Two pollers, queue20 cap, wrong identity/session/token/version, suppressed lease write, expiry during material wait, source/policy/confirmation changes and historical quarantine |
| Historical size / status contention | PASS |20,002 closed records retained; ordinary status succeeds while owner row is locked |
| Formatting / Clippy / diff | PASS |All-target Clippy12.92s with warnings denied; Rustfmt/diff pass |
| Continuity | PASS |Private snapshot/verify checks881 transcript references; no sidebar/account ownership rewrite or absent-file recovery claim |
| Frontend / extension JavaScript suites | NOT TESTED |No UI/JS/API-schema changes in this slice; prior passes remain prior evidence |
| Actual owner browser/account/provider/application | NOT TESTED |No owner tab/window/profile/queue/account action or real Apply admission |
| Native task/form execution | NOT TESTED |Still unported; command transport success does not establish a working application flow |
| Whole-family deployment / resource / receipts | NOT TESTED |No new install, paired resource measurements, awake/locked acceptance or strict worker receipt |
| Complete approved plan | IN PROGRESS |Continue task/form/kernel/execution, remaining services/platforms, then combined/cutover/live acceptance |

Initial fixtures lacked matching owner confirmation and an exact durable historical
admission; the production guards correctly refused them. Fixtures now establish those
facts without weakening guards. The large-history case exposed the prior10,000-record
scan limit applying to closed history; active-only queries fixed it. An intermediate unused
helper warning was removed before final Clippy. Private evidence remains under
`.local/browser-commands-{workspace,postgres,postgres-full,clippy,oracle}.log` and the private
continuity log files. No new dependency, schema change or database role widening occurred.

```sh
cargo test --locked --workspace
uv run --no-project python -m rust.scripts.run_postgres_tests --filter browser_
uv run --no-project python -m rust.scripts.run_postgres_tests
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
git diff --check
uv run --no-project python scripts/project_continuity.py snapshot
uv run --no-project python scripts/project_continuity.py verify
```

No hosted Actions, merge, cleanup, installation, actual browser focus change, provider
call, message or application action occurred. Brave remains primary, Edge explicit,
Safari deferred. Window creation remains suspended. Supervised4/hourly1, three quarantined
admissions, one remaining eligible fourth attempt and the first strict worker receipt
prerequisite remain. The pending owner sign-in request is not repeated.
