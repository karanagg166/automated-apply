# Profile facts and snapshot corrections — source checkpoint 2026-11-16

Implementation [`877cad29333bf17a5ace019df76f28d136e507b8`](https://github.com/karanagg166/automated-apply/commit/877cad29333bf17a5ace019df76f28d136e507b8), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Unvalidated source, not installed or live accepted.

The pure profile comparison now preserves all18 legacy fields, casefold/decimal-phone normalization, national-number ambiguity, presence-only sections, hashed references and separately approved summary/skill updates. Skills preserve every original chip and add only verified approved additions, using the existing published aliases. Desired job titles and salary floors do not become a personal headline/title or compensation fact. Account contact and login remain separate. Three actual-AST DTO schemas were added for account approval and profile sync policy/update; UUID inputs canonicalize before validation. Profile-sync IO/native dispatch is still pending.

## Corrections found during source review

The previous preparation checkpoint described a READ COMMITTED material path. Nested missing-answer/project fingerprints also require a consistent snapshot. Preparation now explicitly uses SERIALIZABLE and locks queue/config/confirmation/account/selection control rows after the shared owner lock, plus the primary profile/material versions. An update committed while waiting must cause a serialization failure, including updates by a legacy READ COMMITTED writer. Existing snapshot requirements were preserved. The new lock-wait/Stop regression is written but UNRUN. Broader serializable owner-wait/control interactions in existing form/review/generation paths still need audit and combined concurrency validation before installation.

The new receipt evidence hash initially used the generic compact JSON binding; the actual legacy expression uses spaced ASCII JSON. The source now uses that exact recipe, with a new actual-AST expression oracle. No receipt was created and this code was not installed before the correction.

## Evidence matrix

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source tracing/formatting/schema generation | PASS (source only) | Actual profile_sync/profile_skills/account DTO definitions and receipt expression read; source formatters and schema --write only |
| New standard Rust tests | NOT TESTED | 3 declarations: pure profile oracle (186 comparisons plus hashes/additions/prepared/canonical cases), closed sync/account DTOs, actual legacy receipt hash expression with2 inputs |
| New native PostgreSQL tests | NOT TESTED | 1 declaration: preparation waits at owner row while legacy Stop commits, then must abort without changing work |
| Broader owner-wait/control snapshot audit | NOT TESTED | Required for existing serializable form/review/generation paths before final acceptance |
| Build/Clippy/drift checks/all suites | NOT TESTED | No tests/checks/builds executed; owner source-first/final combined gate remains in force |
| Actual Mac/provider/browser/DB/profile save/message/install | NOT TESTED | No live operation or runtime replacement |
| Production schema/whole-family cutover | BLOCKED | Reviewed operator migration/grants and STOP installation remain required |
| Actual strict receipt/AUTOMATIC | BLOCKED | Last real evidence0 strict receipts; no activation |
| Focus/locked/restart/24h resources | NOT TESTED | Prior focus findings remain; no timing/resource claims |

Prior fully validated checkpoint remains9c4ace5:193 standard +262 dedicated disposable-PG tests,455 distinct. No new result is inherited from it. Estimate stays58% complete /42% remaining, an engineering estimate, not an acceptance score.

## Reproduction and remaining work

After complete source integration, run `scripts/run_acceptance.py` under coordinated locks with fictional native PostgreSQL. Added files are `tests/profile_sync_facts.rs`, the receipt hash case in `tests/submission_observations.rs` and the fifth preparation PG case. The AST oracles never import application settings or access real candidate data. Schema reproduction is `uv run --no-project --python .venv/bin/python rust/scripts/export_execution_contracts.py --check`, reserved for that final gate; only --write ran here.

No executed failure logs exist. Expected snapshot failure is sanitized execution_database_error with rollback; no automatic action replay. Profile errors include profile_skills_bounded_observation_required, profile_skills_existing_chips_changed_or_no_addition and profile_skills_unapproved_or_duplicate_addition. No correctness or performance comparison follows from unrun fixtures.

Continue owner account approval and complete profile-sync policy/status/work/save/reconciliation, original questionnaires/owner replies, search discovery and native broker/scheduler, then all remaining services/providers/platforms in the [completion plan](../plans/completion-execution-20261116.md). Existing STOP162, lifetime4/hour1, three quarantines, filters, focus, Gmail read/draft-only, private history and installed services remain unchanged.
