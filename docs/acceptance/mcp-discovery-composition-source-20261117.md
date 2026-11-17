# Native MCP discovery composition — source checkpoint2026-11-17

Implementation [75b4f9ebad7cf6ea5ae4feb8303c5e1b64464786](https://github.com/karanagg166/automated-apply/commit/75b4f9ebad7cf6ea5ae4feb8303c5e1b64464786), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Source only, untested and uninstalled.

The official pinned stdio bridge now composes eight default source/status/actual-query preview tools with six optional original discovery/read/local-completion tools and two separately optional Apify metadata tools. Both action groups default off in private configuration; direct calls enforce the same opt-ins as discovery. Original dispatch requires real explicit consent and retained nonnil UUIDs; recovery requires a distinct read UUID. Paid opt-in, reviewed Actor/build/schema, full-cap reservations, original context and bounded read lifetime/spacing remain enforced by existing authenticated owner APIs. No separate provider clients, DB pools, grants or ledgers were added. Manual imports, alternate keys and arbitrary provider targets are excluded from this narrow tool surface.

Per-request timeouts cover the configured discovery budget with a persistence margin. Metadata calls have35-second requests/40-second outer deadlines; ordinary reads15/20seconds. The two-request MCP semaphore, shared host long-request slot, private IPC/bearer policy, no proxy/retry/redirect and256KiB response cap remain. Error context selects only validated original UUIDs and disables automatic retry. An oversized/lost response does not undo an operation or its held reservation. The dashboard/API remains the saved-result recovery surface. No complete legacy MCP parity claim follows from this slice.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source/formatting | PASS(source only) | Closed discovery mappings, local/remote annotations, direct-call opt-ins, original IDs, selected error context; cargo fmt only |
| New standard fixtures | NOT TESTED |9: default catalog/direct authority; enabled action annotations; nested schema refs/import exclusion; consent/UUID/native normalization; status versus local complete; distinct read scope; metadata target restrictions; private error context; literal optional configuration |
| New PG/loopback/framed fixtures | NOT TESTED |4: default reads/preview/no dispatch/no writes; original paid replay and local completion share one start/reservation; separate account inspection/status; framed missing-original UUID/false consent |
| Existing fixture alignment | NOT TESTED |Default framed catalog expectation includes eight additions; shared Unix fixture accepts explicit fictional provider config |
| Current test/build/check/lint execution | NOT TESTED |New executed tests0; full agreed source precedes combined gates |
| Real MCP/provider/browser/Mac/install | NOT TESTED |No process handshake, native service, paid start/read/abort, account inspection, provider endpoint or production SQL executed |
| Resources/timing | NOT TESTED |No new pool; existing request limits retained; no measured timing/binary/resource comparison |
| Full runtime/platform parity/live acceptance | NOT TESTED/incomplete |Provider/CLI/local conversation, remaining tool/platform source, inventory/contracts and combined/live gates remain |

No private logs or screenshots published. Deferred reproduction: `cargo test --locked -p automated-apply-agents --lib mcp_bridge`; dedicated disposable PostgreSQL runner includes four ignored fixtures and existing framed/private IPC regressions. These commands are recorded, not executed. Actual source registration/installation, configured optional actions and framed/live proof remain separate acceptance.

Last validated9c4ace570535a5856184775f8045ee89eafdd05f:193 standard Rust+262 dedicated PG=455 distinct prior passes; not current-head validation. Estimate58%/42% held. Queue last observed STOPPED162; lifetime4/hour1, three uncertain jobs quarantined, one fourth admission remaining, strict worker receipts0. Identity/PDF/filter/focus rules retained. No hosted Actions, merge, cleanup, sending/application or installation operation.
