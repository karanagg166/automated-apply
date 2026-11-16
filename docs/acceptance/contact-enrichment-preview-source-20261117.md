# Contact enrichment planning — source checkpoint 2026-11-17

Implementation [175f63e76948668af27904f126dafa4504df52f5](https://github.com/karanagg166/automated-apply/commit/175f63e76948668af27904f126dafa4504df52f5), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

The native owner API adds the existing local enrichment-preview, provider-configuration/budget and retained-run routes. Actual EnrichInput defaults/coercions are frozen without service/settings imports. Read-only repeatable snapshots implement saved role aliases/cache lookup policy, retained discovery targets and conservative no-fallback decisions. Inventories cap at1000 contacts and100 discovered people, with truncation disclosed. `allow_paid` in a preview reserves nothing and dispatches no request. Company evidence and historical usage fields are whitelisted; historical errors become a fixed review code/count. Candidate patterns retain a candidate label/disclaimer and never become verified mailboxes.

Provider configuration, local reserved estimates, unknown provider balance, live eligibility and native execution readiness remain separate. Current primary documentation distinguishes [Apollo search](https://docs.apollo.io/reference/people-api-search) from [credit-consuming match enrichment](https://docs.apollo.io/reference/people-enrichment); eligibility and account-specific caps still gate dispatch. [SignalHire documentation](https://docs.signalhire.com/overview) distinguishes synchronous withoutWaterfall Person requests from asynchronous modes. Product availability does not expand this adapter's supported operations or grant account access. Research involved public documentation only.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Three owner routes, saved status/preview/run projection, actual frozen DTO and local-first rules; formatting applied |
| Standard fixtures | NOT TESTED | 2 new declarations:29 actual EnrichInput comparisons;12 actual role +12 actual cache lookup +48 actual fallback decision comparisons |
| Dedicated native PostgreSQL/HTTP | NOT TESTED | 8 declarations: preview/no reservation; role aliases/corrected contacts; qualified empty-company planning; credentials/budget/entitlement; inventory/evidence bounds; saved run/error/usage/candidate qualification; no owner lock/writes; auth/method/DTO/query/missing run |
| Current-head build/lint/tests | NOT TESTED | New executed tests0; full source must precede the combined acceptance |
| Actual provider/Mac/runtime/install | NOT TESTED | No key validation, real person lookup, purchase, provider balance probe or installed change |
| Timing/resources | NOT TESTED | Bounded inventory/query structure only; no measured comparison |

Source review corrected SQL NULL handling for oversized historical runs; these fail with `invalid_contact_saved_record` instead of trying to decode a missing payload. Other fixed codes include `invalid_contact_enrichment`422 and `contact_enrichment_run_not_found`404. No executed failure log exists. Private source payloads, credentials, candidate data and raw logs are not published.

Final reproduction: coordinated `scripts/run_acceptance.py`, actual contact schema drift stage, Rust `contact_rules` and disposable `contact_enrichment_*`/`contact_provider_*` PostgreSQL/HTTP cases, then combined frontend/backend/extension contracts and build journeys. Durable lookup/credit admission, provider IO/identity reconciliation and grounded local outreach remain source work before final tests. Native provider execution readiness is explicitly false until that integration is complete.

Private continuity snapshotfed847dc77c992e4321b8c6d44c7c30737254fe09283f4ef485f5290de1d7950 at2026-11-16T19:24:15Z preserves104 indexed/6 available/98 missing transcripts; no missing-byte/sidebar recovery claim or account/session identity rewrite. Prior validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 native PG passes,455 distinct; it does not validate this head.58/42 held. STOP162/lifetime4/hour1/three quarantines/strict worker receipts0 and saved filters/identity/PDF/focus/history controls remain. No hosted Actions, merge, cleanup or provider activation.
