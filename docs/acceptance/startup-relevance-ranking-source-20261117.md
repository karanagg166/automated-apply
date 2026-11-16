# Saved startup relevance ranking — source checkpoint 2026-11-17

Implementation [d3c5af031cf9d466c760c0698664c424d77ea9c4](https://github.com/karanagg166/automated-apply/commit/d3c5af031cf9d466c760c0698664c424d77ea9c4), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

Pure company relevance now reuses the existing deterministic domain discovery matcher for saved profile/job alignment, then applies the actual company technology, size-band, hiring, location, stage and supported-contact weights. It preserves reason order, missing facts, exclusions, profile version and bounded numeric output. Unknowns and excluded jobs cannot silently become positive candidate evidence. Matcher structures contain professional search facts; no candidate contact/login fields enter output or inference.

The score remains explicitly relevance_not_probability. It grants no application, submission, mailbox verification or sending authority. Missing profiles retain missing-fact findings instead of inferred suitability. Catalog/history filtering, database detail/search/shortlists and provider discovery remain subsequent integration work; this module has no IO.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Bounded pure relevance port/reused domain matcher, exact reasons/missing/exclusions and profile version; formatting applied |
| Standard fixtures | NOT TESTED | 2 declarations:32 actual rank_startup comparisons using the actual legacy job matcher; bounds/no authority regression |
| Native PG/frontend additions | NOT TESTED | No new declarations in this slice; previous source remains unrun |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests0; complete source precedes combined gates |
| Actual Mac/provider/runtime/install | NOT TESTED | No provider/account/browser/production/installed action |
| Timing/resources | NOT TESTED | Reused pure scorer by source design; no measured runtime comparison |

Fixed failures include `invalid_startup_ranking_record` and `startup_ranking_inventory_limit`. No executed failure log, candidate data, mail or raw private evidence is published. A fixture declaration and a relevance score establish no operational acceptance.

Final reproduction: coordinated `scripts/run_acceptance.py`, Rust `startup_ranking`, later complete catalog/shortlist PG/UI/browser gates. Commands are documented, not executed now. Continue derived startup detail/search/shortlist persistence, public discovery and remaining dashboard/registry/provider/CLI/conversation/eight-platform source, then coordinated gates and reviewed migration/install/live evidence. Last validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard+262 native PG=455 distinct passes; not current-head evidence.58/42 held. Last observed STOP162/lifetime4/hour1/three uncertain quarantines/strict worker receipts0 and current filters/identity/PDF/focus rules are not changed by this slice. No hosted Actions, merge, cleanup, sending or installation.
