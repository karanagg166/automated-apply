# Exact local intake identities and query filters — source checkpoint 2026-11-17

Implementation [a1da12b32e5bb7131782baed958c84fc46b20f4f](https://github.com/karanagg166/automated-apply/commit/a1da12b32e5bb7131782baed958c84fc46b20f4f), branch `feat/rust-agent-runtime`, [PR 50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source; database intake follows.

Native observation keys now preserve the actual source-board-ID or canonical original URL identity. Conservative content identity requires a company UUID, explicit company domain, location, known workplace policy and at least 200 folded description characters. HTML/case/whitespace normalization follows the existing identity helper; title similarity alone cannot merge records. Untyped board provenance and nil company IDs fail conservatively instead of becoming stronger identity evidence.

Pure discovery filtering keeps owner-explicit criteria separate from profile-expanded provider terms. It preserves the actual age/keyword/location/employment/workplace filter order and fixed exclusion explanations. Unknown publication/location/employment/remote evidence remains visible; profile terms are not silently promoted into explicit local filters. These discovery decisions do not establish application suitability, verified skills, applicant count, identity, resume or submission authority. No personal competencies or employer domains are inferred.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Exact identity/content helpers, original explicit query semantics and formatting applied; atomic SQL job/company/receipt ingestion pending |
| Standard additions | NOT TESTED | 3 declarations: 40 actual identity cases, 32 actual discovery-loop cases, 12 actual Unicode/HTML folding cases, plus untyped provenance refusal; 84 actual comparisons declared |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests: 0; full source precedes combined gates |
| Actual native provider / Mac / install | NOT TESTED | No native provider, account/application/browser, production DB or installation operation in this slice |
| Timing/resources | NOT TESTED | Pure normalization only; no measured performance or memory comparison |

The deferred oracle extracts actual `job_deduplication` functions and the existing discovery service's filtering loop, with actual DTOs and a fictional pinned clock. It imports no ORM, provider HTTP client or application settings. These selected comparisons do not establish current-source acceptance. Fixed failures include `invalid_public_job_identity`, `invalid_discovery_query` and `invalid_normalized_job`; no executed logs or private evidence is published.

Deferred reproduction: `cargo test --locked -p automated-apply-agents --test public_job_intake_rules`, earlier source suites and `uv run --no-project python scripts/run_acceptance.py` after remaining agreed source. Continue owner-fenced atomic job/company/source-observation/local-receipt intake with current context/TTL checks, bounded complete legacy URL inventory and preservation of application history; then parent/child startup orchestration, owner endpoints/dashboard recovery, reviewed Apify execution and remaining runtime/platform source.

Last validated `9c4ace570535a5856184775f8045ee89eafdd05f` remains 193 standard +262 dedicated native PG =455 distinct passes, not current-source evidence. Estimate remains 58% /42%. STOP162, lifetime4/hourly1, three uncertain quarantines, zero strict worker receipts and all identity/PDF/filter/focus constraints remain unchanged. No hosted Actions, merge, cleanup, sending or installation occurred.
