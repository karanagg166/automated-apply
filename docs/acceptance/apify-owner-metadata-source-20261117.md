# Owner Apify inspection and saved status — source checkpoint 2026-11-17

Implementation [27050a09624bbf4a7d8f3a7b3177a3327a9cd842](https://github.com/karanagg166/automated-apply/commit/27050a09624bbf4a7d8f3a7b3177a3327a9cd842), branch `feat/rust-agent-runtime`, [PR 50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

The original owner GET status, POST account inspection and POST allowlisted actor inspection paths now connect the bounded native metadata client. They reuse the existing transient permit and one temporary connection. Exact methods/query/body validation and owner transport authentication remain; existing BFF policy already permits these exact routes, so it was not broadened. Missing credentials and unlisted actors fail before admission or provider work.

The original ten-second `apify_metadata` access window commits under owner-first SERIALIZABLE, with independent post-trigger ACK, before remote GETs. Transport holds no owner transaction. Superseded account claims cannot overwrite newer observations. The separate native cache stores only closed numeric/cycle projections with private credential-context and content hashes; original legacy cache is preserved. Saved status uses one read-only repeatable snapshot for cache and local USD reservations, never a provider refresh. Changed credential contexts, invalid/tampered/oversized cache and old unbound observations are explicitly qualified. Unknown fields from old cache are projected out. Inspection age/staleness and local versus provider accounting remain distinct.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Configuration, owner routing, pacing, guarded cache, saved local budget/status, sanitized error mapping and formatting applied |
| Standard additions | NOT TESTED | 2 declarations: closed owner routes/methods and private allowlist/settings projection; earlier 9 metadata declarations remain unrun |
| Native PG / loopback HTTP | NOT TESTED | 8 declarations: saved inspection/read-only status; missing credential/unlisted actor/public inspection; committed pacing/free owner mutex; pacing ACK rollback; cache ACK rollback with retained pace; changed credential/tamper/legacy privacy/oversized cache; superseded completion; actual owner HTTP authentication/method/query/rate boundary |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests: 0; full source precedes combined gates |
| Actual Mac/provider/install | NOT TESTED | No authenticated Apify request, actual budget/account operation, owner browser activity, installation or production database change |
| Timing/resources | NOT TESTED | No measured comparison; unchanged source peak connection budget 4 with Telegram /3 without, sharing the transient slot |

Fixed codes include `apify_metadata_access_rate_limited`, `apify_metadata_write_ack_failed`, `apify_metadata_inspection_superseded`, `apify_metadata_claim_outcome_unknown`, `apify_metadata_cache_outcome_unknown` and `apify_actor_metadata_not_allowlisted`. No executed failure logs, token, account identity or raw private payload is published.

Deferred reproduction: `cargo test --locked -p automated-apply-agents --test apify_metadata`, dedicated disposable PG `apify_metadata_*`, then `uv run --no-project python scripts/run_acceptance.py` after the remaining agreed source. Continue reviewed actor execution/budget/retained-result lifecycle, public job adapters/startup orchestration and remaining dashboard/registry/CLI/conversation/platform source before final coordinated tests and operational acceptance. Metadata success will not establish Actor/MCP execution or application acceptance.

Last validated `9c4ace570535a5856184775f8045ee89eafdd05f` remains 193 standard +262 dedicated native PG =455 distinct passes, not current-source evidence. Completion estimate remains 58% /42%. Last observed STOP revision162, lifetime4/hourly1, three uncertain quarantines, zero strict worker receipts and current filters/identity/PDF/focus rules remain unchanged. No hosted Actions, merge, cleanup, sending or installation occurred.
