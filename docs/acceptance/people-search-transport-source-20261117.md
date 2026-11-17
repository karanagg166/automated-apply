# Bounded search transport and retained findings — source checkpoint 2026-11-17

Implementation [5a43ac52f64be2fc667c6b1e0d3c413c92f603bf](https://github.com/karanagg166/automated-apply/commit/5a43ac52f64be2fc667c6b1e0d3c413c92f603bf), branch `feat/rust-agent-runtime`, [PR 50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source. Paid local ingestion and host/dashboard integration remain pending.

The search transport now consumes only an original opaque grant, bound to its exact request, configuration, original deadline and invocation. It uses one fixed Serper POST with sensitive header credentials, no proxy, retries or redirects, a 15-second total deadline and a 1-MiB streamed response bound. Endpoint substitution requires an explicit loopback fixture URL and is rejected in production. Result URLs are never requested.

Only parsed professional evidence reaches the finding journal. Official candidates remain unconfirmed; raw snippets, provider diagnostics, keys and permission URLs are excluded from public retained output. Recording commits the selected finding and original reservation terminal state before later local ingestion. A rate response also sets monotonic cooldown. Response loss or malformed data retains unknown cost and the full local allowance. Replay and GET never recreate the consumed transport grant. Provider balance and actual charge remain unverified.

The controller composes manual import or original paid admission/transport/finding, keeping network work outside database transactions. Paid results currently report `persistence_status: not_imported`; they are not presented as persisted contacts. Current company changes do not discard the original transport finding. The next dependency checks current input/settings/company context before conservative local completion.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Fixed bounded transport, original grant consumption, selected finding journal/controller, sanitized reads and exact terminal timestamp binding; formatting applied |
| Standard additions | NOT TESTED | 1 endpoint boundary declaration added to people_research_settings; file now has 3 declarations |
| Native PG / loopback HTTP | NOT TESTED | 9 declarations: official finding/replay/no import; public candidates; rate/cooldown; auth/redirect/invalid/missing/oversized; raw connection loss; no held fence/company change; cancellation; finding/terminal ACK failure; retained privacy |
| Host / frontend additions | NOT TESTED | None in this slice; UUID owner endpoint and durable dashboard recovery remain pending |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests: 0; complete source precedes combined gates |
| Actual Mac/provider/install | NOT TESTED | No live credential, account, provider execution, real budget, browser, production or installation action |
| Timing/resources | NOT TESTED | Source deadlines/byte/connection bounds only; no measured performance comparison |

Fixed codes include `public_research_original_grant_changed`, `public_research_rate_limited`, `public_research_provider_authentication_required`, `public_research_response_limit`, `public_research_invalid_provider_response`, `public_research_finding_context_changed` and `public_research_write_ack_failed`. No executed failure logs or private evidence are published.

Deferred reproduction: `cargo test --locked -p automated-apply-agents --test people_research_settings`, complete dedicated disposable PG `people_search_*` plus shared budget/identity suites, then `uv run --no-project python scripts/run_acceptance.py` and later provider/UI/install/live gates. Continue retained finding-to-contact completion, owner endpoint/dashboard recovery and the remaining agreed full source. Existing source compatibility for the Serper request is not a current account/API entitlement verification; see the recorded primary research limitations.

Last validated `9c4ace570535a5856184775f8045ee89eafdd05f` remains 193 standard + 262 dedicated native PG = 455 distinct passes, not current-source evidence. Estimated completion remains 58% / 42%. Last observed STOP revision 162, lifetime allowance 4/hourly 1, three uncertain quarantines, zero strict worker receipts and all current filters/identity/PDF/focus rules remain unchanged. No hosted Actions, merge, cleanup, sending or installation occurred.
