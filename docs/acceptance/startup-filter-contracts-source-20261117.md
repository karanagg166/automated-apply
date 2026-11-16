# Actual startup filters — source checkpoint 2026-11-17

Implementation [6101f3c325baaa7006e9a5767a81a5ce6c54b0a3](https://github.com/karanagg166/automated-apply/commit/6101f3c325baaa7006e9a5767a81a5ce6c54b0a3), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

Actual StartupFilters and ShortlistInput schemas are frozen through AST-only loading without settings/services. Native normalization preserves defaults, optional values, integer/boolean/score/time/UUID coercions, text-list trimming, omission semantics and cross-field count bounds. Bounded GET parsing retains repeated list order and refuses duplicate scalars or unknown fields. The final runner gains a startup-contract drift stage.

Pure source ports preserve explicit size bands, exact versus range count filters, unknown-size handling, requested role/location/remote choices and industry aliases with Python-compatible word boundaries. A range never becomes a factual headcount, and AI cannot match retail. Early-stage stays explicit/default false. Legacy max50 default is preserved in the DTO; the existing frontend explicitly submits max_employees=null when no size cap is chosen. No early-stage-only restriction is introduced.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Actual DTO exporter/frozen schemas, native normalization/query parsing, explicit pure filters and final drift stage; formatting applied |
| Standard fixtures | NOT TESTED | 3 declarations:68 actual DTO cases (56 filter/12 shortlist);110 actual normalizer cases (64 size allowance/12 size bands/6 roles/16 industries/12 location choices); GET list/scalar/query bounds |
| Native PG/frontend additions | NOT TESTED | No new declarations in this slice; existing source remains unrun |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests0; complete source precedes combined gates |
| Actual Mac/provider/runtime/install | NOT TESTED | No provider/account/browser/production/installed action |
| Timing/resources | NOT TESTED | Pure bounded source only; no measured runtime comparison |

Fixed failures include `invalid_startup_contract`, `invalid_startup_query` and `invalid_startup_size_record`. No executed failure log, candidate data, mail or raw private evidence is published. Source export/formatting does not validate contract parity.

Final reproduction: coordinated `scripts/run_acceptance.py`, Rust `startup_contract`, later complete startup PG/UI/browser gates. Commands are documented, not executed now. Continue actual company size/hiring qualification, ranking/catalog/shortlists and public discovery; remaining dashboard/registry/provider/CLI/conversation/eight-platform source precedes combined gates and reviewed migration/install/live evidence. Last validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard+262 native PG=455 distinct passes; not current-head evidence.58/42 held. STOP162/lifetime4/hour1/three uncertain quarantines/strict worker receipts0 and current filters/identity/PDF/focus controls remain. No hosted Actions, merge, cleanup, sending or installation.
