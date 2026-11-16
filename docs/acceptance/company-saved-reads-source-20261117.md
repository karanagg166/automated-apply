# Saved company reads — source checkpoint 2026-11-17

Implementation [c958651ac1a0704ca21580005890bdc9cc2d1d4c](https://github.com/karanagg166/automated-apply/commit/c958651ac1a0704ca21580005890bdc9cc2d1d4c), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

Company people and startup jobs/evidence GETs now use one read-only repeatable-read transaction, exact employer scope, stable pagination/counts and expanded JSON byte bounds. Jobs reuse the original catalog projection/normalizer. Professional people expose selected public identity/source fields and bounded saved evidence text/manual mode, excluding raw vendor fields, phones and private metadata. Company observations expose only declared normalized attributes and public HTTPS links. No GET fetches a source URL, mutates a record or takes the owner mutex.

Old observations remain visible as stale. Future timestamps require review without overwriting the recorded verification status. Timestamps normalize to UTC; saved evidence never claims a current probe, mailbox verification or sending authority. Derived startup detail/scoring/search, shortlist mutations and provider discovery remain subsequent work.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Three saved-read endpoints, shared job DTO, selected public fields, stable bounds/qualification/auth/error mapping; formatting applied |
| Standard fixtures | NOT TESTED | 2 declarations: professional projection/privacy/UTC/future; observation declared fields/private links/malformed attributes |
| Dedicated native PG/HTTP | NOT TESTED | 8 declarations: public projection privacy; future/stale qualification; employer isolation/paging; actual job DTO; owner-lock independence; missing/malformed data; method/query/body/expanded bounds; owner HTTP authentication/methods |
| Frontend additions | NOT TESTED | No new declarations in this slice; earlier source remains unrun |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests0; all source precedes combined gates |
| Actual Mac/provider/runtime/install | NOT TESTED | No provider/network/account/browser/installation action or private data read |
| Timing/resources | NOT TESTED | Bounded coherent saved reads by source design; no measured performance comparison |

Fixed errors include `company_saved_not_found`, `invalid_company_saved_query`, `invalid_company_saved_record`, `company_saved_projection_limit` and `company_saved_database_error`. No executed failure log, candidate data, mail or raw private evidence is published.

Final reproduction: coordinated `scripts/run_acceptance.py`, Rust `companies` and dedicated disposable native PG `company_saved_*`, full frontend/company/people journeys and browser/types/build gates. Commands are documented, not executed now. Continue actual startup contracts/size/hiring qualification/scoring/catalog/shortlists, public research and remaining dashboard/registry/provider/CLI/conversation/eight-platform source before combined gates and reviewed migration/install/live evidence. Last validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard+262 native PG=455 distinct passes; not current-head validation.58/42 held. STOP162/lifetime4/hour1/three uncertain quarantines/strict worker receipts0 and current filters/identity/PDF/focus rules remain. No hosted Actions, merge, cleanup, sending or installation.
