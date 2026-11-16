# Provider professional identity projection — source checkpoint 2026-11-17

Implementation [0c0c8a0151c7d7917358c2a1c5e926fde656c5e7](https://github.com/karanagg166/automated-apply/commit/0c0c8a0151c7d7917358c2a1c5e926fde656c5e7), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

Actual PersonObservation and ContactEnrichmentRequest DTOs are frozen through AST extraction, including the original URL normalizer, without loading settings or provider modules. The native projection retains defaults, omission/null behavior, bounded text, booleans/UUIDs, public URLs and the existing Speedate-backed timestamp normalization. Apollo observations require matching company-domain evidence and a non-obfuscated full name; SignalHire observations require a current matching employer. Returned mailboxes stay provider-reported even when a vendor calls them verified. Personal emails, phones and vendor blobs do not enter the projected observation.

Native handling additionally refuses conflicting SignalHire professional profiles or multiple distinct company work mailboxes instead of choosing one. Obfuscated Apollo names are withheld. Public company-website host identity can normalize HTTP website syntax without fetching it; provider network origins remain a separate fixed-transport concern. Business-email host comparison now handles IDNA-equivalent company domains after canonical email validation. These are conservative native qualifications, not an independent mailbox, identity or provider-account verification.

Primary [SignalHire Person](https://docs.signalhire.com/person-api/retrieve-person), [withoutWaterfall](https://docs.signalhire.com/person-api/without-waterfall), [credits](https://docs.signalhire.com/person-api/credits) and [authentication](https://docs.signalhire.com/authentication) documentation were refreshed. Future transport uses one identifier/no callback and preserves unexpected asynchronous IDs without resubmission. This checkpoint implements projection only; no provider call was made.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Actual schemas/exporter, DTO normalization, professional identity/company-mailbox projection and IDNA comparison; formatter/source generator applied |
| Standard fixtures | NOT TESTED | 4 new declarations:32 actual observation DTO cases;24 actual request DTO cases;16 actual Apollo method projections;16 actual SignalHire async method projections with fictional request transport; extra redaction/conflicting identity/mailbox/IDNA assertions |
| PG/frontend count | NOT TESTED | 0 new declarations; source-only pure normalization |
| Current-head build/lint/tests | NOT TESTED | New executed tests0; all suites remain deferred until full source integration |
| Actual provider/account/Mac/install | NOT TESTED | No network lookup, API key/balance probe, real person record or installed change |
| Timing/resources | NOT TESTED | No measured comparison |

The existing actual-source fixtures use fake in-process provider methods; they do not establish actual API acceptance. Fixed failures include `invalid_contact_person_contract`, `contact_provider_identity_conflict` and `contact_provider_mailbox_conflict`. Source review preserved absent-list defaults and distinguished malformed vendor fields from usable observations. No executed failure log, private person fields or raw provider payload is published.

Final reproduction: coordinated `scripts/run_acceptance.py`, contact schema drift and Rust `contact_person` tests plus earlier contact/provider rules. Next complete fixed provider transport, fresh capability/one-time dispatch guards, result identity ingestion/controller, grounded outreach and remaining full plan before combined integration/build/browser gates. Prior validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 native PG passes,455 distinct; it does not validate this head.58/42 held; provider readiness false. STOP162/lifetime4/hour1/three quarantines/strict worker receipts0 and saved filters/identity/PDF/focus/history controls remain. No hosted Actions, merge, cleanup, purchase, provider activation or runtime installation.
