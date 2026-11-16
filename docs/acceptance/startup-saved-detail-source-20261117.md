# Derived saved company detail — source checkpoint 2026-11-17

Implementation [fe0e7c2495f23af1350ee5d8ccc615a996463382](https://github.com/karanagg166/automated-apply/commit/fe0e7c2495f23af1350ee5d8ccc615a996463382), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

The owner startup detail GET now combines source-qualified company attributes/size, saved current job/board hiring evidence, complete bounded contact counters and deterministic relevance in one read-only repeatable-read snapshot with one database clock. Legacy company metadata is not promoted to public attributes; private job metadata is reduced to the expiry/current-listing claims needed for qualification. Observation/job URLs are validated before public projection.

Contact counts reuse existing evidence/retention rules and reject suppressed, conflicting or future contact observations. Public detail receives aggregate counts and relevance summaries, without contact/profile PII or vendor payloads. Missing profiles, company identity review and future observations remain explicit findings. Exact StartupRead/Search output schemas are now frozen through the actual AST-only exporter. Search and shortlist composition follow this detail dependency; the detail shortlist flag remains a placeholder until that next slice wires saved shortlist state.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Snapshot detail/qualified attributes/size/hiring/contact counters/relevance, actual output schemas, owner GET/auth/error wiring; formatting applied |
| Native PG/HTTP fixtures | NOT TESTED | 9 declarations: combined detail/privacy/actual output DTO; no legacy promotion; old/future/historical/review/human priority; closed/no jobs; suppressed/conflicting/future contact counts; missing profile; missing/malformed expanded evidence; read-only owner-lock independence; owner HTTP/auth/method/query |
| Standard/frontend additions | NOT TESTED | No new declarations in this slice; previous source remains unrun |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests0; full source precedes combined gates |
| Actual Mac/provider/runtime/install | NOT TESTED | No provider/account/browser/production/installed action |
| Timing/resources | NOT TESTED | Coherent bounded snapshot by source design; no measured runtime comparison |

Fixed failures include `startup_catalog_not_found`, `startup_catalog_inventory_limit`, `invalid_startup_catalog_record` and `startup_contact_inventory_limit`. No executed failure logs, candidate data, mail or private evidence are published. Derived relevance and saved hiring evidence grant no application authority.

Final reproduction: coordinated `scripts/run_acceptance.py`, dedicated disposable native PG `startup_detail_*`, actual StartupRead oracle and full catalog/frontend/browser gates. Commands are documented, not executed now. Continue filtered search/shortlist persistence/public discovery and remaining dashboard/registry/provider/CLI/conversation/eight-platform source, then coordinated gates and reviewed migration/install/live evidence. Last validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard+262 native PG=455 distinct passes; not current-head evidence.58/42 held. Last observed STOP162/lifetime4/hour1/three uncertain quarantines/strict worker receipts0 and configured filters/identity/PDF/focus rules are not changed. No hosted Actions, merge, cleanup, sending or installation.
