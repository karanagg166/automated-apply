# Native browser profile lifecycle — qualified acceptance

Branch `feat/rust-agent-runtime`; implementation
[`b0462175df6e0ed113601fe5629ef2f3c7f7f771`](https://github.com/karanagg166/automated-apply/commit/b0462175df6e0ed113601fe5629ef2f3c7f7f771),
[PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`.
The complete approved plan remains in progress. This checkpoint does not implement the
browser command executor or claim actual platform acceptance.

The Rust HTTP host now authenticates the fixed native-extension identity only on its
exact native route. Bearer token, peer, Host, origin and TLS/private-socket requirements
remain; duplicate identity headers, wrong extensions and native clients on owner routes
are refused. Existing native message schema validates bounded requests before mutation.
Connect, heartbeat and disconnect now preserve the legacy owner preferences, hashed
profile secret, session/window identity, version and opt-in command flag. Owner profile
listing, selection CAS, fixed-profile restriction and disconnect routes are implemented.
No database schema changes or additional connection/pool are introduced.

Reconnect, disabling commands, selection changes and offline detection invalidate old
tasks/plans/commands under the existing legacy owner lock. A lost session/window moves
admitted original forms to unknown reconciliation, closes their old questions and records
an outbox event without refunding admission, creating a receipt or replaying Apply.
Owner/global pause reasons and historical unknown evidence survive. After three prior
history checks, eligible unknown work can enqueue one honest unconfirmed-outcome notice
under existing preferences; it never claims submission. No real Telegram delivery occurs.

Status excludes profile secrets and command lease tokens/hashes; history pages are bounded
to30 commands/receipts with stable creation/key ordering. Related inventory is capped at
10,000 records and fails explicitly above the cap rather than silently skipping revocation.
Future heartbeat timestamps no longer establish liveness. Windowless heartbeat always
reports `background_window_allowed=false`, preserving the actual failed Brave focus
finding. Poll/start/ack remain explicitly unavailable until the next broker port.

All writes check returned acknowledgements. Suppressed writes roll back task/audit/state
changes and release the owner lock. Failed commit is unknown; the API closes/reconnects
without automatically replaying the mutation or emitting a safe-retry header.

| Check | Result | Evidence / limits |
| --- | --- | --- |
| Complete standard Rust workspace | PASS |191 passed;235 dedicated PG cases ignored and not counted as passes |
| Complete native disposable PostgreSQL suite | PASS |235 passed in54.40s;426 distinct Rust tests with standard suite |
| New lifecycle PostgreSQL cases | PASS |10 within235; targeted1.54s overlaps the complete run |
| Python public projection parity | PASS |42 actual isolated legacy-Python comparisons inside one of3 new standard tests |
| New HTTP boundary cases | PASS |Exact extension route, missing/wrong/duplicate identities, origin, bearer, owner-route confinement, strict body and method checks |
| Failure/concurrency cases | PASS |Suppressed profile write, deferred commit failure and API reconnect, CAS race, session/window quarantine, bounded unknown notice, expired non-redelivery |
| Clippy / formatting / diff | PASS |All-target warnings denied1.69s; Rustfmt and diff checks pass |
| Actual owner browser/profile/account/platform | NOT TESTED |All new database/HTTP evidence is fictional; no installed profile, tab/window, account or provider action |
| CPU/RSS/latency resource comparison | NOT TESTED |No paired whole-runtime measurement; query/page caps are source bounds only |
| Browser command/application execution | NOT TESTED |Not implemented by this checkpoint; unavailable response remains explicit |
| Whole-family installation / real receipts | NOT TESTED |Legacy installed family remains unchanged; no new Apply admission or worker receipt |
| Complete approved plan | IN PROGRESS |Continue broker/task/form/application ports, other remaining services and final combined/cutover/live acceptance |

The initial HTTP fixture omitted required readiness tables and failed target validation;
it now uses the existing fictional knowledge fixture. A compile-time Boolean/JSON mismatch
in notice preferences was corrected before final validation. No runtime role was widened.
Private logs are `.local/browser-profiles-{workspace,postgres,postgres-full,clippy}.log`.
No frontend/API schema or dependency changed, so frontend tests are not freshly counted here.

Reproduce from the canonical checkout:

```sh
cargo test --locked --workspace
uv run --no-project python -m rust.scripts.run_postgres_tests --filter browser_profiles
uv run --no-project python -m rust.scripts.run_postgres_tests
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
git diff --check
```

No hosted Actions, merge, cleanup, service installation, owner data mutation, browser focus
change, provider call, message or application action occurred. Supervised4/hourly1, three
quarantined admissions, one remaining eligible fourth attempt and the first strict receipt
prerequisite remain. Do not repeat the pending owner sign-in request or failed window path.
