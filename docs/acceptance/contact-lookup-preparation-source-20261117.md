# Atomic contact lookup preparation — source checkpoint 2026-11-17

Implementation [42ce99bab75e813f81ae01118d2b6164a493ead9](https://github.com/karanagg166/automated-apply/commit/42ce99bab75e813f81ae01118d2b6164a493ead9), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

Per-target preparation rechecks the original native run, current company/contact/version, reviewed provider order and role/cache policy. Paid contact enrichment requires a canonical existing professional profile; name-only enrichment is refused. Primary Apollo search requires bounded matching local inventories to be empty. Per-run credit and unique-person limits apply before work. Fallback requires a retained usable completed result without business email; a prepared, failed or unknown first result cannot justify it.

Shared owner/SERIALIZABLE transactions commit the unique legacy lookup claim, private intent and positive credit reservation together. The credit ledger now exposes a crate-internal same-transaction helper while retaining its separate committed entry point. Every new prepared intent records zero POST admissions and no dispatch authorization. Running/unknown/failed/queued/billing-uncertain claims stay non-replayable even after expiry. A new explicit run may replace only a known completed/not-found expired cache claim; its prior row and original intent/history are preserved, and prior reserved credits are never refunded. No provider request is sent by preparation.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Target/profile/plan/cap guards, atomic claim/intent/credit preparation, prior-claim archive and zero-credit search safeguards; formatter applied |
| Standard fixtures | NOT TESTED | 1 new declaration with14 actual profile-normalizer comparisons plus public-domain scope assertions |
| Dedicated native PostgreSQL | NOT TESTED | 10 new declarations: exact atomic preparation/no dispatch; repeated/abandoned claim;4 quarantined expired states; known completed cache replacement/history/no refund; current role/cache/profile/authorization; person/order/fallback; monthly cap rollback;2 lookup-row ACK faults; intent ACK rollback; empty-inventory zero-credit search |
| Earlier budget/run fixtures | NOT TESTED | Same existing declarations exercise refactored helper contracts in the final gate; no duplicated pass count |
| Current-head build/lint/tests | NOT TESTED | New executed tests0; final combined execution remains deferred |
| Provider dispatch/controller/identity ingestion | NOT TESTED / INCOMPLETE | A prepared claim is not a one-time dispatch grant; fixed transport/current capability/final dispatch guard and result ingestion remain source work |
| Actual account/Mac/install/timing/resources | NOT TESTED | No private lookup, real credits, browser/service change or measured comparison |

Fixed failures include `contact_paid_lookup_authorization_required`, `contact_professional_identifier_required`, `contact_lookup_already_claimed`, `contact_fallback_evidence_required`, `contact_run_person_limit_reached`, `contact_provider_run_budget_exhausted` and `contact_lookup_write_ack_failed`. Unknown/malformed private intent payloads fail closed. No executed failure log, private target record, provider key or raw journal is published.

Final reproduction: coordinated `scripts/run_acceptance.py`, Rust `contact_rules`, dedicated `contact_lookup_*` cases, original budget/run cases and later fixed-provider dispatch/recovery fixtures once remaining source is integrated. Complete provider/identity/outreach/registry/conversation/platform work before combined tests. Prior validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 native PG passes,455 distinct; it does not validate this head.58/42 held; provider dispatch readiness remains false. STOP162/lifetime4/hour1/three quarantines/strict worker receipts0 and saved filters/identity/PDF/focus/history controls remain. No hosted Actions, merge, cleanup, purchase, provider activation or runtime installation.
