# Research owner API and dashboard recovery — source checkpoint 2026-11-17

Implementation [4b2c67632d36171e4c9a2d930605fc216a8cf8ca](https://github.com/karanagg166/automated-apply/commit/4b2c67632d36171e4c9a2d930605fc216a8cf8ca), branch `feat/rust-agent-runtime`, [PR 50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

The native owner API now connects the complete research controller through UUID PUT/GET requests under `/api/v1/rust-agent/research/people/requests/{id}` and a saved status GET. Unkeyed native legacy search POST returns 428 before database/provider work. The owner boundary, existing transient permit and temporary connection budget remain shared. Saved results expose their original company UUID when available. Status separates configured credentials/rights and local request limits from live verification or provider balance. The shared BFF policy includes only the exact new methods/paths; existing session/CSRF controls remain.

The dashboard persists only company/request UUIDs before a request, uses browser Web Locks across cooperating tabs, reads a prior request first and retains its pointer after response loss. A missing durable admission requires fresh explicit approval before PUT. An existing successful finding may retry only guarded local completion with the same request. Unknown/held results cannot silently become a fresh paid search. Preparing another search requires explicit review, an independent terminal GET and exact pointer comparison; database history and consumed allowances are retained. UI text qualifies saved/held/uncertain results and no longer dumps raw runtime JSON.

Web Locks design/support was checked against [Mozilla documentation](https://developer.mozilla.org/en-US/docs/Web/API/Web_Locks_API) and its [primary compatibility data](https://raw.githubusercontent.com/mdn/browser-compat-data/main/api/LockManager.json). Mutation refuses before network work if browser coordination is unavailable. No owner browser was opened or tested. The new browser journey will generate an isolated fictional screenshot only when final gates run; no current screenshot evidence is claimed.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | UUID owner API/status, unkeyed refusal, company binding, shared budget, generated BFF policy, UUID-only dashboard recovery/review and qualified UI; formatting applied |
| Rust standard additions | NOT TESTED | 1 closed route/method declaration |
| Native PG / loopback HTTP | NOT TESTED | 6 declarations: saved status/unkeyed no work; full PUT/GET/replay/company binding; auth/method/query/body bounds; shared transient contention; manual without remote settings; client disconnect recovery/no second provider POST |
| Frontend unit additions | NOT TESTED | 14 declarations: 10 durable recovery/helper cases, 3 UI consent/status/storage cases, 1 exact gateway policy case |
| Browser fixture additions | NOT TESTED | 1 real-browser Web Locks/tab/reload journey with intercepted fictional backend: server commit before response loss, shared UUID recovery, zero second PUT/legacy POST; screenshot deferred |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests: 0; complete source precedes combined gates. HTTP policy copies generated, not checked |
| Actual Mac/provider/install | NOT TESTED | No live credential, account, provider execution, real budget, owner browser, production or installation action |
| Timing/resources | NOT TESTED | Existing transient/connection bounds in source; no measured runtime comparison |

Fixed findings include `public_research_request_id_required`, `public_research_method_not_allowed`, `invalid_public_research_query`, `public_research_request_conflict` and `bounded_background_request_running`. A formatter caught and corrected a syntax typo in a new frontend fixture; that was source formatting, not an executed test. No executed failure logs, private data or raw provider diagnostics are published.

Deferred reproduction: Rust people_research_owner, full dedicated disposable PG `people_research_owner_*`/`people_search_*`/`people_*`; frontend people-research unit/gateway/UI declarations; isolated people-research-recovery browser journey after build; then `uv run --no-project python scripts/run_acceptance.py` and applicable install/provider/live gates. Continue startup job-led/provider orchestration, Apify runtime integration, remaining dashboard/registry/provider/CLI/conversation/eight-platform full source before coordinated validation. A written endpoint or browser fixture is not operational acceptance.

Last validated `9c4ace570535a5856184775f8045ee89eafdd05f` remains 193 standard + 262 dedicated native PG = 455 distinct passes, not current-source evidence. Estimated completion remains 58% / 42%. Last observed STOP revision 162, lifetime allowance 4/hourly 1, three uncertain quarantines, zero strict worker receipts and all current filters/identity/PDF/focus rules remain unchanged. No hosted Actions, merge, cleanup, sending or installation occurred.
