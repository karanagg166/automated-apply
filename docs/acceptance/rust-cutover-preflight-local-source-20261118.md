# Rust cutover preflight

Local branch `feat/rust-agent-runtime`, implementation `be597e9211aec0c9fb992b6c8577d783b12aff8b`.

The reviewed additive SQL package checks the STOPPED application queue and locks and checks any saved legacy Naukri preparation control before creating Rust tables. The package checksum changed. The migration's table definitions and expected catalog are identical.

The candidate's `cutover-preflight --config /absolute/private/runtime.env` command checks Rust readiness and saved STOPPED controls after the reviewed migration. It opens one bounded read-only PostgreSQL transaction and reports control revisions, the current role's connection limit and a count of its other visible database sessions. Pooler headroom, the legacy process inventory and the rollback inventory require separate evidence during the cutover review.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source checks | PASS | Rust formatting, Python lint and Git whitespace checks passed. The rendered SQL matches the checked-in artifact and pinned checksum. |
| Disposable PostgreSQL | NOT TESTED | The Rust executable fixture and the revised migration rehearsal await the combined run. |
| Laptop cutover and live receipt | NOT TESTED | No operator migration, live database preflight, runtime restart or provider application occurred. |

The engineering estimate stays at 58% complete and 42% remaining. The combined results, reviewed installation and live Naukri receipt are pending.
