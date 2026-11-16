# Completion research and constraints — 2026-11-16

Primary sources were reread before the remaining implementation. These are design inputs,
not evidence of an installed service, authenticated account, provider entitlement or receipt.
Keep pinned Cargo/pnpm dependencies unless a needed implementation justifies a change.

| Subject | Primary reference | Consequence for this implementation |
| --- | --- | --- |
| Native framing/origin | [Chromium native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging) | UTF-8 JSON uses32-bit native-endian length framing; host responses cap1MiB. Caller origin and allowed extension identity must be validated; application limits remain stricter |
| Edge native host | [Microsoft Edge native messaging](https://learn.microsoft.com/en-us/microsoft-edge/extensions/developer-guide/native-messaging) | Same stdio model; native host manifest is separate from extension manifest and macOS executable paths are absolute. Edge requires explicit installation/account/focus evidence |
| SQLx savepoints | [SQLx PostgreSQL transaction source0.9.0](https://docs.rs/crate/sqlx-postgres/0.9.0/source/src/transaction.rs) | Nested begin creates savepoints; do not confuse rollback of task work with rollback of an enclosing lease/invalidation |
| PostgreSQL snapshots | [PostgreSQL17 transaction isolation](https://www.postgresql.org/docs/17/transaction-iso.html) | Read committed statements can see different snapshots; task metadata uses repeatable read, while mutations lock/reload. Sequence counters are not rolled back, useful for no-replay evidence |
| MCP authorization/hints | [MCP tools specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/server/tools.mdx), [annotation schema](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-06-18/schema.mdx) | Tool annotations are hints, not grants. Retain runtime authorization, budgets and durable intent independently; do not silently change the pinned SDK/wire version |
| Apify hosted MCP | [Apify MCP documentation](https://docs.apify.com/mcp) | Current four public discovery/docs tools can operate without token; actor execution and storage require authentication. Runtime actor calls additionally need owner budget and allowlist. No default broad tool catalog or paid run |
| Gmail draft creation | [Google users.drafts.create](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.drafts/create) | Fixed POST creates a DRAFT; compose is among supported scopes. App transport must still exclude sending; use exact owner content review and durable ambiguous-write reconciliation |
| Telegram polling | [Telegram Bot API](https://core.telegram.org/bots/api) | A larger getUpdates offset confirms earlier updates; persist command effects/cursor atomically and preserve original owner binding. Network acceptance of a message is not owner-read proof |
| Himalayas data | [Official jobs API](https://himalayas.app/docs/remote-jobs-api) | Public read endpoints do not establish account access. Preserve source credit and API applicationLink for Apply; exact rate metadata and fresh vacancy checks are adapter concerns |
| WWR data | [Official public RSS](https://weworkremotely.com/remote-job-rss-feed) | Public feed is documented for reuse with attribution/backlinks. Ingested job records are neither account verification nor employer application receipts |

The SQLx aggregate type page returned a web access error; the pinned official crate source
above was available and used instead. No private provider API, cookie copying, stealth,
CAPTCHA/rate bypass, owner-window interaction or account grant was used for this research.

Source review also found the final runner lacks some browser/UI and Python PostgreSQL
integration stages; add those before final acceptance. The source API inventory reports243
decorated declarations in21 files, not243 required active endpoints or a migration percentage.
Reconcile actual router mounts, disabled sending contracts, OpenAPI and callers during the
coverage pass. See [the implementation structure](completion-execution-20261116.md).

PostgreSQL fixture shutdown follow-up: [official PostgreSQL17 pg_ctl documentation](https://www.postgresql.org/docs/17/app-pg-ctl.html) confirms status3 means no server, status4 means inaccessible/missing data directory; fast shutdown rolls back transactions and disconnects clients. The source harness cleans its own temporary cluster only after confirmed shutdown/no-server status, preserving it on uncertain shutdown. No fixture was started during this research.
