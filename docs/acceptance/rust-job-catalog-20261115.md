# Rust saved-job screen — 2026-11-15

Implementation [`2195b4c8ac9b144138912eb9309171bace790a05`](https://github.com/karanagg166/automated-apply/commit/2195b4c8ac9b144138912eb9309171bace790a05),
branch `feat/rust-agent-runtime`, [PR #50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling`. Full migration and live application acceptance remain incomplete.

Rust now implements the complete saved-job screen group: job listing, full 17-field
details, GET matching alongside the existing POST, and owner shortlisting. Catalog reads
need no candidate profile, inference or provider call. They preserve nullable fields,
status/pagination defaults, numeric scores, UTC/microsecond timestamp representation and
the private/internal field projection. Static SQL shares one compile-time projection;
all request values are bound parameters. No runtime SQL interpolation or new dependency.

Read-only list queries preserve legacy last-value scalar handling and ignore unknown keys.
Invalid status and invalid stored DTOs use the legacy 400 Invalid argument response;
malformed pagination/UUID inputs remain 422. Listing uses a stable ID tie-breaker where
legacy equal creation times had no defined order. A 4KiB query cap is an explicit stricter
bound. URL strings retain the legacy DTO's permissive data semantics; returned text never
grants browser/tool authority.

GET matching validates the profile before looking up the job; POST retains job-first
lookup. Both reuse the same scorer and write no job scores, profile, history or budget.
Shortlisting holds a row lock, accepts only discovered/reviewed/already-shortlisted jobs,
preserves timestamps for no-ops and commits before ACK. It checks exactly one updated row,
rolling back a silently suppressed write. It cannot overwrite a concurrent progressed
status or authorize an application, quota admission or submission.

| Check | Result | Evidence and limits |
| --- | --- | --- |
| Standard Rust workspace | PASS | Fresh 129 passed,0 failed;140 dedicated PG tests ignored in this run |
| Full disposable PostgreSQL suite | PASS | Fresh 140 passed,0 failed,34.92s |
| Distinct total | PASS | 269 = 129 standard + 140 PG; five new catalog tests; focused reruns not added |
| Owner HTTP/catalog DTO | PASS | Auth before malformed query; extension client denied; full projection, nulls, timestamps, status/pagination and missing records tested without a profile |
| Match compatibility | PASS | Actual HTTP GET/POST equal valid scores; distinct lookup-order failures preserved; no score/model-budget write |
| Shortlist transaction | PASS | All six statuses, independent committed readback, unchanged no-op timestamps, held row lock/concurrent progression, raised and silently suppressing triggers |
| Independent read-only review | PASS | Two findings fixed: suppressed UPDATE acknowledgement and stored DTO error class; full suite passed afterward |
| Clippy/format/diff | PASS | Workspace/all-target warnings denied; Cargo format and whitespace checks |
| Actual production Mac job data | NOT TESTED | All new job fixtures fictional; no production shortlist, application action or provider call |
| Full Rust installation/live receipts | NOT TESTED | Legacy runtime remains installed; complete worker/service parity, physical account connection, rollback/focus/resource and real receipt acceptance remain |

Initial compilation rejected runtime-built SQL under SQLx 0.9's static SQL contract
(`E0277`/`E0597`). A shared projection macro plus compile-time `concat!` resolved this
without an unsafe assertion or duplicated query projection. The earlier focused run
passed six tests (five new catalog tests plus an existing MCP catalog test); the final
full suite additionally includes the review fixes. No unresolved test failure remains.

Standard test-body times sum to 5.24s, PG tests 34.92s, Clippy 7.65s. These are unpaired
fictional timings, not a whole-project speed, CPU/RSS/GPU or live-provider comparison.
No schema migration, production data write, new pool, browser launch, runtime replacement,
cleanup or hosted Actions occurred. Raw logs stay ignored/private in canonical `.local/`.

```sh
cargo test --locked --workspace
uv run --no-project python rust/scripts/run_postgres_tests.py
uv run --no-project python rust/scripts/run_postgres_tests.py --filter catalog_
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
git diff --check
```

Next: application-packet lifecycle/review/readiness and immutable snapshots, then legacy
queue/admission/quarantine, native browser/questionnaire/profile/receipt parity and the
remaining provider/Gmail/Drive/discovery/Telegram services. Existing application limits,
unknown jobs and owner facts remain authoritative throughout cutover.
