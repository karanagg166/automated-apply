# Execution policy/filter/receipt core — source only, NOT TESTED

Branch `feat/rust-agent-runtime`, implementation
[`454dffa9a2e9903f4e3923e56ca3cc3e252969dd`](https://github.com/karanagg166/automated-apply/commit/454dffa9a2e9903f4e3923e56ca3cc3e252969dd).
[PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`.

The native execution module now contains closed policy/configuration/control contracts,
effective global/custom limits, filter-only capacity holds, conservative posting-date
and applicant-bound decisions, stable Naukri vacancy identities, fair inspection hints
and retained receipt predicates. The first-worker predicate additionally binds the current
account, original admitted Apply and confirmed work record. None of these pure functions
creates a receipt, consumes an admission or dispatches a browser operation.

Six DTO schemas are extracted from actual Python class ASTs without importing application
settings/services. Their drift exporter joins the final gate. Runtime day buckets use
exactly pinned `chrono-tz`0.10.4 with `std` only, researched against its
[official API documentation](https://docs.rs/chrono-tz/0.10.4/chrono_tz/). The lockfile adds
four packages:chrono-tz,phf,phf_shared,siphasher. Existing locked package versions are retained.
No dependency compilation occurred.

Saved policy values are inputs, not overwritten defaults. The frozen legacy DTO defaults
are separate from the owner's current saved14-day/1,000-applicant/score50/any-skill policy
and supervised lifetime4/hour1 allowance. This source changes no actual policy or record.
Malformed/uncertain outcomes are not promoted to verified receipts or refunded admissions.

| Gate | Status | Exact evidence / limitation |
| --- | --- | --- |
| Source and schema files committed | PASS | Exact implementation SHA above;6 DTOs; no settings import during schema writing |
| New regression execution | NOT TESTED | 3 new standard test declarations,0 executed,0 passed,0 failed |
| Written policy/filter corpus | NOT TESTED | Includes8 policy inputs,6 ZoneInfo day comparisons,3,240 posting/applicant scenarios,24 inspection orders,2 initial items and retained receipt/binding variants; these are unrun cases, not passes |
| Current compilation/Clippy/full tests | NOT TESTED | Deferred under the owner instruction; historical455 Rust passes at9c4ace5 do not validate current source |
| Native queue API/claim/admit/finish | NOT TESTED | Transactional queue/kernel port remains next; these helpers are not yet wired as a working queue service |
| Actual saved candidate/account/policy/DB | NOT TESTED | No live data read/write or production migration |
| Actual browser/provider/application | NOT TESTED | No browser launch, owner-focus change, provider call or application action |
| Actual first strict worker receipt | BLOCKED | No receipt obtained; recurring AUTOMATIC remains unaccepted |
| Timing/resources/binary size | NOT TESTED | No measurement; do not infer improvement from the source/library choice |
| Full project completion | NOT TESTED | Remaining source, combined gate, STOP cutover, per-platform live and24-hour gates remain |

Only source reads, primary library research, dependency resolution, AST schema writing and
formatting occurred. No lint/check/test/build command, fixture cluster, application service,
hosted workflow or actual queue was started. There are no new runtime logs/failure counts.
Python/schema files contain fictional contract metadata, not candidate facts or credentials.

Continue durable queue storage/status/control, whole-family stop fences, identity/PDF,
claim/admission/history/quota, original forms/question/upload/submission/reconciliation
and strict receipt ports. Preserve uncertain records and all existing limits throughout.
After all source is complete, run `uv run --no-project python scripts/run_acceptance.py
--run`; its new contract stage is `uv run --no-project python -m
rust.scripts.export_execution_contracts --check`. Neither command ran here. Estimate stays
58% complete/42% remaining; source alone is not new acceptance evidence.
