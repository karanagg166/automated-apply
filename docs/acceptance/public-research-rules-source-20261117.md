# Professional research rules — source checkpoint 2026-11-17

Implementation [3834099421594938700bd132812f29b4df92579c](https://github.com/karanagg166/automated-apply/commit/3834099421594938700bd132812f29b4df92579c), branch `feat/rust-agent-runtime`, [PR 50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled pure source.

The native parser now preserves existing search-index queries, selected role aliases, Python Unicode case/word/name rules, canonical professional URL projection and same-name ambiguity handling. Canonical URLs are deduplicated before ambiguity checks. Public search titles remain source-reported candidates; official results require the exact company domain, named role and company attribution. Every generated official result remains human_confirmed=false with explicit observation time and permission provenance. Raw vendor snippets are excluded from output. Limits cap result count, expanded response bytes and text processing. No URL fetch, provider transport, budget reservation or application authority exists in these pure rules.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Pure query/candidate/official/ambiguity rules and research limitations recorded; formatting applied |
| Standard fixtures | NOT TESTED | 2 declarations: 60 actual adapter/query cases (40 public, 20 official), 8 actual ambiguity cases, plus bounds/privacy/no-authority assertions |
| Native PG / frontend additions | NOT TESTED | None in this slice; durable admission/ingestion follows |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests: 0; complete source precedes combined gates |
| Actual Mac/provider/install | NOT TESTED | No credential, account, provider execution, browser, production or installation action |
| Timing/resources | NOT TESTED | Bounded source only; no measured performance comparison |

Primary research is recorded in [completion research](../plans/completion-research-20261116.md). Apify's official run/dataset/account references were read. Serper's public page supplied result examples, but `/docs` returned 404 and the playground did not expose an authenticated request contract to this reader. The repository's existing fixed request contract remains a compatibility input, with no new live or entitlement claim. Research did not execute a provider operation.

Sanitized codes include `invalid_public_research_record`, `public_search_record_invalid`, `public_research_response_limit`, `public_research_permission_required` and `public_research_official_domain_required`. No executed failure logs or private evidence are published.

Deferred reproduction: `cargo test --locked -p automated-apply-agents --test public_research_rules`, then the coordinated `uv run --no-project python scripts/run_acceptance.py` and later full research/provider/install/live gates. Continue original search admissions, retained findings, conservative identity ingestion and remaining agreed full source.

Last validated `9c4ace570535a5856184775f8045ee89eafdd05f` remains 193 standard + 262 dedicated native PG = 455 distinct passes, not current-source evidence. Estimated completion remains 58% / 42%. Last observed STOP revision 162, lifetime allowance 4/hourly 1, three uncertain quarantines, zero strict worker receipts and all current filters/identity/PDF/focus rules are unchanged. No hosted Actions, merge, cleanup, sending or installation occurred.
