# Completion research and constraints — 2026-11-16

Fallback deadline source review2026-11-17: pinned local reqwest0.12.28 `async_impl/request.rs` documents RequestBuilder::timeout as covering connecting through response body completion and overriding the client timeout. Use that request deadline for cloud transports; keep ledger COMMIT outside cancellation. Local/CLI transport already has separate bounded lifetime. This is local library/source review, no provider/daemon request or test.

CLI follow-up2026-11-17: read primary [AGY CLI reference](https://antigravity.google/docs/cli/reference/) and [Tokio1.54.1 Command](https://docs.rs/tokio/1.54.1/tokio/process/struct.Command.html). The CLI documents stream-json input/output, schema path, print timeout and disabling slash expansion; useG1Credits defaults false. Sandbox may be unavailable, so its flag is not containment proof. Preserve exact tool-free init/profile/settings checks independently. Tokio children survive ordinary handle drop by default; use kill_on_drop plus an owned process group guard and bounded pipe drains. This is documentation-only research; no installed CLI, model, owner config, login, quota or generation was probed.

Apify execution research follow-up2026-11-17: reread official [Run Actor](https://docs.apify.com/api/v2/actors-runs-post), [run status](https://docs.apify.com/api/v2/actor-run-get), [abort](https://docs.apify.com/api/v2/actor-run-abort-post), [dataset items](https://docs.apify.com/api/v2/dataset-items-get), [Actor identity](https://docs.apify.com/api/v2/actor-get) and [build metadata](https://docs.apify.com/api/v2/actors-build-get). maxItems is a pay-per-result billing bound, not a returned-row bound; retain actor input and local pagination/bytes caps independently. Keep the existing reviewed PAY_PER_EVENT-only policy despite broader provider cap documentation. Build selection accepts a build number; bind returned run/build identity rather than assuming a version string is a build ID. Old actors/:actor/builds/:buildId metadata is deprecated in favor of actor-builds. Run cost immediately after completion is preliminary; native billing_final remains false and the full local reservation stays retained. An abort request/HTTP200 alone is not independent termination proof. Documentation-only web reads; no account, Actor, dataset, token or native runtime request occurred. Two initial docs-link clicks failed tool reference resolution and were corrected to opened-reference links; no provider endpoint was probed.

Primary sources were reread before the remaining implementation. These are design inputs,
not evidence of an installed service, authenticated account, provider entitlement or receipt.
Keep pinned Cargo/pnpm dependencies unless a needed implementation justifies a change.

Provider research follow-up, 2026-11-17: [Apify Run Actor](https://docs.apify.com/api/v2/actors-runs-post),
[dataset items](https://docs.apify.com/api/v2/dataset-items-get) and
[account limits](https://docs.apify.com/api/v2/users-me-limits-get) remain separate surfaces.
Run limits/build selection belong to the original run admission; a local HTTP deadline
does not establish remote termination. Use Authorization headers and bounded selected
storage reads, never URL tokens or arbitrary retained run/dataset identifiers.
[Serper's public site](https://serper.dev/) exposes search result examples but its public
`/docs` returned 404 and the [playground](https://serper.dev/playground) did not expose the
authenticated request contract in this reader. Preserve the repository's fixed search
endpoint/header contract as existing source compatibility; do not claim current account,
credit, retention entitlement or live endpoint verification from the marketing page.
No account/provider execution was performed by this research.

Dashboard recovery follow-up, 2026-11-17: [Mozilla Web Locks documentation](https://developer.mozilla.org/en-US/docs/Web/API/Web_Locks_API)
describes same-origin coordination across tabs and release when the callback completes;
its [primary compatibility data](https://raw.githubusercontent.com/mdn/browser-compat-data/main/api/LockManager.json)
records Safari support from 15.4 and Edge support through the Chromium mapping. Recovery
helpers use this browser lock while updating UUID-only pointers and refuse mutation
before network work if unavailable. This is source design evidence, not a live test of
the owner's browser. A missing durable admission still requires fresh explicit approval
before a paid PUT; recovering an already saved finding only completes local work.

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

Queue quota timezone research: [Chrono-TZ official API documentation](https://docs.rs/chrono-tz/0.10.4/chrono_tz/) identifies0.10.4 as the current documented release and describes IANA-generated timezone conversions and day changes across DST. The source dependency is pinned exactly0.10.4 with std only; the lock adds chrono-tz,phf,phf_shared,siphasher without replacing existing locked versions. Production timing, binary size and timezone parity are untested; the final suite contains explicit ZoneInfo comparisons.

Queue read projection research: [PostgreSQL17 CTE materialization documentation](https://www.postgresql.org/docs/17/queries-with.html#QUERIES-WITH-CTE-MATERIALIZATION) supports NOT MATERIALIZED for the side-effect-free inventory/filter CTEs, so the planner can push projections/filters instead of retaining a full history payload as an intermediate relation. The source queue read uses two business SELECT statements inside a read-only repeatable snapshot; transaction setup/commit are additional protocol work. No timing or memory behavior has been measured for it.
# Contact provider research refresh — 2026-11-17

Read primary [Apollo People API Search](https://docs.apollo.io/reference/people-api-search),
[Apollo People Enrichment](https://docs.apollo.io/reference/people-enrichment) and
[SignalHire API overview](https://docs.signalhire.com/overview) during the source phase.
Apollo documents zero-credit search without emails/phones and qualifies free-account
access by work-email registration plus additional eligibility. Match enrichment can
consume credits; account-specific ceilings and live endpoint/credit proof still gate
dispatch. Search availability never proves a free enrichment entitlement. SignalHire
documents synchronous Person API with withoutWaterfall and asynchronous alternatives;
unexpected async/unknown outcomes must not cause another billable submission. Existing
adapter capabilities remain narrower than provider product availability. No account/API
call, registration, purchase or real-person lookup was performed by this research.

Additional primary [credit stats](https://docs.apollo.io/reference/view-credit-usage-stats),
[API stats](https://docs.apollo.io/reference/view-api-usage-stats),
[authentication](https://docs.apollo.io/reference/authentication) and
[rate limits](https://docs.apollo.io/reference/rate-limits) were read. Current credit stats
documents a `credit_usage_stats` wrapper, while the legacy pure parser expects a root
pool. Native parsing must support the documented wrapper and qualified root compatibility,
refusing duplicated/ambiguous pool representations. Rate examples contain inconsistent
remaining/consumed figures; keep conservative arithmetic checks and require actual account
evidence, rather than treating a documentation example as endpoint allowance. Stats and
health introspection are documented separately from billable enrichment. No live balance,
endpoint entitlement or API key verification was performed.

Read SignalHire's primary [Person endpoint](https://docs.signalhire.com/person-api/retrieve-person),
[withoutWaterfall](https://docs.signalhire.com/person-api/without-waterfall),
[credits](https://docs.signalhire.com/person-api/credits) and
[authentication](https://docs.signalhire.com/authentication) references. Native transport
uses the fixed documented origin/header, one identifier, withoutWaterfall=true and no
callback/personal-field path. An unexpected accepted asynchronous response remains an
unknown result to preserve, never a reason to submit again. Credits metadata is distinct
from mailbox verification and current-employer/profile reconciliation. No provider call
was made during this research. Initial URL-based documentation click IDs failed to
resolve; the already-open official page references resolved successfully.

# Apify metadata follow-up — 2026-11-17

Public transport follow-up 2026-11-17: [SmartRecruiters endpoints](https://developers.smartrecruiters.com/docs/endpoints)
document public active posting lists/detail; authenticated/internal posting access is
outside this adapter. [Remotive's primary README](https://github.com/remotive-com/remote-jobs-api/blob/main/README.md)
advises at most four reads daily; retain the existing six-hour source window and source
attribution. The [HN API documentation page](https://hn.algolia.com/api) was accessible
only as a JavaScript shell, so no additional schema assurance is inferred. A web research
open of Arbeitnow's official public endpoint returned a current JSON sample. That was one
public read through the research tool, without runtime admission, local ingestion,
credentials or owner data. It is not native adapter/live operational acceptance. Further
source work uses fictional fixtures; no additional live feed probe is part of this phase.

Public ATS follow-up: primary [Greenhouse Job Board API](https://docs.greenhouse.io/job-board),
[Lever public posting fields](https://github.com/lever/postings-api/blob/master/README.md)
and [Ashby public posting API](https://developers.ashbyhq.com/docs/public-job-posting-api)
confirm documented public board reads and provider-specific workplace/compensation fields.
Keep source attribution, configured employer identity and observed publication evidence
separate; Lever's feed cannot establish a posting date and Ashby isRemote includes hybrid.
No application API or owner browser was called during this research.

Primary references: [account limits](https://docs.apify.com/api/v2/users-me-limits-get)
and [monthly usage](https://docs.apify.com/api/v2/users-me-usage-monthly-get).
The documented limits envelope contains monthlyUsageCycle, numeric limits and current
usage; monthly usage has usageCycle, service/daily breakdowns and two numeric aggregate
credit totals. The native projection keeps only documented numeric fields and cycle
timestamps. Credits, local reservations and the provider's spending ceiling remain
separate; these reads do not authorize runs. Existing actual provider source defines
the actor/public OpenAPI path and selected store metadata. Pure oracle fixtures will
compare the actual schema extractor and Python sorted-JSON digest; bounded loopback
fixtures will exercise transport without actual account requests. These are research
findings and deferred fixture declarations, not live acceptance.

