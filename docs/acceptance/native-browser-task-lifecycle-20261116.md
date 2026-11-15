# Native task ownership and recovery — qualified acceptance

Branch `feat/rust-agent-runtime`; implementation
[`9c4ace570535a5856184775f8045ee89eafdd05f`](https://github.com/karanagg166/automated-apply/commit/9c4ace570535a5856184775f8045ee89eafdd05f),
[PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`.
The complete approved plan remains in progress. Form inspection, exact-field approval,
fill receipts and owner-question bridging are not implemented by this checkpoint.

The existing native open/get/update task operations and owner list/application lookup/
pause-resume-cancel routes now run in Rust. Tasks keep their deterministic per-application
identity, saved packet/profile/context stamps, current/target URLs, original browser/tab/
window ownership, pause reasons, challenge state, counts and recovery evidence. A duplicate
open cannot create another task or revive approval. Explicit profile transfer requires the
previous task paused and retains owner/global pause. Binding validates destination, current
material and unclaimed tab ownership; missing/unknown states do not release an old claim.
Task metadata never authorizes submission. Unknown/nonimplemented form events fail explicitly.

Worker restart during filling retains an unknown partial receipt, clears plan/authorization
and requires fresh inspection. Focus-loss observations are idempotent; unexpected navigation
cannot authorize a redirect. Recovery retains owner/global stop and does not restore a guard,
tab or executable plan. Cancellation is terminal. A filling checkpoint whose candidate or
packet changed pauses the task rather than reporting a successful fill. Missing plan IDs
cannot claim fill-start idempotency. Native UUID inputs are canonicalized before binding.

Mutators share the existing owner fence and use a savepoint for task/audit writes. Native
request nonces are consumed once. Remote task requests require the original executing
command's profile/session/selection/version/token/application/task and current lease, checked
again after work. A delayed task insert past expiry rolls back the entire new task/request
audit and marks the original command unknown. No application admission is refunded.
Acknowledgements are checked before returning; database failures use existing reconnect
without mutation replay.

Normal task checkpoints use a read-only repeatable snapshot without the owner or packet
row lock. A filling checkpoint closes that snapshot before reacquiring the mutating owner
fence and rereading current state. Existing packet APIs retain their original shared parent
and material locking. The no-lock snapshot path is metadata only; every later mutation
rechecks the full context. The same control connection is used; no new pool or connection.
Typed DTO defaults preserve older saved records, including nested count/capability defaults.
Listing retains an explicit10,000-record inventory limit; no historical data is deleted.

| Check | Result | Exact evidence / limits |
| --- | --- | --- |
| Complete standard Rust workspace | PASS |193 passed;262 dedicated PG cases ignored and not counted as passes |
| Complete native disposable PostgreSQL suite | PASS |262 passed in56.57s;455 distinct Rust tests with standard suite |
| New task PostgreSQL group | PASS |12 within262; targeted2.53s overlaps full run |
| Actual Python DTO/helper parity | PASS |36 subcases inside one new test:9 saved DTO/default cases,8 navigation cases,5 contextual questions and14 next-action messages |
| Native lifecycle / owner HTTP | PASS |Duplicate open, nonce consumption, exact tab/version binding, pause/resume/cancel, profile transfer, typed list/lookup/control and extension-client refusal |
| Recovery / no replay / rollback | PASS |Unknown fill evidence, sticky stop, changed candidate during fill, concurrent opens, failed request audit, expired remote lease and insert delayed beyond lease |
| Checkpoint contention | PASS |Bound checkpoint succeeds while owner row is held with100ms lock timeout; no audit write for ordinary read |
| Existing packet locks / contracts | PASS |All prior packet/concurrency/failure tests pass in the complete PG suite |
| Clippy / formatting / diff | PASS |All-target warnings denied13.00s; Rustfmt/diff pass |
| Actual owner browser/account/provider/application | NOT TESTED |New DB/HTTP evidence is fictional; no owner tab/window, login, profile, queue or provider action |
| Form inspection / authorization / receipts / questions | NOT TESTED |Next port; task state and transport do not establish a working form/application |
| Resource / installation / actual strict receipt | NOT TESTED |No paired CPU/RSS/latency comparison, whole-family cutover or real application receipt |
| Full approved plan | IN PROGRESS |Continue form/execution/kernel and remaining account/provider/CLI/Telegram/platform ports, then combined/cutover/live acceptance |

The initial savepoint compile had an ambiguous SQLx trait call; explicit connection
dispatch fixed it. A nested default insertion was simplified after Clippy. The first full
PG run had261 passes and one fixture assertion counting older retained request audits;
the assertion now checks only its exact request nonce. Production rollback had already
succeeded. Fresh full rerun has262 passes. Isolated DTO/helper oracle0.24s. Private logs:
`.local/browser-tasks-{workspace,postgres,postgres-full,clippy,oracle,check}.log`.
No UI/extension JavaScript/API schema or dependency changed, so no new JS suite is claimed.

```sh
cargo test --locked --workspace
uv run --no-project python -m rust.scripts.run_postgres_tests --filter browser_tasks
uv run --no-project python -m rust.scripts.run_postgres_tests
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
git diff --check
```

No actual account/provider/browser action, new Apply admission, service installation,
Telegram message, hosted Action, merge or cleanup occurred. Window creation stays suspended;
the pending owner login request is not repeated. Supervised4/hourly1, three quarantined
admissions, one remaining eligible fourth attempt and the first strict receipt prerequisite
are unchanged. No recurring AUTOMATIC activation or completed-plan claim follows.
