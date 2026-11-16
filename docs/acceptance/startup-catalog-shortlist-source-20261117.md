# Saved startup search and shortlist — source checkpoint 2026-11-17

Implementation [ab7d8cb46aeadb5c177d32be2a6f2dd96a2acb36](https://github.com/karanagg166/automated-apply/commit/ab7d8cb46aeadb5c177d32be2a6f2dd96a2acb36), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

Owner GET/typed POST startup search and saved-shortlist GET share actual filter normalization and one read-only repeatable-read snapshot. The service rejects more than500 candidate companies after source/shortlist predicates,10000 aggregate jobs/packets and bounded output bytes. It filters/ranks the full qualified set before pagination and reports the actual total rather than truncating silently. Current source evidence, size, country/industry/role/skill/remote/stage choices, qualified business mailboxes and application status remain distinct controls. Early-stage remains explicit opt-in.

History predicates preserve legacy applied jobs and all bounded packet submission/interview/rejection evidence. A newer prepared packet cannot hide an older submission; preparation does not mean applied. Search projects selected history state labels, without private packet fields. Company detail now reads the actual shortlist state, replacing the previous placeholder.

Shortlist writes use the shared owner-first serializable fence, exact company/optional existing startup-run checks, one original insert and complete RETURNING/post-trigger ACK. Replays preserve the first snapshot/note/run and never regenerate or overwrite them. Public replay strips unexpected private fields from historical snapshots without changing the saved row. Neither searching nor shortlisting mutates job/application state or invokes a provider.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Filtered/ranked saved catalog, complete bounded packet evidence, original shortlist/ACK/privacy, actual detail shortlist state and owner endpoints; formatting applied |
| Standard fixtures | NOT TESTED | 1 declaration:140 actual job/packet/status comparisons plus conservative multiple-packet regression |
| Native PG/HTTP fixtures | NOT TESTED | 12 declarations: GET/POST/actual output DTO/paging; explicit filters; legacy/multiple-packet history; original shortlist/detail/list;3 ACK corruption modes; historical privacy; missing/contract boundaries; owner HTTP; read-only owner-lock independence; concurrent saves; company limit/source narrowing; actual startup-run identity |
| Frontend additions | NOT TESTED | No new declarations in this slice; previous source remains unrun |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests0; complete source precedes combined gates |
| Actual Mac/provider/runtime/install | NOT TESTED | No provider/account/browser/production/installed action |
| Timing/resources/concurrency | NOT TESTED | Snapshot/bounds and concurrency fixture source only; no measured runtime comparison |

Fixed findings include `startup_catalog_company_limit`, `startup_catalog_job_limit`, `startup_catalog_packet_limit`, `startup_catalog_projection_limit`, `startup_catalog_write_ack_failed` and `startup_catalog_run_not_found`. No executed failure logs, candidate data, mail or raw private evidence are published. Source fixture declarations establish no operational acceptance.

Final reproduction: coordinated `scripts/run_acceptance.py`, Rust `startup_history`, complete dedicated disposable PG `startup_search_*`/`startup_shortlist_*`/catalog boundaries and full frontend/company/shortlist/browser gates. Commands are documented, not executed now. Continue public research/discovery/provider status and remaining dashboard/registry/provider/CLI/conversation/eight-platform source before coordinated gates and reviewed migration/install/live evidence. Last validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard+262 native PG=455 distinct passes; not current-head evidence.58/42 held. Last observed STOP162/lifetime4/hour1/three uncertain quarantines/strict worker receipts0 and filters/identity/PDF/focus rules remain unchanged. No hosted Actions, merge, cleanup, sending or installation.
