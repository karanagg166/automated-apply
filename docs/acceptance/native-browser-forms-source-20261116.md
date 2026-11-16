# Native form source checkpoint — NOT TESTED

Implementation branch: `feat/rust-agent-runtime`, exact implementation
[`203a1b9eb04f2c0949b64043193ba86c9bf118c4`](https://github.com/karanagg166/automated-apply/commit/203a1b9eb04f2c0949b64043193ba86c9bf118c4).
Review: [PR50](https://github.com/karanagg166/automated-apply/pull/50), base
`chore/uv-python-tooling`. Source-only milestone under the owner's instruction to
finish remaining files before the final combined tests. No installation or live acceptance.

## Changes written

- Frozen inspection, plan and receipt contracts; evidence-backed control proposals,
  sensitive/ambiguous controls left unresolved, current profile/packet/project/missing-answer
  and canonical private PDF checks, exact field review and single consumption.
- Native inspect/prepare/authorize/receipt dispatch, owner plan listing/review and existing
  task attachment. Mutating form paths use the existing owner lock and serializable
  transaction, nested rollback, write acknowledgements and request nonce.
- Partial/late receipts preserve original profile/session/tab provenance without changing
  a transferred task or claiming submission. Execution changes retain existing history,
  diagnostic and stable `state_changed` outbox identities.
- Observed unanswered Naukri questions enter packet history. Explicit native Ask prepares
  contextual owner envelopes after the final sibling packet revision. Question-only
  execution records grant no fill, application admission or submission authority.
- Fifteen database regressions written for the final gate, including complete/partial
  fills, stale context, nonce conflict, task transfer, sensitive controls, source questions,
  owner pause, late command expiry, suppressed write ACK and unknown commit.

## Evidence matrix

| Gate | Status | Exact evidence / limitation |
| --- | --- | --- |
| Source and fixture files recorded | PASS | Implementation commit above;15 new PostgreSQL test declarations |
| Current source compilation / Clippy | NOT TESTED | Intentionally deferred; no new build invoked |
| New database tests | NOT TESTED | 0 executed,0 passed,0 failed;15 declarations are not15 passes |
| Current full Rust/Python/UI/extension suites | NOT TESTED | Last full Rust checkpoint remains193 standard +262 native PostgreSQL at9c4ace5; those455 passes do not validate this change |
| Pure form helper historical comparison | PASS, historical only | Before the test-deferral instruction,2 pure tests passed, including707 actual-Python branch comparisons; not a current combined acceptance run |
| Actual Mac browser/focus/install | NOT TESTED | No browser/window/tab/service/install operation performed |
| Actual provider/profile/application receipt | NOT TESTED | No real application/owner fact/account/provider/queue change |
| Recurring AUTOMATIC | BLOCKED | Zero strict worker receipts; retained lifetime4/hour1 and three uncertain admissions remain prerequisites |
| Telegram question delivery / replies | NOT TESTED | Envelopes are source-level queueing only; legacy delivery/reply parity remains to port and validate |
| Full project completion | NOT TESTED | Whole execution/kernel, remaining service/provider/platform ports and final/cutover/live gates remain |

`cargo fmt --all` wrote formatting. It did not compile or execute tests. Source review
identified and corrected missing execution history/diagnostic/outbox compatibility and
the need to create sibling envelopes only after their final packet revision. No current
failure-code log, runtime measurement, resource comparison or browser evidence exists for
this change; do not infer one. Raw historical oracle output stays private.

## Final-gate reproduction commands — not executed at this checkpoint

After all remaining source is integrated, run `uv run --no-project python
scripts/run_acceptance.py --run`. The runner still needs the planned disposable Python
PostgreSQL and isolated browser/UI stages before that invocation. Native database command:
`uv run --no-project python -m rust.scripts.run_postgres_tests`; standard Rust command:
`cargo test --locked --workspace`. No personal browser profiles or live candidate database.

Continue the consolidated source plan, complete native question delivery/replies and
execution/kernel ports, reconcile every route/worker, then compile and run the combined
gate. Review canonical PDF, transaction/concurrency, migration and actual Mac focus/resource
behavior before install/live acceptance. Rough engineering estimate stays58%/42%; no
acceptance percentage increase follows from untested source.
