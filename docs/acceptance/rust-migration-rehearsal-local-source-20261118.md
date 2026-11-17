# Local Rust migration rehearsal

Local branch `feat/rust-agent-runtime`, implementation `398e25035533b51451032e98ac4056206e078d09`.

The combined runner now includes the existing reviewed SQL package rehearsal. The rehearsal uses a separate disposable loopback PostgreSQL cluster and verifies STOP enforcement, the pinned catalog and the restricted role. The private combined report records the Git commit and worktree cleanliness at the start and end. It records a clean-commit fixture pass only after all stages pass and both observations show the same clean commit.

| Gate | Status | Evidence |
| --- | --- | --- |
| Plan wiring and source checks | PASS | The plan lists 33 stages, includes the migration rehearsal without manifest writes, and lists no live actions. Ruff and Git whitespace checks passed for the changed source. |
| Combined suite and rehearsal | NOT TESTED | Six new tooling cases and the existing disposable migration rehearsal await the combined run. |
| Laptop installation and operational acceptance | NOT TESTED | The reviewed migration was neither applied to the owner database nor used to change the installed writer family. No live browser or provider operation ran. |

Inspect the plan with `uv run --no-project python scripts/run_acceptance.py --plan`. Continue remaining source and fixtures, then run the combined suite and use its private report during installation review. The engineering estimate stays at 58% complete and 42% remaining pending current validation.
