# Apollo capability metadata — source checkpoint 2026-11-17

Implementation [4dd980abed10ac3af5386392c8de8bfa9d89cfe6](https://github.com/karanagg166/automated-apply/commit/4dd980abed10ac3af5386392c8de8bfa9d89cfe6), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

Primary research found a concrete legacy compatibility difference: [Apollo's current credit stats](https://docs.apollo.io/reference/view-credit-usage-stats) documents pools inside `credit_usage_stats`; the older Python helper expects a root pool. The native pure parser accepts the documented wrapper and qualified root compatibility, refuses simultaneous/ambiguous representations and never sums unrelated credit pools. Integral nonnegative allowance checks and exact endpoint identity remain conservative. [API stats](https://docs.apollo.io/reference/view-api-usage-stats) examples include inconsistent consumed/remaining figures; those examples are not account entitlement, and inconsistent actual responses remain blocked.

The24-hour operator eligibility guard retains free-account/work-email/endpoint/evidence/time requirements with correct aware-time conversion and naive UTC compatibility. Pure preflight combines eligibility, health flags, unique endpoint rates and the reviewed credit pool, refusing exhausted or unknown allowances. Its result explicitly grants no lookup, purchase or provider request. Fixed transport/controller integration and actual account proof still remain separate source work. [Authentication](https://docs.apollo.io/reference/authentication) and [rate-limit documentation](https://docs.apollo.io/reference/rate-limits) were also reviewed publicly; no private key or account was used.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Pure source integration | PASS (source only) | Rate/pool parsing, documented wrapper compatibility,24-hour eligibility and necessary-condition preflight; formatter applied |
| Standard fixtures | NOT TESTED | 3 new declarations:24 actual endpoint-rate cases;16 actual legacy pool cases plus1 documented-wrapper comparison and3 wrapper refusals;12 actual eligibility cases plus preflight qualification/health/budget assertions |
| PG/frontend count | NOT TESTED | 0 new declarations; this slice has no database/HTTP/UI operation |
| Build/lint/current tests | NOT TESTED | New executed tests0; final coordinated execution remains deferred |
| Actual provider account/HTTP/Mac/install | NOT TESTED | No balance or key probe, lookup, budget mutation or installed change |
| Timing/resources | NOT TESTED | No measured comparison |

Fixed failures include `contact_apollo_capability_evidence_required`, `contact_apollo_eligibility_review_required`, `contact_provider_cooling_down` and `contact_provider_budget_exhausted`. No executed test failure log or private provider payload is published. Final reproduction: coordinated `scripts/run_acceptance.py`, Rust `contact_rules` and subsequent fixed-transport/lookup/recovery integration fixtures after remaining source is complete.

Prior validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 native PG passes,455 distinct; it does not validate this head.58/42 held. Provider readiness remains false. STOP162/lifetime4/hour1/three quarantines/strict worker receipts0, saved filters/identity/PDF/focus/history controls remain. No hosted Actions, merge, cleanup, provider activation, purchase or runtime installation.
