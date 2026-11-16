# Owner execution status reads — source only, NOT TESTED

Branch `feat/rust-agent-runtime`, implementation
[`f23f5e3dca30e98717821a725b3253e7ab65ea8b`](https://github.com/karanagg166/automated-apply/commit/f23f5e3dca30e98717821a725b3253e7ab65ea8b).
[PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`.

The native host source now serves the existing owner GET `/api/v1/execution/queue` and
GET `/api/v1/execution/naukri/account-binding`. Queue status uses a read-only repeatable
snapshot, two business SELECT statements and no owner-row lock. Transaction setup/commit
add protocol work. The query aggregates retained history and projects only public item
metadata; descriptions, profile bindings, admission arrays, reservation IDs and internal
leases are not returned. Full closed history is retained in storage.

Saved policy/STOP revisions and reservations are read without rewriting them. Invalid
saved policy/budget fails rather than becoming a fresh allowance. Daily budget date uses
the saved timezone. The status advertises submission as unavailable while the native
kernel remains incomplete. This is a read port, not an operational application worker.

The source uses `NOT MATERIALIZED` for side-effect-free inventory/filter CTEs, following
[official PostgreSQL17 materialization documentation](https://www.postgresql.org/docs/17/queries-with.html#QUERIES-WITH-CTE-MATERIALIZATION).
That is a query design choice, not a measured speed or memory result. Current first-worker
binding predicates also reject missing profile IDs/revision rather than comparing absent
JSON fields as equal. Existing execution-mode denials retain their prior HTTP handling;
the new error mapping enumerates only the new service errors.

| Gate | Status | Exact evidence / limitation |
| --- | --- | --- |
| Source/SQL/route integration recorded | PASS | Exact implementation SHA above;2 owner GET routes |
| New PostgreSQL scenarios | NOT TESTED | 5 new declarations,0 executed,0 passed,0 failed |
| Written retained-history fixture | NOT TESTED |20,002 fictional closed rows,owner-lock contention and bounded/redacted response assertions; none executed |
| Written policy/quota/API scenarios | NOT TESTED | STOP162/lifetime4/hour1-shaped fixture,filter/paging/counts,malformed-budget non-reset and owner/native/method separation; none executed |
| Current compilation/Clippy/full suites | NOT TESTED | Intentionally deferred; historical455 Rust passes at9c4ace5 are not current validation |
| Actual DB/account/profile/browser | NOT TESTED | No live connection/query, browser launch or account/provider change |
| Runtime timing/resources | NOT TESTED | No measurement or accepted comparison |
| Queue writes/claims/admissions/worker | NOT TESTED | Remaining kernel ports; no new write route or browser dispatch |
| Full project completion | NOT TESTED | All remaining source,combined gate,STOP cutover and live/platform/recovery gates remain |

Only source inspection, SQL/reference research and formatting occurred. No test/build/
lint/check, fixture cluster, service restart, production migration or installed extension
change. No application allowance was consumed/refunded and no recurring AUTOMATIC enabled.
There are no new runtime logs/failure counts to publish. No PII or credentials are in
the fixtures/report.

Continue owner control/fencing and the complete native queue/kernel, then the remaining
service/provider/platform ports. After all source is complete, invoke `uv run --no-project
python scripts/run_acceptance.py --run`. The5 new cases join `uv run --no-project python
-m rust.scripts.run_postgres_tests`; these commands were not run at this checkpoint.
Keep the rough58%/42% estimate and the last validated checkpoint separate from this source.
