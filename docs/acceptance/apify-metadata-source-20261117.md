# Native Apify metadata — source checkpoint 2026-11-17

Implementation [e209b23c9f53bbaed10ec9df9a99646abb758af8](https://github.com/karanagg166/automated-apply/commit/e209b23c9f53bbaed10ec9df9a99646abb758af8), branch `feat/rust-agent-runtime`, [PR 50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

The native GET-only client inspects public actors, default-build input schemas and bounded store metadata without authorization headers. Only the two fixed account endpoints use the sensitive local bearer header. No arbitrary URL/path, execution POST, run/dataset API, proxy, retry or redirect is exposed. Each streamed JSON response is limited to 1 MiB, individual requests to 15 seconds and composite inspections to 20 seconds. Fixture substitution requires explicit fixture mode and exact numeric loopback. Connected MCP credentials are never reused.

Actual ActorMetadata and ActorInspect schemas are frozen through AST-only extraction. Unique POST schemas support one local component lookup; external references remain inert metadata. Digests use the actual sorted Python JSON representation. Account projection deliberately narrows the legacy arbitrary dictionary output to documented numeric limits/current usage/aggregate totals and validated matching cycle timestamps. It rejects inconsistent cycles, malformed known numbers and missing core totals; unknown fields and daily/service blobs cannot expose account PII. Actor/store schemas and pricing remain bounded public metadata, never reviewed execution input or entitlement.

The field selection was researched against primary [limits](https://docs.apify.com/api/v2/users-me-limits-get) and [usage](https://docs.apify.com/api/v2/users-me-usage-monthly-get) references. This is implementation research, not an authenticated provider observation. Default-build inspection does not verify a reviewed pinned execution build.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Closed metadata projections/client, actual schema generation and formatting applied; owner host/cache/pacing follows |
| Standard additions | NOT TESTED | 9 declarations: 5 synchronous and 4 async; includes 20 actual extractor/digest cases, 8 actual inspect-contract cases, projection/privacy/bounds, account cycles/numbers, fixture-origin refusal, header/path isolation, six HTTP failure modes, missing credential and truncated response |
| Current tests/build/check/lint | NOT TESTED | Executed tests: 0; no compilation, contract drift check or test run in this source phase |
| Actual Mac/provider/account/install | NOT TESTED | No actual account request, actor execution, provider charge, browser operation, production DB access or install |
| Timing/resources | NOT TESTED | Source HTTP/time/size bounds only; no measured latency or memory comparison; no connection pool added |

Fixed codes include `apify_metadata_authentication_required`, `apify_metadata_rate_limited`, `apify_metadata_http_unavailable`, `apify_metadata_response_limit`, `apify_metadata_transport_error`, `apify_account_cycle_changed` and `apify_account_metadata_invalid`. These are source codes; no executed failure logs or private metadata are published.

Deferred reproduction after the complete agreed source: `cargo test --locked -p automated-apply-agents --test apify_metadata`, then the coordinated `uv run --no-project python scripts/run_acceptance.py` gates. Continue owner-fenced inspection pacing/cache/status/routes, reviewed actor execution/discovery orchestration and remaining full source first. Metadata availability never grants dispatch authority or claims current spendable provider credits.

Last validated `9c4ace570535a5856184775f8045ee89eafdd05f` remains 193 standard + 262 dedicated native PG = 455 distinct passes, not current-source evidence. Engineering estimate stays 58% complete / 42% remaining. Last observed STOP revision 162, lifetime 4/hourly 1, three quarantined uncertain admissions, zero strict worker receipts and existing filters/identity/PDF/focus rules are preserved. No hosted Actions, merge, cleanup, send or install occurred.
