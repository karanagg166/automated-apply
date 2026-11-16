# Attributable research input contracts — source checkpoint 2026-11-17

Implementation [f3f3d6f24d19ab51bcbf2c70e2884162b717bcb5](https://github.com/karanagg166/automated-apply/commit/f3f3d6f24d19ab51bcbf2c70e2884162b717bcb5), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

Actual CompanyObservation/StartupRunRequest and PublicPerson/OfficialPersonEvidence/PeopleQuery schemas are frozen through actual schema declarations without settings, database or provider clients. Native normalization preserves defaults/coercions, strict exact headcounts, count/band consistency, domain/public URL normalization, timezone-aware actual observations, published business-email/source pairs and manual import permission/count rules. Nested lists and expanded JSON are bounded. Schema-only source export was run; validator/oracle acceptance was not.

Public profile URLs, source-reported identities and human-confirmed fields remain input claims. Normalization performs no DNS, page fetch, account verification, budget reserve or provider dispatch. A query allow_paid field is not a transport grant. Unknown fields fail closed; reference URLs are validated, never fetched.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Actual frozen schemas/exporters, native nested research normalization and final people-contract drift stage; formatting applied |
| Standard fixtures | NOT TESTED | 2 declarations:160 actual DTO cases (36 public person/36 official person/32 people query/36 company observation/20 startup run); explicit5-minute time boundary/expanded-byte/no transport grant regressions |
| Native PG/frontend additions | NOT TESTED | No new declarations in this slice; previous source remains unrun |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests0; full source precedes combined gates |
| Actual Mac/provider/runtime/install | NOT TESTED | No provider/account/browser/production/installed action |
| Timing/resources | NOT TESTED | Bounded pure normalization only; no measured runtime comparison |

Fixed failures include `invalid_research_contract`. No executed failure logs, candidate data, mail or raw private evidence are published. Valid structured input is not evidence of a working source adapter or accepted application.

Final reproduction: coordinated `scripts/run_acceptance.py`, Rust `research_contract`, startup/people schema drift and later complete provider/ingestion/PG/UI/browser gates. Commands are documented, not executed now. Continue canonical company/manual evidence ingestion, durable public research/provider status and remaining dashboard/registry/provider/CLI/conversation/eight-platform source before coordinated gates and reviewed migration/install/live evidence. Last validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard+262 native PG=455 distinct passes; not current-head evidence.58/42 held. Last observed STOP162/lifetime4/hour1/three uncertain quarantines/strict worker receipts0 and filters/identity/PDF/focus rules remain unchanged. No hosted Actions, merge, cleanup, sending or installation.
