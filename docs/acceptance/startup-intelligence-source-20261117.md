# Company size and hiring qualification — source checkpoint 2026-11-17

Implementation [84538f12a9bb55a212f9bf41755cf158ee765fe1](https://github.com/karanagg166/automated-apply/commit/84538f12a9bb55a212f9bf41755cf158ee765fe1), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

Pure company intelligence now resolves the latest saved size claim per source identity, prefers current human-confirmed claims and checks concurrent exact-count/range conflicts. Overlapping ranges retain a reported snapshot and never become an inferred headcount. Source-labeled historical evidence remains distinguishable from the current selected result. Inventories and public primitive fields are bounded.

Hiring qualification combines saved observed jobs, current attributable board evidence, explicit current-listing claims, expiry/closed markers and fresh company statements. Missing jobs yield hiring_unknown. Two deliberate conservative corrections are separate from legacy parity: future observations do not count as fresh evidence, and a stored not_currently_hiring statement needs its recorded authoritative flag. Equal-time statements preserve original input precedence. This pure module is not yet a wired startup catalog/shortlist service.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Bounded size/hiring qualification and intentional future/negative-statement safeguards; formatting applied |
| Standard fixtures | NOT TESTED | 3 declarations:24 actual company-size cases;26 actual hiring cases; separate future/authoritative-negative/inventory regressions |
| Native PG/frontend additions | NOT TESTED | No new declarations in this slice; earlier source remains unrun |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests0; full source precedes combined gates |
| Actual Mac/provider/runtime/install | NOT TESTED | No provider/account/browser/production/installed action |
| Timing/resources | NOT TESTED | Bounded pure source only; no measured runtime comparison |

Fixed failures include `invalid_startup_intelligence_record` and `startup_intelligence_inventory_limit`. No executed failure logs, candidate data, mail or raw private evidence are published. An evidence status is not application, delivery or employer acceptance.

Final reproduction: coordinated `scripts/run_acceptance.py`, Rust `startup_intelligence`, later full catalog/shortlist PG/UI/browser gates. Commands are documented, not executed now. Next: profile-aware relevance ranking, derived startup detail/search/shortlists, public discovery and remaining dashboard/registry/provider/CLI/conversation/eight-platform source, then coordinated gates and reviewed migration/install/live evidence. Last validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard+262 native PG=455 distinct passes; not current-head evidence.58/42 held. STOP162/lifetime4/hour1/three uncertain quarantines/strict worker receipts0 and current filters/identity/PDF/focus rules remain. No hosted Actions, merge, cleanup, sending or installation.
