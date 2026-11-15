# Rust notification inbox — 2026-11-15

Implementation [`8e35f7ad5a5ba845c516cb7622be1ecc6adb3da5`](https://github.com/karanagg166/automated-apply/commit/8e35f7ad5a5ba845c516cb7622be1ecc6adb3da5),
branch `feat/rust-agent-runtime`, [PR #50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling`. Full migration remains incomplete.

Three existing owner dashboard routes now use Rust and the existing PostgreSQL connection:
notification inbox, mark-read receipt and saved delivery history. Inbox pages retain 50
records and delivery history 100; private deduplication/internal linkage fields are omitted.
Mark-read uses one autocommitted update before acknowledgement and changes no delivery,
application, preference, profile or quota state. No notification dispatcher or new task,
pool, dependency, schema migration or production runtime was installed.

| Check | Result | Evidence |
| --- | --- | --- |
| Standard workspace | PASS | Fresh 129 passed,0 failed;135 dedicated PG tests ignored in this run |
| Full disposable PostgreSQL suite | PASS | Fresh 135 passed,0 failed,33.94s |
| Distinct total | PASS | 264 = 129 standard + 135 PG; four new PG tests, no focused-run double count |
| Actual HTTP/PG integration | PASS | Auth precedes invalid query/body handling; extension client denied; 50-row pagination, projection,405/404/422 and committed read receipts |
| Failure/privacy | PASS | Forced DB update failure preserves unread rows and hides private SQL error; oversized stored body rejected without truncation/deletion |
| Delivery/application safety | PASS | History reports external delivery disabled; attempts, preferences and packets unchanged |
| Read-only independent review | PASS | No blocking authorization/transaction/privacy defect; misleading pagination detail corrected and response tested |
| Clippy/format/diff | PASS | Workspace all-target warnings denied; Cargo formatting and whitespace checks |
| Actual Mac production notification data | NOT TESTED | All notification fixtures fictional; no production inbox reads/writes or delivery |
| Full Rust install / job submission | NOT TESTED | Legacy services remain installed; account connection/receipt and remaining ports still pending |

Intentional stricter compatibility: only one `offset` parameter is accepted for inbox
pagination; legacy FastAPI ignored unknown/limit parameters and used the last duplicate.
The inbox rejects individual bodies over 64KiB or serialized pages over 512KiB; the old DTO
had no equivalent response cap. Current generated notifications use short fixed messages.
These differences are explicit, not a claim of unrestricted legacy DTO parity.

Initial focused validation passed 4/5: after forcing a database error, the same API correctly
entered its reconnect backoff and returned 503 before the test's unrelated oversized-body
check. That check now uses a fresh API instance to isolate the two conditions; all five
focused tests passed in 3.26s (four new notification tests plus one existing Telegram test).
The subsequent full 135-test PostgreSQL run passed; no unresolved test failure remains.
Standard test-body times sum to 5.05s; Clippy took 7.54s. These are unpaired fixture timings,
not an application speed, CPU/RSS/GPU or external-provider acceptance claim. Raw logs stay
private under ignored canonical `.local/`.

```sh
cargo test --locked --workspace
uv run --no-project python rust/scripts/run_postgres_tests.py
uv run --no-project python rust/scripts/run_postgres_tests.py --filter notification_
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
git diff --check
```

The current migration plan also corrects the supervised invariant to the owner's cap 4
without refunding consumed admissions or replaying the three uncertain jobs. Historical
milestone evidence is retained. No hosted Actions were dispatched. Continue saved-job
catalog/shortlist and remaining service ports; notification preferences/synchronization,
full legacy worker parity and all installed/live completion conditions remain open.
