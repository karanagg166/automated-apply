# Atomic professional imports — source checkpoint 2026-11-17

Implementation [4418abc52f8ef78d4387c87bc3898b4a64195d9e](https://github.com/karanagg166/automated-apply/commit/4418abc52f8ef78d4387c87bc3898b4a64195d9e), branch `feat/rust-agent-runtime`, [PR 50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source; this domain service awaits owner/provider controller integration.

Local manual professional imports now commit their UUID receipt, selected public-person observations and conservative contact reconciliation atomically. Exact replay returns the original result without refreshing evidence; changed input conflicts. A nonempty batch requires an explicit normalized company domain, since display name alone cannot merge employers. Canonical company facts, confirmed public-person rows, suppression, corrections and earlier identity review conflicts remain protected. Official imports require rights confirmation and exact employer/publication domains. Independently confirmed owner evidence remains distinct from provider claims and mailbox verification; no sending occurs.

The complete bounded existing person inventory is reused across a batch. Canonically equivalent historical profile URLs match before insertion; ambiguous historical matches fail for review. Canonical URL deduplication avoids duplicate contact work. Selected retained outputs exclude private nested fields. All coupled writes roll back on complete acknowledgment failure. Shared contact reconciliation now independently rereads contact, evidence, identity and receipt writes after triggers.

Source review found the earlier saved company reader and its fixture used `discovered_people`, while the actual migration defines `discovered_company_people`. The reader is corrected and its fixture now creates the actual migration table definition. This was a source-review finding, not an executed test failure. Full combined validation is still required.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Atomic UUID imports/retained reads, conservative identity qualification, complete acknowledgments, actual company-person table correction; formatting applied |
| Standard additions | NOT TESTED | No new declarations in this slice; earlier source remains unrun |
| Native PG fixtures | NOT TESTED | 14 declarations: real table/read bridge/dedup; replay/hash conflict; weak official mailbox; confirmed publication; domain mismatch; missing domain/rights/source; protected confirmed rows; suppression/corrections; public-row rollback; shared identity/evidence/receipt rollback; retained privacy; concurrent UUID; qualification-trigger rollback; ambiguous historical URLs |
| HTTP / frontend additions | NOT TESTED | None in this slice; controller and durable dashboard recovery remain pending |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests: 0; complete source precedes combined gates |
| Actual Mac/provider/install | NOT TESTED | No credential, provider, account, browser, production or installation action |
| Timing/resources | NOT TESTED | One bounded inventory per manual batch in source; no measured runtime comparison |

Fixed codes include `public_research_company_domain_required`, `public_research_request_conflict`, `public_research_official_permission_required`, `public_research_person_url_ambiguous`, `public_research_write_ack_failed` and `contact_identity_write_ack_failed`. No executed failure logs or private evidence are published.

Deferred reproduction: complete dedicated disposable PG `people_*` and shared `contact_identity_*`/`company_saved_*`, then the coordinated `uv run --no-project python scripts/run_acceptance.py` and later full research/provider/UI/install/live gates. Continue durable paid search admission/retained findings/controller integration and remaining agreed full source.

Last validated `9c4ace570535a5856184775f8045ee89eafdd05f` remains 193 standard + 262 dedicated native PG = 455 distinct passes, not current-source evidence. Estimated completion remains 58% / 42%. Last observed STOP revision 162, lifetime allowance 4/hourly 1, three uncertain quarantines, zero strict worker receipts and all current filters/identity/PDF/focus rules are unchanged. No hosted Actions, merge, cleanup, sending or installation occurred.
