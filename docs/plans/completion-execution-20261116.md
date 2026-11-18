# Complete-source delivery plan — 2026-11-16

## Current delivery scope

Complete and validate Automated Apply on the owner’s laptop. The active goal and repository instructions suspend GitHub pushes, pull requests, remote reports, hosted Actions and merges until the owner reauthorizes them. Keep local Git milestones, acceptance reports and private continuity snapshots. Finish the source and fixtures, run combined validation, then review the local installation and verify operation on the laptop.

The native owner policy route will reuse `agent_policies` and `agent_policy_events`. Preserve the dashboard's nine platform preferences and compare-and-swap version, including the original Gmail and LinkedIn restrictions. All preview, fill and execution clients will read the same saved preference with its existing fallback rules. The write path takes the owner fence and row lock, saves one event for the next version, and checks both stored records before commit. A preference change does not grant an execution budget or modify the active Naukri mode. Exercise the dashboard contract, extension denial, stale versions and partial-write rollback in the combined gate.

The portal session routes will reuse the existing `portal_<platform>` records for Naukri, Wellfound, Instahyre, YC Work at a Startup and Internshala. Keep the dashboard's manual acceptance and forget behavior, with one owner fence and a checked row write. The extension already sends a gesture-scoped indicator through native messaging. Accept only its known operation and indicator values through the authenticated extension route. Persist the sanitized indicator and the existing actor/request digest atomically, so replay returns the saved result. A visible sign-in indicator does not establish account identity, API access or submission readiness. Feed platforms continue through their own discovery and handoff contracts. Use the same saved portal projection for the dashboard and Telegram.

Bind new portal observations to the selected browser when the existing extension credential, ordinary window, browser session and owner selection agree. An older sender can still record a historical indicator. The native service will keep the binding and revision details private and project only whether that observation is current, stale or unscoped. A current observation expires after 30 minutes or when its browser session, window, profile revision or owner selection changes. Reauthenticate scoped requests on replay because the shared request hash redacts the profile secret. Instahyre documents candidate signup by email or linked login. The sign-in indicator cannot establish which account is signed in, so the account adapter still needs independent identity evidence before dispatch. See the [Instahyre candidate setup documentation](https://help.instahyre.com/en/article/getting-started-nkf98s/).

The local connections report will use the existing dashboard fields and a read-only snapshot on the owner connection. Distinguish the current database query and local bearer request from stored OAuth evidence, recent browser and Telegram activity, local profile/PDF checks, and credential configuration. Use bounded projections and never expose account IDs, mailbox addresses, file bytes, secrets or bot replies. The view does not call providers, run CLIs, launch browsers or take the execution fence. Keep unauthenticated clients out. Browser guidance uses the selected Brave or Edge profile when available. Add loopback PostgreSQL coverage for positive evidence, stale evidence, and redaction after the source is written.

The owner command and history routes will use the frozen command DTO, the existing actor/request hash and `agent_operations`. Restore saved health, capabilities, policy, preferences, discovery status and HTTPS preview. Route extension URL previews and connection status through the existing extension-authenticated boundary. Keep conversation bound to Telegram and form, portal and queue operations bound to the extension. Replay the exact stored result for the same request and refuse changed payloads. Command execution in this route only reads local state before writing the receipt, so a receipt race can resolve without taking the execution fence or performing a side effect. History shows the latest 50 operation summaries and retains the original rows. Add fixtures for both HTTP actors, concurrent receipt arbitration and history disclosure before the combined run.

The platform audit found that `tool_api.rs` lists all eight saved platform sources while `packet_platform::select` only accepts Naukri among them. Native public feed discovery and ingestion already preserve Himalayas and We Work Remotely attribution and destination links. Naukri has the existing broker and receipt path. Instahyre, Wellfound, YC Work at a Startup and Internshala have saved portal indicators. Preparation still needs an explicit trusted source and destination rule for these seven sources, including HiringCafe. Extend the shared packet selector first, preserve each provider's exact source and destination semantics, and carry the original account and receipt gates through any later adapter work. A prepared packet does not authorize submission.

For the expanded packet selector, resolve the portal's saved listing identity before offering the platform page for review. Prevent a different explicit listing on the same platform from substituting for the original job. For the two feeds, use the original stored provider link with its query and fragment, require it to match the same saved observation and canonical listing identity, and evaluate known expiry against the current database time. Include expanded destination validity in the packet digest so existing packets refresh when the destination changes or expires. Show visible feed attribution. The existing browser form context refuses these packet sources until their platform adapters have separate authorization and evidence. Keep the legacy destination corpus and add expanded platform and expiration fixtures for the combined run.

Restore owner-supplied discovery import for the manual source family, including Internshala and HiringCafe. Use the existing normalized listing DTO, explicit discovery filters and shared deduplication. Store new rows as requiring review with fixed manual provenance. Duplicate imports preserve the saved job and any prior provider observation. Keep the import, rankings and final run receipt in one local transaction keyed by the owner request UUID. Support the normal dashboard preview and approval with a listing URL, title and optional employer. Manual imports spend no provider budget and do not establish applicant account identity or authorize browser actions. For a portal with an employer URL used for canonical deduplication, restore the observed provider listing for packet handoff only when its saved source and original observation agree.

HiringCafe documents a public conversational MCP connector with search and single-job details. Register its official endpoint in the project MCP configuration. A bounded research search returned an attributed public job URL with a slug ending in the posting ID. Accept this format alongside previously saved bare-ID links. Match saved HiringCafe observations by the posting ID across slug changes and preserve the original attributed URL. Keep local import owner-reviewed, since the connector describes conversational search and rate limits. Employer handoff still requires separate evidence. See the [official connector documentation](https://hiringcafe.com/documentation/hiringcafe-claude-connector).

Allow an owner to save an optional HiringCafe employer application link from a supported ATS. Reuse the draft discovery payload and explicit listing approval. Show both original listing and employer destination in the packet only when the retained manual source observation, normalized ATS job identity and supplied URL agree. Keep legacy absent or unsupported links on the portal handoff. Reject conflicting saved destinations and require fresh approval through the existing packet digest when the evidence changes. This is a manual handoff under the existing application gates.

Scheduled public discovery currently waits on HTTPS in the execution worker before its next application tick. Split the durable reservation, network fetch and cache/intake phases. Keep all database work on the existing worker connection and run at most one fixed-endpoint feed fetch at a time in a network-only task. Global controls and shutdown can cancel that task after reservation, preserving the consumed cooldown. Carry both worker control and feed schedule revisions into the ingestion transaction so a Stop followed by a Resume cannot admit an old task. A fresh scheduling tick may use its valid saved public cache under current policy. Preserve owner-run discovery, per-provider fairness, cache receipts and retry limits. Model-step scheduling and live timing will need their own coverage.

Use the same reserve/transport/complete split for the configured Cohere planner. Hold its existing provider permit from preparation until accounting, defer permit contention without spending a decision, and persist the run intent and monthly reservation before HTTPS. Move only the admitted, bounded request into a network task. Keep local tools and all SQL on the existing execution connection. Run Stop, owner pause, or shutdown can cancel the transport and preserve consumed budgets. After transport, record provider usage and enforce the planner's role rules before the original run lease can accept a result. A stale result cannot transfer authority. Keep the existing single-tick entry point for deterministic and fixture models.

Cached application conversation integration, 2026-11-18. Use the existing dashboard search preferences path and owner preference row. Read current profile and saved filters inside the job snapshot. Reuse the existing platform preview policy and prepare packets through the existing packet service. Bind Telegram selections to current saved filters, reject rows with submission or uncertain Apply history, and write selection, reply record and update cursor together. Keep arbitrary URLs in preview only.

Cached conversation filters/preferences design2026-11-17 LOCAL ONLY: freeze the actual SearchPreferences subclass without importing ORM/configuration and port its complete defaults/coercion/range ordering through the existing profile contract walker. Preserve literal known-properties/dedup controls. Port read-only cached job/company predicate separately from worker eligibility: explicit company/role/location/skills/remote/type/platform/status/recency/score/salary and optional requested startup/employee/exclusion filters; unknown required properties refuse, numeric experience is never inferred from descriptions. Capture Python matches with AST-only fictional objects/fixed time for reference generation. No search match grants application eligibility, history replay, new budget or profile facts. Durable GET/PUT preference and cached search orchestration follow with owner fences/revision ACKs and history suppression. Write source/fixtures before final combined tests.

Approved project conversation design2026-11-17 LOCAL ONLY: add a read-only answer projection over the existing coherent project Snapshot. Preserve current configuration/candidate/approval revision binding and project IDs; independently require selected facts remain approvable. Apply configured priority/rank, exact named project restriction, requested topic/personal-claim filter and legacy stable term/technology relevance. Return one project's approved text, pinned source evidence and deterministic/draft-review status with legacy bounded word/character compaction. No resume fallback in this Telegram projection (the legacy adapter supplies none), repository scan/fetch/model/approval save or inferred personal skills. Add frozen fictional reference comparisons and direct invalid/stale/limit cases before combined tests; no production read.

Conversation memory design2026-11-17 LOCAL ONLY: reuse telegram_context_<owner-hash> and existing bounded selection semantics (10 jobs,8 category/time history entries,10-minute TTL). Use DB time and the existing owner fence before row locks. Loaded memory keeps an opaque exact saved-row expectation; writes recheck it and ACK exact row after triggers. Expiry creates a fresh selection proposal without touching application/Codex history. Oversized, malformed, unknown-field or incoherent saved memory is retained and refused, not silently overwritten. Persist only bounded typed intent/selection fields and category history, not raw incoming messages. Telegram/user binding remains the caller's separately verified boundary; memory is never provider/application authority. Add pure and disposable PG fixture source; no production DB operation, classifier or provider call.

Conversation intent source design2026-11-17: freeze the actual legacy Intent schema and deterministic interpretation corpus without importing app configuration or executing classifiers. Port bounded compositional parsing and common command spelling repair, keeping saved company/project identity unchanged and model output unable to grant authority. Preserve unsafe-command refusal, conflicts/clarification, word/character limits, follow-up filters and typed selection coherence. Use fixed cached legacy regex/Unicode projection and selected native URL normalization; no network or browser side effect. Optional classifier transport and persisted owner-bound conversation/responding follow separately under current local/model budgets. Add source/corpora/fixtures now, defer their comparison/execution until the combined gate.

Local-answer v1 design2026-11-17: port typed deterministic/model/needs-input/validation-failed outcomes and exact factual/summary/resolver/low-memory exclusions. Integrate deterministic resolution in native answer preparation. Optional rewrite callbacks receive only permitted sentence variants/options, never raw source facts or citations, and are network-only: no durable ledger transaction may occur in a cancellable callback. Production service adoption remains deterministic/no callback; existing explicit writer paths own budgets/IO. Share only overlapping identical question/context/instructions hashes (max8), not a persistent candidate cache. Keep one waiter cancelling from cancelling another; last-waiter drop removes its own nonce-bound entry and aborts transport. Revalidate returned sentence text locally and retain truthful deterministic fallback/error/model-attempt/selected usage on failure. Add fictional concurrency/cancellation/capacity/provenance fixtures; no implicit model creation or new connection/pool.

Sentence rearranger design2026-11-17: implement the missing explicit OLLAMA_GENERATION_AUTHORIZED branch when generic OLLAMA_ENABLED is false. Reuse fixed loopback client, local metadata proof, shared provider gate/optional monthly ledger and deadline. Send only permitted approved sentence variants through /api/chat with no tools/stream, keep_alive0, bounded local context/thread/output options and a closed answer-only schema. Reconstruct claims locally through existing extractive::match_answer; model-supplied citations/claims are forbidden. Require exact model, assistant, stop and complete envelope; reject tools, remote metadata, oversized/encoded/redirected or malformed replies. Grounding/current-context draft gates remain after IO. Do not conflate this provider path with the legacy internal LocalAnswerEngine v1/coalescing contract, which remains an explicit separate parity item until integrated. Add source/fixtures before combined tests; no daemon start/pull or actual model call.

Local fallback design2026-11-17: preserve explicit primary provider and opt-in local Ollama only. A shared original LLM deadline gives primary transport55% when fallback is available and local transport its remainder. Do not wrap/cancel durable reservation/token/cooldown COMMITs with a network timeout. Bound RequestBuilder deadlines (including response bodies), local metadata/generation and CLI group lifetime separately. Primary provider response/timeout never grants a retry of that provider; no fallback to another remote provider. Unknown ledger, unsafe tool/usage/context errors stop rather than being hidden by fallback. Retain each consumed ledger, selected actual provider/model and selected-attempt usage, with fixed fallback warnings and any-primary-attempt provenance. Preserve local cloud-disabled/model metadata proof and shared semaphore. Write source/fixtures first; source-only configuration is not daemon/model acceptance. Rearranger-specific closed sentence matching follows independently.

CLI writer source design2026-11-17: port legacy AGY with fixed argv and cleared environment, exact frozen no-tools primary-agent profile, existing owner-trusted private runtime workspace, no-overage settings and explicit enabled/quota/model selection. Do not create owner trust/authentication, change shared settings or inherit provider credentials. Use existing llm_monthly_usage provider=agy with one durable request before process work; no automatic retry/refund. Keep schema/log artifacts private and bounded, outside development/release source. Verify metadata/tool-free init before writing a candidate prompt. Parse every stdout frame including final unterminated data, refuse advertised/called tools/subagents, require exactly one successful one-turn result and selected usage. Bound stdout/stderr64KiB each, enforce an absolute deadline, kill/reap the owned process group on failure/cancellation, and preserve only fixed errors. Integrate the same grounding/context generation checks in answer_service; keep questionnaire Cohere-only and no implicit CLI selection. Add fictional process/protocol/PG regression source before combined tests. Local fallback/rearranger follows this primary writer boundary separately.

MCP discovery composition design2026-11-17: add a narrow bridge submodule for source/status,
actual-query previews, retained job/startup/read UUID reads and explicit local completion.
Optional original dispatch/read recovery and metadata inspection have separate private
configuration opt-ins, checked for direct calls as well as discovery. Each original PUT
requires an explicit true consent field and caller-retained nonnil UUID; read recovery
uses a distinct read UUID, never actor/run/dataset URL input. Normalize requests against
existing native contracts, exclude manual imports/alternate idempotency keys, and route
all work through the same authenticated owner API. No new DB pool/grant/ledger or provider
client. Use per-operation deadlines covering the configured host budget; ambiguous HTTP
responses retain caller UUIDs in selected error context with no retry. Describe local
completion separately from provider recovery, and metadata calls separately from paid
execution. Add catalog/direct-call, schema/ID/consent/timeout and framed-process fixtures,
all deferred until the full source gate. Preserve default read availability without paid
credentials and keep native/live MCP acceptance explicitly false until tested.

Startup durable owner boundary2026-11-17: add UUID PUT to the existing saved-run GET
and empty-body POST .../complete for job-led native startup parents. Validate normalized
job-led body/source and IDs before the shared connection slot; legacy keyed POST and
manual company-first path stay compatible. Saved GET never dispatches; explicit local
completion inspects the original child and completes retained finding/jobs/company
results only, preserving unknown remote states. Reject manual PUT adoption. Preview
reports effective provider query separately from company filters, native readiness and
selected actual-query paid estimate/caps/blocker without provider/budget/owner writes.
Gateway adds only UUID PUT and narrow complete POST. Then replace the old startup
component's unretained POST state with isolated durable UUID/source metadata, Web Locks,
GET-only mount/recovery and reviewed pointer release. Paid new runs need separate opt-in
and ready preview consent; unknown paid child recovery remains explicit in job discovery
using its original child UUID, never replayed by startup local completion. Keep manual
company-first imports outside new job-led controls and preserve unsupported-source gates.

Paid startup composition2026-11-17: share the existing job-led startup parent and
catalog-result path using a typed public/paid child adapter, limited to startup's
already supported Wellfound and Work at a Startup paid sources. Admit the actual
startup parent plus actual paid job parent/original intent/reservation in one owner
transaction; retain deterministic child UUID and compatibility key. Original opaque
child acquisition stays provider-specific; replay may finish only retained local
findings. Reuse frozen job-to-company receipt attribution, pinned profile/current
configuration and selected catalog recheck; source-reported company claims do not
promote curated startup facts. Compare exact nested paid child/reservation/month/
cooldown after startup triggers before commit. Saved completed parent reads remain
independent of current paid configuration/profile. Parent and child result hashes
include separate paid reservation/recovery metadata without renewing authority.
Expose child_run evidence needed for explicit acknowledged-read recovery in the job
flow; startup parent finalization stays local. Full startup UUID PUT/local completion
and durable dashboard consent/recovery follow. No source fixture proves a platform's
real discovery/application automation.

Acknowledged read dashboard design2026-11-17: keep a separate local pointer containing
only parent/read UUIDs under the original discovery Web Lock. Save before explicit
empty keyed PUT; mounting/inspection performs saved GETs only. Require separate owner
consent for every new read round; never recover an unknown paid start without an
acknowledged run ID. Reuse retained read GET or local-complete pages, then original
local discovery completion, without another provider call. Validate read IDs/source,
3-round/4GET bounds, minimum counts and full-cap preliminary accounting. Adopt the
server's last read UUID when its browser pointer is missing; never generate a fresh
round from a lost response. After an explicit review of an expired/spaced-out read
with no complete pages/finding and allowance remaining, prepare a new UUID pointer
without dispatch; require fresh read consent before PUT. Original completed-result
review may clear only linked browser pointers, preserving all server history/budgets.
Keep expired/unknown pending pointers on errors, configuration changes and reload.
Expose saved refresh, local page completion and new bounded reads as separate actions;
provider start/abort, application work, profile facts and billing finality are absent.

Acknowledged owner recovery boundary2026-11-17: add GET/PUT UUID resources at
discovery/runs/{parent}/reads/{read} and empty-body POST .../{read}/complete. Reject
nil/equal IDs, arbitrary run/dataset/query fields, methods and query strings before
dispatch; require a retained native paid owner parent rather than adopting legacy or
public runs. GET reads saved read state; explicit PUT consumes only a separate bounded
read claim; POST reconstructs saved pages locally and does not dispatch providers or
rank/apply automatically. Reuse existing owner authentication/CSRF policy, shared
transient permit, temporary connection and host timeout. Expose original read allowance,
last read UUID and next read time in the paid parent's closed usage so response-loss
recovery can recover its original read pointer. Add only the two narrow gateway route
patterns, generate both policy copies, and defer full inventory/OpenAPI/type gates.
Use fixed422/409/429/404/timeout errors; saved GET and completed read replay must stay
available without current credentials/configuration. Durable UI read consent/pointers
follow before combined tests; no new provider or installation operation now.

Acknowledged read transport detail2026-11-17: consume the separate opaque read claim,
durably admit status/build/dataset GETs in that order (maximum4), and enforce GET-only
again in the final transport permit. Original paid Session permits remain separate.
Before each GET recheck exact original/read rows, credential/current reviewed context,
full-cap/monthly numeric snapshot, cooldown and45-second deadline. Commit before IO;
retain only selected typed status/build/page and bounded counts/errors after IO, with
monotonic cooldown and final ACKs. A pending lost read stays minimum-count/unknown;
saved replay never rehydrates the claim. Status checkpoints also CAS the original
selected run so later rounds cannot forget newly acknowledged dataset/terminal/options
identity; preserve original start intent and original HTTP counters. Successful bounded
dataset collection retains both selected pages with individual hashes and original
observation time. Local-only completion reconstructs the full bounded finding, CASes
it into the original journal and records its read UUID/hash separately. Refuse a fresh
read round while complete saved pages await local completion. Share pure dataset selection/deduplication with original
acquisition. Explicit recovery does not start/abort, refund, rotate accounts or apply;
ordinary owner GET/local-complete remain local. Add controller/transport fixtures after
source, then owner route/UI pointer source before the final combined gates.

Acknowledged read admission detail2026-11-17: retain the consumed read UUID list,
last-admitted/next-allowed timestamps and lifetime count inside the original private
paid journal, initialized at paid intent creation. A separate optional index must not
reset allowances. Each new explicit read UUID appends once under owner-first SERIALIZABLE
and creates its immutable private read intent in the same transaction; replay returns
saved state without context renewal. Require all prior referenced read records to exist
and remain bound to parent/scope/reservation/run. Refuse missing or malformed allowance,
unknown start, active original, changed reviewed configuration/credential, global
cooldown, active/too-recent prior read or more than3 lifetime rounds. Bind the opaque
claim to the exact updated original journal/read row, exact monthly snapshot and one
45-second deadline, with final independent ACKs after all triggers. Current profile is
not required for read-only status observation; local intake still requires its pin.

Acknowledged Apify read recovery design2026-11-17: preserve closed acknowledged run
options in original checkpoints and add pure selected actor/run restoration with
round-trip validation. A separate ReadContext may construct only fixed GET status,
original build and original dataset targets; it cannot construct a paid start/abort,
reservation or dispatch permit. Require the original intent expired (75seconds), no
retained finding, same reviewed configuration/query/credential, attached acknowledged
run identity and24-hour recovery window. A fresh status must succeed before build/
dataset use; changed actor/build/run/start/cap/dataset/terminal status must refuse.
Next implement separate owner-fenced read admissions (maximum3 rounds, maximum4GETs/
45seconds per round,5-minute spacing, provider cooldown), durable per-read checkpoints,
lost-read minimum counts and no renewed original grant. Unknown starts without an
acknowledged run stay held; no guessing/latest-run search. Final selected finding CAS
preserves original start/HTTP evidence and retained budget, then existing local finish
rechecks current pinned profile/context. Read results remain preliminary billing and
qualified termination observations, with no independent termination or refund claim.
Owner GET stays saved-only; an explicit separate read-recovery action follows the
durable read lifecycle, never automatic retry through local-complete or ordinary PUT.

Paid dashboard design2026-11-17: select only saved-ready native paid sources; keep
unconfigured/legacy-only sources disabled. Require a separate explicit allow_paid
checkbox before preview and the existing reviewed-run consent after a ready preview.
Changing criteria clears both paid and run consent; recovering a retained finding uses
only GET/empty local complete and needs no renewed paid start consent. Persist only
the existing opaque UUID/source pointer across response loss or reload. Show exact
saved run/month caps, selected estimate/blocker and retained full-cap reservation with
preliminary billing; unknown paid estimates must never appear free. Validate native
paid result reservation shape before allowing terminal review/pointer release. Keep
saved result refresh separate from acquisition, avoid on-mount dispatch, and retain
all unknown-start pointers. Add UI/helper fixtures now; actual UI/type/browser gates
remain deferred with the final combined test run.

Paid owner boundary design2026-11-17: extend existing authenticated discovery UUID
PUT/keyed POST and local-only complete routes to configured Apify sources, using the
same transient semaphore/temporary connection. Validate source/body before acquiring
the permit. Select saved native public/paid parent by private original-journal key in
one read-only snapshot; legacy reads must refuse either native scope appearing in a
later snapshot. The same saved-kind discriminator selects local-only completion,
never arbitrary request/provider IDs or a start retry. Keep paid missing configuration,
opt-in, budget and cooldown errors explicit and sanitized. Registry native execution
readiness is an additional saved review/budget/build-schema projection, separate from
legacy configuration availability and live verification. Invalid paid configuration
disables its execution without preventing unrelated public/saved read paths. Preview
uses effective saved query and returns selected estimated/capped costs and blockers
without provider calls, owner-fence writes or budget reservation. Paid POST compatibility
UUID uses a distinct fixed namespace; public UUID mapping remains unchanged. Full UI
paid consent/result accounting and bounded acknowledged-run recovery follow separately.

Paid owner-run composition design2026-11-17: refactor original Apify admission into
the same owner-first transaction as an actual discovery_runs row and private owner
journal; only an opaque original claim can acquire provider data. Standalone saved
paid intents or legacy compatibility keys cannot be adopted as new parents. Bind the
normalized original request, child scope/configuration/credential/profile hashes,
actual row and exact monthly snapshot; final admission ACKs follow all parent triggers
and recheck child journal/reservation/month/profile/plan/cooldown/deadline. Replays are
saved reads. Complete retained findings with shared local intake and native bounded
ranking/history suppression in one transaction; independently verify rows, receipt,
original child and ranking/history inputs after terminal parent/journal triggers.
Terminal replay returns original immutable results without current credentials/profile
or freshness. A previously saved local receipt remains usable for pending parent
completion only with current original pinned context. Expose honest pending/unknown,
local-intake and ranking states, minimum HTTP counts and full-cap preliminary accounting;
no retry POST, cap refund, application authority or live verification. Keep transport
and local-only completion separate for subsequent owner routing/known-run recovery.

Apify retained local intake design2026-11-17: extract only the provider-independent
job/company/source-observation batch and closed receipt validator from public intake;
keep public original-scope/configuration/window guards unchanged. The paid wrapper
requires its original selected SUCCEEDED run, attached full-cap reservation, finding
hash and original normalized provenance. Fresh local writes require the same reviewed
configuration, credential and pinned profile plus a24-hour finding TTL. Owner-first
SERIALIZABLE, existing intake advisory lock, complete bounded legacy identity inventory,
fill-only job/history preservation and final full-row ACKs remain shared. Atomically
save jobs and an immutable private apify_intake receipt bound to original scope,
configuration, finding, run and reservation hashes. Re-read journal, exact numeric
monthly total, reservation, profile/configuration and written rows after receipt
triggers; any mutation rolls back the local transaction without erasing remote evidence.
Saved local receipt replay is a read independent of current configuration/profile/TTL
and makes no provider call, refresh or budget release. Keep selected company intelligence
in source observation provenance as source-reported claims; do not overwrite curated
company facts or infer verified startup/eligibility evidence. Parent/run finalization,
owner endpoints and bounded known-run read recovery follow as separate compositions.

Apify fixed transport/checkpoint design2026-11-17: consume only an original opaque
75-second grant, bind the client credential hash and current saved plan before HTTP,
and use fixed api.apify.com/v2 targets from the typed planner. Explicit numeric-loopback
fixture replacement only in testing; disable proxies, cookies, redirects and retries.
Each response max1MiB/20seconds and aggregate8MiB; no error body/url/token in failures.
Before billable start, checkpoint selected original actor ID and reviewed exact build/
schema evidence and durable start intent. After response, commit selected bound run ID
into the original reservation and journal before any polling/build/dataset follow-up.
Cancellation/commit ambiguity preserves prior stage and full cap without replay.
Each status/dataset/abort operation requires its own original durable stage admission;
GET saved state cannot create or resume an in-memory transport session. Explicit later
recovery reads only previously acknowledged IDs under a separate bounded read claim,
never retries a start. Retain selected finding/hash and accounting before local intake;
no automatic cross-route fallback. HTTP abort is one original bounded best effort with
durable intent and separate qualified outcome, not independent termination proof.

Apify original USD admission design2026-11-17: use existing NUMERIC(16,6) budget and
reservation tables, exact decimal/micros conversion, owner-first SERIALIZABLE and no
new connection/pool. Atomically reserve the entire per-run cap, increment the monthly
total, retain its original opaque invocation/profile/source/query/build context and
nonrenewable deadline, then independently ACK reservation/month/journal after triggers.
No grant comes from saved replay or a public reservation reader. Same UUID with changed
body/context conflicts; a previously admitted unknown start keeps its full allowance.
Check all Apify cooldown months before new reservation. Saved original requests remain
readable without current credentials/configuration. No refund/reset, no provider-credit
claim, no cross-route fallback/account rotation. Provider attachment and selected status
checkpoints will update only the original reservation/run binding, leave monthly totals
unchanged and keep cost preliminary; failed local transactions preserve earlier intent.

Reviewed Apify execution dependency design2026-11-17: first port pure portal record
normalization, exact six-decimal local USD accounting, fixed original request targets
and closed actor/run/build/dataset evidence. No HTTP authority belongs in these helpers.
Preserve reviewed pinned build/permissions/inclusive account cap and explicit allow_paid;
retain one configured actor route per original UUID without unknown-start failover.
Local dataset count/bytes and mapped input limits remain independent from provider
maxItems billing semantics. Resolve the configured actor's opaque ID through a selected
original metadata response, bind run actId/buildNumber and returned buildId, then verify
the original build before dataset use. Require a separate private opaque build ID and
reviewed schema digest (not a guessed build number as path ID); verify that exact build
and validate actual bounded actor input with no reference resolution before a start
target can be constructed. Actor identity/build/input/context remain bound across
original status/dataset/abort targets. Drop arbitrary vendor/recruiter/private metadata
and personal founder/profile URLs from generic job retention; professional evidence
continues through the separately rights-reviewed people workflow. Keep provider costs
preliminary, no URL bearer tokens, no arbitrary run/dataset targets and no account
rotation. Follow with atomic full-cap numeric reservation/original intent, fixed transport
and durable response checkpoints before local ingestion. Lost start responses remain
unknown without a second POST; cancellation cannot fabricate remote termination or refund.

Startup job-led original composition design2026-11-17: admit a real startup parent,
private normalized request/filter/profile scope and original native job child in one
owner-first transaction; deterministic child UUID and legacy-compatible startup_child_
key bind the original child. Final ACKs follow parent triggers and recheck child row,
journal, profile and source window before commit. Share transaction-local native job
admission and opaque original acquisition; never reconstruct or replace a lost child
invocation. Startup replay/GET are saved reads, while explicit local recovery may finish
retained child observations and then the parent without provider replay. Extend local
job receipts with closed opaque job-to-company IDs so owner edits cannot silently
rebind original startup attribution. Compose the existing saved startup catalog only
for those original company IDs, with current pinned profile and original filters;
unknown size/competency remains unknown. Parent terminal row/journal/shortlist snapshot
commit together; repeat the bounded selected-company snapshot after terminal triggers
at the same observation time to detect late changes. No new directory crawl, source
pacing reset, application authority, subscription purchase or live acceptance inference.

Public discovery owner boundary design2026-11-17: expose original preview/run/read paths
plus UUID GET/PUT run resources through existing owner authentication, CSRF gateway,
single shared transient permit and one temporary connection. Validate requests before
connection/authority; original POST requires a stable compatibility key mapped into a
fixed UUID namespace, while new dashboard requests persist an opaque UUID before PUT.
Preview is REPEATABLE READ READ ONLY and returns selected source/effective query only;
GET never mutates/provider-dispatches. Read legacy rows as explicitly unverified saved
history without adopting them into native authority. Unsupported manual/paid execution
remains explicit until its separate source lifecycle is implemented. Keep source metadata
implementation flags distinct from live verification. Dashboard Web Locks serialize
cross-tab recovery; persist only UUID and source, require explicit original dispatch,
inspect saved GET before recovery, and allow local completion only from retained findings.
Never erase an unresolved browser attempt on criteria edits/reload/network failure or
silently generate a new admission. Terminal review can prepare a new attempt while all
DB history/source pacing remains intact. No browser mount effect may dispatch providers.

Owner public result finalization design2026-11-17: share transaction-local intake and
its deferred full-row acknowledgements so a fresh owner completion commits employer/
job/observation/local receipt, saved relevance rankings and terminal actual parent row/
journal together. Existing separately completed local receipts remain immutable local
recovery inputs; changed context/profile/expired findings hold pending finalization.
Use the existing pure domain discovery matcher, current original-pinned profile and
bounded reviewed local mailbox history, omitting confirmed prior applications from
rankings without rewriting their application facts. Deduplicate saved IDs and sort
score descending then UUID. Disabled profile use yields empty completed rankings and
must not query profile/history. Terminal reads/replays project original counts/IDs/
rankings and never refresh facts, consult current profile or reconstruct HTTP authority.
Keep low-level acquisition distinct from the composed owner run; cancellation leaves
durable admission/finding/local receipt for local-only recovery, never another GET.

Atomic SQL public intake design 2026-11-17: use transaction-local helpers over the
actual companies/jobs/job_source_observations schema, owner fence then advisory240204.
Read exact source observation and canonical URL identity before employer names; build
one complete id/URL-only legacy inventory bounded to10000 rows when needed. Ambiguous
exact identities or changed employer/source identity hold the whole local transaction,
leaving the separately retained finding intact. Resolve company domain then unique
lowercase name, explicitly flag unresolved ambiguous names, and never overwrite known
company facts. Preserve full existing job rows, application decisions and primary links;
fill only missing evidence, refresh only same-primary experience ranges, and keep newer
source provenance when an older observation arrives. Coerce expected numeric/timestamp/
array patches with actual PostgreSQL row types before independent post-trigger ACKs.
Updated-at trigger timestamps may lie between transaction start and final clock time.
Retain final full-row expectations for a coupled reread after parent/receipt writes.
Parent local completion checks original finding hash,24-hour TTL, current source context
and canonical profile pin, then commits jobs/observations/immutable receipt/terminal
parent together. Saved completed replay returns the original receipt without new local
freshness or provider authority. Context changes and uncertain HTTP never repeat GETs.

Public owner-run admission design 2026-11-17: atomically create the original actual
discovery_runs row, private owner/profile/query scope and original child public batch/
source window under one owner-first SERIALIZABLE transaction. Reuse a transaction-local
child admission helper, with final independent ACKs after all parent writes/triggers.
Use the requested native UUID as the real run ID and a bounded fallback compatibility
key; never attach a preexisting unscoped child, rewrite a legacy run or steal a reused
compatibility key. Replay validates original request hash and returns retained state
without refreshing profile/config, expiry or network authority. Only the returned
in-memory original claim can acquire its child observation; source and parent metadata
must remain readable without dispatch and cannot claim local job intake is complete.

Public owner-run scope design 2026-11-17: freeze the actual RunRequest and original
request hash (excluding the compatibility idempotency field). Preserve use_profile,
explicit versus effective query, and actual title/location/remote/employment expansion
before any parent/child admission. Public-source planning rejects manual records and
unsupported sources without network authority. A private canonical profile UUID/version/
content-hash pin binds every saved fact while exposing only query terms/version in future
preview; no raw candidate/contact/resume data is copied into provider plans. Disabled or
absent profiles remain distinct, and changed profile/context must hold later local intake.
This dependency precedes SQL job intake so recovery cannot silently change filters or
inherit a new profile while completing an original retained provider observation.

Public local-intake dependency design 2026-11-17: first freeze actual source/board/ID
and canonical URL observation keys, conservative company/domain/location/content identity
and explicit discovery-query filters. Profile-expanded provider terms must remain distinct
from owner-explicit filtering; unknown publication/location/employment/remote fields stay
visible as in the existing discovery service and confer no application eligibility. Use
original Unicode case/HTML/whitespace semantics and fixed explanation codes. Then build
owner-first atomic local intake with original finding/config/profile/filter checks,
24-hour finding TTL, bounded complete legacy URL inventories, source/URL identity before
company names and no title-similarity merge. Preserve all existing application decisions,
notes, scores, explanations, primary links, company facts and uncertain history. ACK every
job/observation/receipt after triggers, retain original finding on local failure, and
separate startup-parent/child original admissions from any later local-only recovery.

Public batch transport design 2026-11-17: consume the original opaque grant exactly
once through fixed GET plans, sensitive data never in diagnostics. Disable redirects,
environment proxies and automatic retry. Bound each JSON response to 8 MiB, total decoded
bytes to 32 MiB, the retained normalized batch to 8 MiB, individual calls to 15 seconds,
batch lifetime to the original 75-second deadline and requests to configured boards plus
at most 100 details and two HN calls. Fixture substitution is explicit numeric loopback
only. Sequential board pagination uses the frozen native order; Ashby removes unlisted
postings before slicing; SmartRecruiters checks exact offset/limit/count before fixed
detail reads; HN selects one original hiring story and only its top-level comments.
Do not follow upstream links or refill a page after malformed records. Compare duplicate
raw hashes in memory, omit raw input from retention and quarantine all conflicting
identities rather than retain an arbitrary first candidate. Preserve partial findings
and distinguish local HTTP attempts, observed responses and complete traversal. Rate
responses extend the shared source cooldown monotonically, including HTTP-date values;
unrepresentable delays require review and a far-future hold. Retain selected finding/hash
and original terminal journal atomically before separate job/company ingestion. GET or
saved replay never repeats provider work; cancellation keeps original admission unknown.

Public batch admission design 2026-11-17: under owner-first SERIALIZABLE, bind an
original request UUID to normalized source/query, exact private source snapshot/context,
single in-memory invocation and 75-second deadline. Commit the shared provider access
window (Remotive six hours, other public providers sixty seconds) and private original
journal together; independently reread both after triggers. Only that original returned
opaque grant may enter the subsequent GET batch. Replays and saved reads cannot create
a grant, extend expiry, reset pacing or import jobs. Same UUID with changed source/query
conflicts, while old requests remain readable even if present configuration is missing.
Commit ambiguity/lost invocation remains qualified pending/unknown without replay.
Do not hold a database transaction across transport or equate batch admission with a
provider HTTP response, live vacancy, identity verification or application authority.

Public request planning design 2026-11-17: enumerate only seven fixed source origins
and reviewed configured board IDs, with query/page/record bounds from the actual DTO.
Construct SmartRecruiters details from validated posting IDs and HN comment requests
from validated original story IDs; never follow provider ref/pagination/result URLs.
Use deterministic sorted configured board order in the native request snapshot (a
documented difference from legacy JSON insertion order); include the exact order/region
and employer binding in future original admission hashes. This pure planner returns
closed GET targets, not a transport grant. Then compose durable owner-first source
window admission, nonrenewable original invocation, fixed no-proxy/retry/redirect GETs,
bounded complete pagination and retained findings before separate local ingestion.

Public provider parsing design 2026-11-17: port the seven existing public adapters'
record parsers over the actual normalized job contract, without transport authority.
Preserve operator board/employer attribution, exact hosted posting/application identity,
Ashby visibility/remote consistency, SmartRecruiters active/company/detail checks,
explicit salary units and unknown publication/remote evidence. Parse only selected
professional job fields and provenance; exclude arbitrary source_fields/vendor JSON
from new observations as a deliberate privacy tightening. HN accepts only top-level
attributable hiring comments; HTML/entity handling stays local without following links.
Native endpoint transport, complete pagination/deduplication, durable pacing and atomic
startup orchestration follow. Fixture comparisons use actual parser methods with a
fictional clock and bounded projection of the documented provenance difference.

Public job contract design 2026-11-17: freeze the actual NormalizedJob and DiscoveryQuery
before porting the seven legacy public providers. Preserve defaults, whitespace/type
coercion, strict experience evidence, bounded finite pay, explicit UTC observation
timestamps, ATS identity override rules, unknown company flags and tri-state remote
evidence. Arbitrary source fields confer no verification/application authority. Retain
the actual 256-KiB serialized record cap and bounded query pagination. Compare actual
Pydantic DTOs with pinned fictional observation times through AST/pure contract loading;
do not import application configuration or provider clients. Then compose provider-specific
normalizers, fixed-host GET transport, durable source pacing and startup job-led ingestion.

Apify owner inspection design 2026-11-17: retain existing exact owner-only status,
account-inspect and allowlisted actor-inspect routes. Use the shared transient permit
and one temporary connection, no new pool. Commit the original 10-second metadata
access window under owner-first SERIALIZABLE with an independent post-trigger ACK
before any remote GET; release the transaction across transport. A superseded claim
cannot overwrite a newer account inspection. Cache only closed account projections
under a new native key with private credential-context/hash binding; preserve and
sanitize older legacy cache on read while explicitly qualifying its unknown context.
Status reads one REPEATABLE READ snapshot for cache and exact local budget without
provider operations or writes. Local USD reservations are not provider credit. Saved
actor prerequisites, public default-build metadata and account observations remain
separate from execution approval. GET never probes; POST inspections remain explicit.

Apify metadata design 2026-11-17: implement a read-only fixed official API client,
separate from actor execution and connected MCP credentials. Actor/store calls are
public without an authorization header; only the two account endpoints use the local
sensitive bearer header. No arbitrary URL/path, proxy, retry, redirect, run, dataset or
POST operation is exposed. Bound each streamed JSON response to 1 MiB, each composite
inspection to 20 seconds and each request to 15 seconds. Fixture origin substitution
requires explicit fixture mode and exact numeric loopback. Freeze the actual actor
metadata/inspect DTOs. Extract only a unique POST input schema with local component
references; never resolve external references or execute defaults. Preserve the legacy
sorted Python JSON schema digest. Account output deliberately narrows legacy arbitrary
payloads to documented numeric limits/current/totals and validated cycle timestamps;
unknown fields and daily/service blobs cannot expose account PII. Treat this as observed
metadata, never current credit entitlement, pinned-build review or dispatch authority.
Follow with owner-fenced pacing/cache and owner routes before actor execution work.

Research owner/dashboard design 2026-11-17: add native-only UUID PUT/GET request paths
and pure saved configuration status. Reject unkeyed legacy native search POST before any
database/provider operation. Share the existing transient permit, owner boundary and one
temporary connection; no added pool/process. Keep the existing PeopleQuery unchanged.
The dashboard persists only company/request UUIDs before PUT, reads a saved request first,
reuses the same ID after response loss and never falls back to the legacy paid POST.
Only a retained successful finding may retry local completion. Unknown/held requests keep
their pointer. Preparing a new search requires explicit review, a fresh terminal GET and
exact pointer comparison; retain the old database history. Show results/status in ordinary
product language without raw runtime JSON or claims of completion for held/unknown work.
Extend the shared BFF policy only for these exact paths and retain CSRF/session checks.

Paid finding completion design 2026-11-17: use a second owner-first SERIALIZABLE local
transaction after durable finding retention. Recheck exact original input/configuration,
current saved rights, company snapshot and a 24-hour finding lifetime. Changed or missing
context records a qualified held result without requesting the provider again. Valid
findings reuse the manual identity/ACK machinery with explicit public_search provenance,
unconfirmed provider identity and original observation time. Commit local receipt, all
people/contact changes and terminal paid journal atomically; failures retain the prior
finding. Replay can complete local work from a saved finding but cannot obtain a new
transport grant. Completed reads return the original selected result without refreshing
facts or writing. The UUID-only native owner endpoint/dashboard will use this controller.

Search transport/finding design 2026-11-17: consume only the original opaque grant at
one fixed no-proxy/no-retry/no-redirect Serper endpoint, with sensitive header credentials,
a 15-second total call and 1-MiB streamed response limit. Loopback substitution is fixture
only. Parse only selected public/official professional results; never request result URLs.
Retain the qualified transport finding and exact original reservation terminal state in
one owner transaction before local persistence. Rate responses set monotonic cooldown;
transport loss retains unknown charge and the entire local allowance. Recording does not
depend on current settings or employer still matching, since lost evidence must survive
those changes; later local completion checks them. GET/replay cannot reconstruct grants.
Saved finding output excludes raw snippets, provider diagnostics and permission URLs.
No current provider credit/balance/charge or operational installation is inferred.

Paid professional search admission design 2026-11-17: the native owner endpoint will
use a UUID in its path so existing legacy POST handlers cannot silently ignore a new
idempotency header and bill again. Keep actual PeopleQuery unchanged. Before one fixed
Serper POST, commit the exact input/configuration/company snapshot, private single-use
grant, original deadline and one locally capped search-request reservation under the
owner fence. Reuse the existing numeric budget/cooldown tables with a separate serper /
people_ namespace; local units are requests, never a claim of current provider credits
or dollars. Require local credentials, explicit paid opt-in, rights/permission evidence,
profile-result retention or exact official-domain rights. Replay/GET returns retained
state without rebuilding a grant, refreshing deadlines or refunding uncertain cost.
Then retain only parsed professional findings before separate local ingestion. Original
input/settings/company changes hold results; a saved finding may support a reviewed
local completion without authorizing a new provider request. No raw snippets, arbitrary
result URL reads, credentials in output, retries, redirects or fallback paid calls.

Professional manual ingestion design 2026-11-17: commit one UUID-scoped local import
receipt and all candidate/contact changes atomically under owner-first SERIALIZABLE
and the existing ingestion fence. Complete replay returns the original result without
refreshing evidence; a changed request conflicts. Nonempty imports require an explicit
normalized company domain, since display name alone cannot establish employer identity.
Preserve human-confirmed public-person rows and canonical company facts. Manual public
URLs stay unverified; official evidence requires explicit rights confirmation, exact
company/publication domain and independently confirmed owner facts. Reuse existing
contact identity/suppression reconciliation with stable per-item receipts. Weak evidence
must keep identity review required; existing suppression/corrections/review conflicts
cannot be cleared by import. Verify complete rows after triggers and roll back the whole
batch on any ACK failure. No provider calls or email sends accompany local imports.

Public research rules design 2026-11-17: first port the existing search-index query,
fixed role aliases, Unicode word/case/name rules and selected professional evidence
projection. Never fetch result URLs or retain raw search/vendor snippets. Deduplicate
canonical professional URLs before marking equal folded names ambiguous. Provider
titles remain source-reported candidates requiring independent identity review. Official
results must match the exact reviewed company domain and named professional role;
observed time and permission provenance remain explicit. These pure parsers confer no
transport/budget authority. Then compose durable original search admission, retained
findings and owner-fenced conservative local ingestion using existing contact identity
rules; unknown search charges and original intents must survive restart without replay.

Startup registry/host design 2026-11-17: expose original public source metadata from
bounded private configuration, separate saved prerequisites from current probes and
native implementation availability. Never expose board names, actor inputs, keys or
operator evidence URLs. Keep unsupported directory collection explicit and manual
imports subject to per-import rights confirmation. Public search requires both local
credentials and a validated saved permission URL; mere rights flags cannot make it
available. Source/status and preview perform zero provider requests and zero writes.
Preview reads one read-only repeatable snapshot for effective profile preferences.
Wire manual POST and retained run GET through the shared bounded transient host request
permit, preserving original claims, immutable history and sanitized errors. Unported
job-led orchestration must fail explicitly without admitting a pretend completed run.
Then implement provider orchestration and live verification as separate dependencies.

Apify configuration dependency design2026-11-17: freeze actual ActorConfiguration and port
its fixed input builder, public review URLs, pinned build, exact unique limit mapping,
enabled/review/24-hour expiry and inclusive hard-budget prerequisites. Keep schema-valid
configuration separate from current provider capability and one-time dispatch admission.
Port fixed denied actor/input patterns without executing inputs or reusing connected MCP
credentials. No default actor, implicit entitlement, cookies/session inputs or price claim.
Preserve Pydantic omitted-default versus explicit numeric coercion for exact request hashes.

Manual startup-run design2026-11-17: claim the original discovery_runs row and private
opaque invocation under the shared owner fence before ingestion. Match actual request hashes
with startup_ source prefix; idempotency replay returns retained run without reconstructing
authority. Complete permission-confirmed manual observations and company-scoped saved
ranking in one second SERIALIZABLE transaction, exact run/journal ACK and original180-second
deadline. Failed/cancelled work retains the original running claim for review, never resume,
refund or automatic replay. Read output qualifies expired running records without GET writes
and strips private input/journal/unknown fields. This manual-only domain slice precedes the
full source registry, provider orchestration and host route integration; no fake provider PASS.

Canonical company ingestion design2026-11-17: source ID, then exact normalized domain,
then attributable source URL form the actual legacy identity key. Under owner-first
SERIALIZABLE and the existing ingestion advisory fence, reject source mappings to multiple
companies, conflicting domains and URL-only display-name changes; name alone never merges
companies. Preserve all current company facts; fill only a missing domain after explicit
identity-review checks. Add normalized immutable company observations with actual content
hash and unique replay identity, preserving original run/time/status on duplicate. Complete
company/observation ACKs and post-trigger reloads roll back the entire transaction on drift.
No provider fetch or new application authority is associated with a local import.

Research input contracts design2026-11-17: freeze actual company observations/startup runs
and public/manual/official people query DTOs before any provider work. Preserve observed
timezone/time limits, strict exact counts, public URL validation, actual company-domain
normalization, attributable published-email pairs and manual import permission rules.
Source labels and owner-confirmed claims remain data, never transport grants. Normalize
only declared fields, bound nested lists/bytes and compare actual schema/validator behavior
with fictional records. No DNS/page fetch, provider/account call or new budget admission.

Catalog/search/shortlist design2026-11-17: GET and typed POST search use the same actual
filter normalization and read-only repeatable-read snapshot. Limit candidate companies500
after optional source/shortlist predicates; fail above this cap, never truncate total/ranking.
Reuse derived detail's private bounded job snapshot for filters/history, load packet states
in one bounded set and preserve submission evidence versus preparation/interview/rejection.
Rank all qualifying companies before pagination; aggregate byte/inventory caps fail closed.
Company detail reads actual shortlist state. Shortlist is one owner-first SERIALIZABLE
insert preserving the original saved snapshot/note/run on replay, with complete insert and
post-trigger ACK; validate referenced existing startup run without invoking providers. No
application/queue transition or provider call accompanies search or shortlist.

Derived startup detail design2026-11-17: build profile, company observations, jobs/current
board evidence and professional contact counts in one read-only repeatable-read transaction
with one database clock. Bound inventories and expanded bytes; select only needed job
metadata and normalized declared company attributes. Do not promote legacy company metadata
to public facts. Reuse existing contact projection/retention rules and aggregate complete
bounded counts, excluding suppressed/review/future contacts. Feed only a supported-contact
summary to pure relevance. Publish current source-qualified size/hiring/profile version and
missing facts; retain no private profile/contact fields in the public detail. Detail first;
search/shortlist composition follows over the same private snapshot functions.

Startup ranking design2026-11-17: reuse the existing deterministic domain discovery matcher
for saved profile/job relevance, then port actual company relevance weights/reasons/missing
facts/exclusions. Strip candidate PII from matcher inputs, preserve unknowns and exact
profile version, and keep the score explicitly relevance_not_probability. Use observed
attributes only for technology/location/stage boosts; no score establishes a verified fact,
mailbox, team size or application eligibility. Catalog history filtering and submission
guards remain separate. Bound jobs/contacts/input JSON and add actual-source oracle coverage.

Company intelligence design2026-11-17: port actual latest-per-source size claims, human
confirmation preference, overlapping band/count conflict detection and non-inferred chosen
snapshot. Hiring uses saved job/current-board evidence, expiry/closed markers and attributable
company statements; absence of jobs is never a negative statement. Bound all inventories and
retain source labels. Add explicit conservative corrections: future observations are not
fresh evidence, and a negative hiring statement needs its recorded authoritative flag even
for older stored rows. Compare actual legacy functions on valid historical fixtures; keep
these intentional corrections in separate regression assertions. No IO, mutation or activation.

Startup contract/filter design2026-11-17: freeze actual StartupFilters/ShortlistInput through
AST-only loading, retain request defaults/coercions/explicit optional values and expose
bounded repeated-list GET parsing. Port actual size bands, strict min/max/exact count,
role/location/industry rules before derived catalog work. Unknown/range evidence never
becomes an inferred headcount; AI must not match retail. Early-stage remains an explicit
editable opt-in, never a restored owner restriction. Add actual-source oracle fixtures now,
but do not run them before the final combined gate.

Saved company read design2026-11-17: port company people and startup jobs/evidence before
derived catalog scoring/search. One read-only repeatable-read snapshot checks the exact
company, uses stable bounded pagination/counts and exposes public selected columns only.
People evidence retains bounded text/manual mode, never raw vendor fields/mailbox proof.
Company observations expose only normalized declared attributes and validated public links;
old/future observations remain qualified. Reuse the actual job catalog projection instead
of another DTO serializer. No GET writes, provider/network probes, owner mutex or cleanup.

Dashboard draft recovery design2026-11-17: persist only contact/request/draft UUIDs before
local creation, retain exact request scope through response loss and use GET once a draft
ID is known. Reject corrupt/unbound storage or responses before another request; never
navigate to an absent draft ID when facts are missing. Preparing another draft requires
review of the matching saved local draft and no historical send attempt/sent status; keep
the old row and require a fresh key. Requests remain local use_llm=false, mutation retries
disabled. No private body, email or candidate facts are stored in browser recovery metadata.

Outreach writer/controller design2026-11-17: local preview is read-only and local creation
uses the existing ledger. Optional REST rewriting requires a stable caller idempotency key
and one original120-second opaque invocation committed before calling the existing governed
answer writer. Preview/create intents are distinct. Do not hold owner/material locks or a
transaction over model IO. Recheck original journal and complete current context before
persisting; changed/late results are held and cannot create a draft. Repeated completed
requests return retained findings/original drafts; interrupted admissions never renew or
redispatch. Use the shared transient host permit/connection and60-second endpoint bound.
Provider settings/budgets and grounding remain those of the existing answer writer. MCP
composition remains local regardless of use_llm. No sending/provider entitlement is granted.

Outreach local lifecycle design2026-11-17: preserve outreach_logs as the single draft
ledger. Owner-fenced serializable local creation checks idempotency before composition and
persists exact snapshot/content/revision in one transaction. No narrative request enters
this local-only function. Reads/list/eligibility remain read-only. Edits and decisions check
expected revision, refuse every historical send attempt/sent row, update once and verify the
complete row both in RETURNING and after triggers. Approval binds resulting revision,
recipient/content and current evidence digest; unsupported edited sentences require new
grounding. Old incompatible snapshots require regeneration. No approval grants sending.

Outreach snapshot design2026-11-17: use read-only repeatable-read snapshots for previews;
mutations take the existing owner fence first, then company/contact/job/profile/evidence/
resource locks in fixed order. Require the primary profile's exact saved owner confirmation,
current exact employer association, non-suppressed identity and fresh person-specific
business mailbox evidence; provider-reported remains explicitly unverified. Bind complete
bounded candidate evidence/resource inventories, canonical profile, company/contact and
contact evidence, corrected saved job digest, owner confirmation and approved local-project
snapshot. Use approved local projects before profile/evidence fallback. Only validated public
HTTPS links enter copy. Full private snapshots stay out of preview/history responses.

Grounded outreach design2026-11-17: freeze actual draft input/edit/decision DTOs and preserve
the original outreach_logs revision/content/evidence approval semantics. Read history never
sends or invents delivery proof; expired prepared/attempting records are qualified in the
response without GET writes. Build draft context from current confirmed profile/project
evidence, current exact employer/contact evidence and public saved links; sender/login
data is separate. Read and mutation snapshots bind all material facts. Candidate/source
claims and provider-reported mailboxes remain qualified, every draft requires owner review,
and no approval enables Gmail sending. Optional rewriting uses the existing bounded grounded
answer writer outside locks, then rechecks the complete snapshot before persistence. New
context digests include approved local project snapshots; older incompatible drafts require
regeneration instead of retroactive approval. Never treat HTTP/model success as a send receipt.

Owner enrichment controller design2026-11-17: finish local-first discovered-person and
confirmed saved business-evidence ingestion before fixed provider lookup. Use one shared
transient host permit/connection, never hold the owner mutex or transaction over HTTP.
Keep a bounded80-second work budget/90-second endpoint and original180-second run lease;
each metadata deadline is15 seconds and a billable request starts only with its full
configured timeout plus persistence margin remaining. Cancellation/response loss leaves
durable prepared/admitted intents and full reserved costs, never a resumed POST. Finalize
local run counts/errors/candidate-pattern research with exact ACK and immutable finish
receipt; unresolved admitted work makes the result billing-uncertain. The frontend keeps
one idempotency key for a reviewed attempt and must review retained history before another
attempt. Scope remains business-evidence discovery/local drafts; no sending or purchases.

Provider result design2026-11-17: transport binds its outcome to the consumed dispatch
invocation/reservation/provider/request and a private content hash. Persist that immutable
normalized result plus lookup/budget finding and one run-usage entry before identity
ingestion, including expired/changed target contexts. No refund or second POST is possible.
Repeated identical record returns retained finding; differing outcomes cannot overwrite it.
Identity ingestion is a separate owner-fenced transaction with original company/target
version checks and idempotent observation receipts. Persisted late results stay reviewable
without mutating a changed contact. Only completed, successfully reconciled matching
profile results without a company email may enable the already-reviewed explicit fallback.
All provider/identity/runtime changes remain source-only until the coordinated final gate.

Identity ingestion design2026-11-17: reconcile normalized observations under the shared
owner/company/contact locks with bounded inventory byte/row limits. Resolve batched saved
identity mappings/tombstones, exact canonical profiles/business mailboxes and only current
owner-confirmed exact-source/name/role support; name alone never merges people. Preserve
suppression and owner-corrected facts. Conflicting names/profiles/mappings/mailboxes record
review evidence, retain existing facts and cannot become fallback eligibility. Use complete
contact/identity/evidence ACKs plus immutable per-observation receipt; identical replay
returns the retained finding without refreshing timestamps or appending evidence. Provider
claims never create mailbox verification. Existing generic inbox evidence stays company
level. No network IO or application policy edits occur in reconciliation transactions.

Fixed contact transport design2026-11-17: freeze actual person/request DTOs and construct
all network bodies from a consumed native dispatch grant, never arbitrary request JSON.
One HTTP client uses fixed Apollo/SignalHire origins, no redirects/proxy/retries, bounded
response/deadline/header parsing and provider-specific headers; loopback substitution is
fixture-only. Fresh single-use opaque capability observations bind provider/key/operation/
cost and expire before final database dispatch admission. Keep introspection distinct from
billable POSTs; preserve unexpected async IDs/unknown outcomes without another POST.
Normalize public professional identity/business mailbox fields only, never raw vendor
phone/personal fields. Provider-returned mailboxes remain provider-reported claims.

Contact per-target admission design2026-11-17: recheck the original native run, current
company/contact/version and local-first role/cache policy in the same owner-fenced
SERIALIZABLE transaction as a unique lookup claim, immutable private intent and positive
credit reservation. A prepared lookup is not a dispatch grant. Preserve every old claim;
only known completed/not-found expired cache entries may receive a new explicit run claim,
while running/unknown/failed/billing-uncertain entries remain non-replayable. Enforce
original provider order, per-run credits/unique-person limits and evidence-backed fallback.
Paid contact enrichment requires an existing canonical professional profile identifier;
search is primary Apollo only after bounded matching local inventories are empty. No
provider request is sent by preparation; final one-time dispatch/capability checks follow.

Contact run admission design2026-11-17: create the original enrichment run and an immutable
native invocation journal atomically under the shared owner fence. Bind company snapshot,
actual legacy ordered request hash, normalized request and180-second nonrenewable token
lease. An idempotency replay returns retained history only; it never recovers dispatch
authority, adopts a legacy run or renews an abandoned invocation. Guards recheck exact
run/company/request/configuration before later lookup admission. The run token stays
opaque/nonserialized. No provider calls or paid lookup permission are added by starting
or checking a run; lookup intent, live capability and credit admission remain separate.

Apollo capability parser design2026-11-17: separate pure endpoint-rate/credit-pool parsing
and24-hour operator eligibility checks from future fixed-endpoint HTTP. Preserve integral
allowance arithmetic/unique endpoint identity, add the documented credit wrapper, and
refuse simultaneous root/wrapped pool claims. Never aggregate unrelated credit types.
Rate exhaustion and unknown schemas block lookup; provider metadata is not billable
authorization, account setup, a budget reservation or installed dispatch readiness.

Contact credit ledger design2026-11-17: port existing discovery monthly/reservation tables
with integer credit estimates and SQL numeric accounting, not floating arithmetic. Shared
owner/SERIALIZABLE transactions commit reservation plus monthly increment before any
future remote action. Every reservation identity is single-use; provider-reported actuals
remain audit data and cannot refund the reserved cap. Finish is a guarded one-way state
transition with idempotent identical acknowledgment, fixed terminal states and exact
returned fields. Cooldown is monotonic across bounded saved provider months, including a
new zero-reserved current-month row. The ledger itself grants no provider entitlement,
does not perform IO and is not exposed as a remotely callable budget-control endpoint.

Contact provider source design2026-11-17: port read-only local-first enrichment preview,
saved monthly budget/configuration status and retained run review before provider IO.
Freeze actual EnrichInput alongside ContactCorrection. RR read-only snapshots keep budget
status separate from provider balance, live eligibility and installed execution readiness.
Match actual role aliases/cache lookup/fallback policy; cap contacts1000/people100 and
disclose truncation. Preview reserves nothing, even with allow_paid. Historical run review
whitelists structured fields and fixed failure codes, never raw exception text/vendor
records. The later durable lookup/credit admission and identity ingestion use the shared
owner fence and immutable intents, with no unknown resubmission or implicit fallback.

Contact correction design2026-11-17: freeze the actual `ContactCorrection` DTO without
service/config imports; add owner-only PATCH on the existing detail route. Public saved
rows expose an opaque PostgreSQL row-version/updated-time precondition, required through
If-Match before correction. Use SERIALIZABLE/shared owner fence, old/new company locks
in UUID order, then contact lock. Recheck the complete precondition and mailbox evidence;
never treat identity evidence/provider claims as mailbox verification. Company changes
require no retained email and bounded exact identity deletion. Append one immutable
human-correction evidence row with exact insert ACK; compare the complete contact update
ACK and roll back all changes on mismatch. A lost response cannot replay the old version.
No provider action, queue/policy edit or new sending permission is part of correction.

Use the canonical Rust/Tokio/Axum/SQLx runtime and existing PostgreSQL state. Finish
research, contracts and module boundaries before implementing the remaining services;
write their regression fixtures during implementation but execute the combined local
acceptance once the complete source is integrated. Preserve the installed legacy family
until STOP-only whole-family cutover is ready. This plan supplements the existing
[migration plan](2026-11-14-rust-agent-migration.md), not a replacement of its scope.

For new Naukri worker receipts, retain the exact browser Apply acknowledgment with its admitted action, original document and account. Require the acknowledgment to precede both independent history observations. An admitted action with no acknowledgment can still be reconciled without replay, but the resulting history cannot enable recurring AUTOMATIC. Prior manual packet evidence stays immutable and prevents attribution of that packet to the worker. Keep legacy receipt history readable.

After an acknowledged Naukri questionnaire answer, inspect the retained original document for a closed drawer and a positive Applied status. Reuse the existing account and listing observer. Match both isolated-world document identity and browser document identity. A positive result schedules independent history reads and carries no submission receipt. The worker keeps the original tab and quota history through verification. An unrecognized drawer, changed document, account mismatch or absent Applied marker retains the existing uncertainty path.

## Scope

- In: complete native runtime/API/worker/CLI parity; agent tools and dashboard controls;
  Naukri, Instahyre, Wellfound, YC Work at a Startup, Internshala, HiringCafe, Himalayas
  and WWR; Apify discovery integration; owner-bound Telegram; Gmail reads/drafts;
  account-independent continuity; deployment/recovery/performance/live evidence.
- Out: Gmail sending, purchases/subscriptions, CAPTCHA/rate-limit bypass, automatic
  owner-window activation, implicit Chrome fallback, unknown-action replay, fifth Naukri
  admission, cleanup or hosted Actions. Safari and private Drive OAuth/download remain
  deferred by the existing scope decisions; preserve manual PDF and saved review.

## Current evidence and working method

Published implementation `9c4ace570535a5856184775f8045ee89eafdd05f` and report commit
`0f6eae9` provide the last complete validated source checkpoint:193 standard Rust tests
+262 disposable native PostgreSQL tests,455 distinct. Fixtures are not live acceptance.
Uncommitted `browser_profiles/forms.rs`, three form schemas and `tests/browser_forms.rs`
are useful work in progress; preserve them. They currently provide pure validation,
field policy/control transformation and receipt classification, not a form service.

Owner's newest instruction: plan/structure/research first, write all remaining source,
then run tests together at the end; do not repeatedly run suites. Accordingly:

1. Complete the source/contract inventory and record design/research decisions here.
2. Implement the files below in dependency order, reading legacy behavior before each
   port. Add meaningful regression fixtures alongside code without running them yet.
3. Use code review and explicit NOT TESTED records during implementation. Do not describe
   new source as correct/accepted merely because it exists. No untested install/cutover.
4. Run the combined acceptance after all agreed source units are integrated. Fix actual
   failures and rerun affected checks; repeat the whole cycle only for integration risk.
5. Record local intermediate milestones with prior evidence identified as prior and
   new validation explicitly NOT TESTED. Keep this resume record current across accounts.

Static inventory read243 decorated API route declarations from21 Python source files
without importing application configuration. These are declarations, not an API coverage
score: `include_router` prefix composition, mounts, disabled routes and native variants
require reconciliation against the frozen OpenAPI and frontend/extension callers.
Private inventory `.local/completion-route-inventory.json` contains source paths only.

## Ordered actions

Keep the current Rust candidate and installed Python rollback pair while proving
the first supervised Naukri receipt. Use targeted Rust tests or frontend type
checks for repairs, then run the full local release gate. Keep compatibility
where it protects retained state, request identities and API behavior.

Use the existing isolated Brave fixture path to evaluate unattended browser
work without involving personal profiles. The first receipt still needs the
existing focus, identity, resume, quota and independent history checks. Keep
other providers within their approved discovery and assisted handoff paths
until their submission flows have their own evidence. Evaluate relational
queue storage and bounded connection pooling after collecting baseline lock
and STOP latency measurements.

- [x] Inventory the saved plan, current branch, ownership, runtime boundaries and remaining
  route declarations; preserve in-progress form code and published rollback evidence.
- [x] Research protocol, source attribution, transaction and permission boundaries; record
  primary references in [the research record](completion-research-20261116.md).
- [ ] Finish native form inspection/review/consume/receipts and contextual owner questions,
  including old late receipts, canonical PDF checks and transactional execution evidence.
- [ ] Port the complete application queue/worker/kernel: policy, discovery/profile checks,
  filter reconsideration, identity/resume binding, quotas, admission, original forms,
  uploads, questions, independent history reconciliation and immutable strict receipts.
- [ ] Finish legacy Gmail account variants, read-history/alerts/retention and draft workspace;
  port contacts, outreach drafts, saved startup/company operations and remaining dashboard APIs.
- [ ] Finish provider/CLI/local fallback/rearranger and legacy Telegram command parity;
  keep grants, ledgers, safe process invocation and non-replay semantics shared.
- [ ] Implement the eight platform adapters and shared dashboard/MCP capability controls;
  reconcile every legacy route and worker entry with the native coverage ledger.
- [ ] Complete test infrastructure/corpora and run the combined final acceptance: contracts,
  unit, native PostgreSQL, API/auth, browser, UI, concurrency/recovery and build checks.
- [ ] Perform reviewed STOP-only migration/install/rollback and actual Mac focus, connection,
  resource, restart, awake/locked and independently verified per-platform application checks.
- [ ] Record final exact local results and remaining external gates. Completion requires
  all applicable acceptance gates. Keep publication and merges suspended.

## File structure and ownership

All paths are relative to the canonical checkout and owned by its existing `/root` task.
Use existing modules when they already own the behavior; proposed paths below are design
targets, not empty scaffolding or accepted features. No new clone/worktree/source release.

| Area | Existing owner / implementation files to finish | Contract / dependencies |
| --- | --- | --- |
| Browser form core | `rust/agent-runtime/src/browser_profiles/forms.rs`; split service IO into `browser_profiles/form_service.rs`, `form_review.rs`, `form_receipts.rs` when implemented | Frozen `schemas/form-{inspection,fill-plan,fill-receipt}.json`; existing native schema; task/broker/profile/packet/answer services |
| Browser questions | `browser_profiles/form_questions.rs`; existing `tasks.rs` integration | Stable contextual field identities; final packet revision before queuing sibling questions; existing owner delivery channel |
| Native execution policy/queue | `execution.rs`, `execution/{contracts,policy,queue,history,questions,worker}.rs` | Existing `exec:`, `apply_work:`, queue policy/automation revisions, owner lock; no new live DDL by runtime |
| Naukri kernel | `execution/naukri/{identity,discovery,profile_sync,eligibility,admission,forms,upload,submission,receipts,reconciliation}.rs` | Existing extension Naukri contracts; confirmed profile/PDF; lifetime4/hour1; first strict receipt; original-document binding |
| Provider adapters | `platforms.rs`, `platforms/{naukri,instahyre,wellfound,yc,internshala,hiringcafe,himalayas,wwr}.rs` | Shared bounded discover/inspect/prepare/review/apply/reconcile contract; platform-specific capability proof, account/revision and budget |
| Gmail account variants | `gmail_accounts.rs`, `gmail_accounts/{contracts,storage,oauth,refresh,routes}.rs` | Existing Google OAuth + account token envelope; local mailbox services reused; no send; optional schema overlay readiness |
| History/alerts/workspace | `gmail_accounts/{history,selection,retention,alerts,workspace,drafts}.rs`; existing MIME/evidence/draft transports | Explicit read/body consent; selected folders/labels/senders; durable generation/cursor/lease; exact reviewed draft hash |
| Provider/fallback/CLI | Existing `answer_service.rs`, `model_policy.rs`, `provider*.rs`, `gemini.rs`, `ollama.rs`; new narrow `cli_provider.rs`, `local_fallback.rs`, `rearranger.rs` | Fixed command argv/environment/size/time; no arbitrary shell; grant/ledger/context checks; no implicit model download/start |
| Telegram/control | Existing `telegram.rs`, `tool_api.rs`, `mcp_bridge.rs`; `telegram_commands.rs` | Same durable questions/queue broker; private owner user/chat binding; unknown delivery quarantine |
| Legacy service parity | `contacts.rs`, `outreach.rs`, `companies.rs`, `startup_catalog.rs`, `dashboard.rs`, `legacy_agent.rs` with narrow submodules | Existing routes/data/CAS/history; email discovery evidence/budgets; drafts only; disabled sending remains explicitly blocked |
| Operations/packaging | Existing `main.rs`, `configuration.rs`, `process_lock.rs`, native/document/MCP crates; `rust/scripts/` operator tools | Whole writer-family lock, reviewed schema manifest, private config, immutable install inventory/rollback; zero Python production runtime |
| UI/MCP wiring | Existing Next BFF/workflow feature/API paths, generated API types, `.vscode/mcp.json`, extension worker modules | Shared HTTP policy, token/private IPC, honest capabilities/status; no direct browser bearer or owner-signing keys |
| Tests/evidence | `tests/browser_forms.rs`, `tests/support/*_pg.rs`, `tests/fixtures/`; frontend tests/e2e; extension tests; `scripts/run_acceptance.py` | Add tests during implementation; defer execution to final combined gate; raw private logs stay ignored |

## Design decisions before coding

**Transactions:** preserve owner-before-execution/task/packet/material ordering. Normal
status/checkpoint reads use a coherent read snapshot without owner locks; mutation paths
reacquire and reread after waiting. No model/network wait may hold the control connection
or owner lock. Prepare/propose outside the mutation, then validate all bound stamps and
commit an intent before a side effect. After IO, recheck generation/context before saving.
Savepoint rejection must finish rollback. Lost commit is unknown; reconnect does not replay.

**Forms:** freeze actual DTO defaults/limits; treat labels/options/site text as untrusted.
The pure transformation already compares actual legacy policy/controls/receipt branches.
Inspection proposes evidence-backed values; exact field approval and one consumption are
separate. Revalidate profile, packet, destination, expiry, approved project digest, missing
answer generation and canonical PDF bytes. Partial/delayed receipts retain provenance
without authorizing new work or changing a transferred task. Unsupported required controls
and unresolved challenges prevent completion. Uploaded bytes and human facts are never invented.

**Queue/kernel:** keep current online durable records and consumed admissions; defaults
never overwrite saved policy. Discovery/filtering and30-minute portal/profile checks run
independently of model calls. Unknown outcome is a reconciliation-only state. Naukri is
validated first; other platforms need their own account binding and explicit action budget.
Job age14/applicants1000/score50/any verified skill remain editable saved controls.

**Providers/MCP:** use fixed outbound endpoints/allowlisted tools and bounded payloads.
SDK tool annotations describe behavior but are not authorization. Apify public docs/actor
discovery are configured; actor execution/storage requires credentials and an explicit
budget. No entitlement or purchase is inferred. Verified provider facts stay separate from
untrusted scraped text. The Himalayas applicationLink/source credit and WWR backlinks must
survive ingestion and handoff; trackers/feed entries are not application receipts.

**Scope parity:** preserve legitimate existing behavior rather than deleting features to
claim full Rust migration. Historical sending endpoints stay refusal-only under the newer
READ + CREATE DRAFT ONLY instruction. Optional Drive/Safari remain explicit deferred scope.
Connected helper/IDE apps are development tools, not application runtime credentials.

## Final test matrix and ordering

Gmail history port structure: freeze the actual HistoryReview/Version/Retention declarations
through AST-only schema export; implement pure normalization and retained-record validation
in `gmail_history/contract.rs`, then owner-fenced local review/forget/retention/read-only list
and bounded expiry maintenance in `gmail_history.rs`. Reuse existing canonical ATS URL and
reviewed-history duplicate guards. Evidence must belong to the explicitly selected account
and be unexpired; owner-confirmed status stays monotonic across mailbox evidence merges.
No mailbox IO or message-derived automatic confirmation. GET omits expired records without
writing; bounded maintenance scrubs expired stored metadata separately on the execution
connection. Complete legacy read-account/OAuth/selection/sync and alert/draft workspace
services follow this local-history dependency; local-slot services remain independent.

Legacy read-account IO continues in `gmail_accounts/oauth.rs` and `refresh.rs`: preserve
the read.* callback namespace, original encrypted token/verifier purposes, account chooser
and workspace slot identities. Commit exact one-use callback consumption before code
exchange; commit a durable refresh intent before refresh/identity IO, release owner/account
locks during every request, and recheck account generation/identity/scopes/intent before
publishing. An abandoned refresh becomes reauthorization-required, never silently replayed.
Disconnect fences local account/policy/evidence/OAuth state before best-effort revocation.
Use the shared transient connection/long-request permit, fixed Google endpoints, scope
equality, mailbox allowlist and separate outreach-account guard. Legacy send upgrades stay
refusal-only. Callback routing must preserve the existing mailbox.* local account handler.

Selected sync structure: `gmail_accounts/sync_rules.rs` owns calendar-clamped history
windows, folder progression, metadata filters and uncertain-only projections;
`gmail_accounts/sync.rs` owns committed120s selection/account leases, batched per-page
message-ID deduplication, guard-before-read, bounded GET-only IO and atomic evidence plus
checkpoint publication. Retention of decrypted metadata needs its existing opt-in. No raw
body is persisted. All status inferences remain requires_review/confirmed=false. Lease
expiry, reconnect, disconnect or a new selection prevents stale evidence publication;
failed selected reads preserve their checkpoint and may repeat bounded GETs only.

Reviewed email-link import is a local transaction in `gmail_accounts/lead_import.rs`:
require the exact selected account/message/unexpired link and actual LeadImport owner
review, then conservative source/URL/company identity and source observations. Preserve
canonical human decisions and employer associations, keep imported vacancies unverified,
and mark per-URL message import references only after an acknowledged durable job write.
Similarity can produce review hints but cannot merge. No opening URLs, provider calls,
eligibility guesses or auto-application follows this owner import operation.

Local mailbox alert structure: `mailboxes/alerts.rs` owns actual AlertPolicy, account/
automation revision-bound leases, fixed official-sender Gmail reads and safe cursor/error
publication; split pure authentication/query/candidate rules into `mailboxes/alert_rules.rs`
and candidate/notification persistence into `mailboxes/alert_candidates.rs`. Reuse existing
read-only transport/MIME and owner notifications. Require the receiving mx.google.com DMARC
and DKIM result before full-body access, then recheck it. Deduplicate requisitions across
accounts without inventing employer/title/vacancy or writing jobs. Preserve prior/uncertain
applications. Schedule on the same transient permit as questionnaire inference, with fair
selection and no additional persistent connection; disabled/not-due hints avoid owner locks.
Audit abandoned local-mailbox refresh leases too: expired uncertain refreshes require
reauthorization, never restart into another provider refresh.

Three-role workspace structure: `gmail_workspace.rs` owns read-only coherent role/status
projection and local draft list/save/edit, with `gmail_workspace/contract.rs` freezing
actual AccountConsent/DraftInput/DraftApproval models. `gmail_workspace/account.rs` will
own original draft.* OAuth, separate compose-only account, exact legacy token purposes
and durable non-replayed refresh outcomes; `gmail_workspace/dispatch.rs` will own explicit
reviewed draft creation with immutable intent before its one POST, current account/profile/
content/version checks and unknown-safe reconciliation. Reuse selected read-account
authorization for fixed read_1/read_2 roles without moving/adopting another role identity.
Local drafts remain purpose-bound encrypted, with legacy Python canonical content hashes;
local edits require current reviewed profile and exact version and cannot overwrite
dispatching/unknown/saved drafts. Freeze current behavior before adding IO routes, preserve
the existing frontend and gateway contracts, and add deferred actual DTO/hash/profile/CAS/
auth/lost-response fixtures. A saved local draft is not a Gmail draft or sent message.

Legacy single-account integration parity remains separate from the three-role workspace:
`gmail_legacy.rs` will first expose existing saved status through public-column-only SQL,
label recorded verification separately from current probes and force send/modify capability
off regardless of an older deployment flag. Preserve legacy read/compose scope facts without
activating them. Historical outreach send/send-preview routes must be explicit owner-only
policy refusals with zero account/token/send-attempt work. Then port original unprefixed
OAuth, exact connected_accounts/oauth_states identity and token purposes, durable refresh,
verify and local-first disconnect; do not alias/rebind the account into another family.
Connector/provider registry and historical outreach read routes follow the saved-status
dependency. Add actual projection and isolated auth/no-write fixtures before the final gate.

Saved contact structure: `contacts/rules.rs` ports explainable role/team-size/job relevance,
freshness/email categories/publication bindings and retention projection; it cannot grant
email sending. `contacts.rs` owns company contact filters, contact/evidence details and
bounded saved-job recommendations in coherent read-only snapshots. Preserve suppression,
current evidence versus provider claims, stable ID tie order and original profile/employer
associations. Query only needed metadata, bound job references/evidence/pages and reject
malformed saved context; avoid paid/provider IO or GET writes. Freeze actual rules through
AST-only oracles and add isolated filtering/privacy/expiry/auth fixtures. Owner correction,
professional people discovery/enrichment budgets and grounded local outreach follow this
read dependency, using the same owner fence and immutable unknown-intent rules.

The existing runner is the starting point, not yet a complete end-to-end gate: it omits
UI/browser journeys, several extension browser fixture suites and PostgreSQL-backed Python
integration. Extend it during source integration with a disposable DB lifecycle and strict
stage isolation. Do not run it now or operate the owner's browser to execute fixtures.

| Stage | Planned verification |
| --- | --- |
| Static contracts | HTTP security drift, schema/OpenAPI/frontend/native DTO parity, native route coverage, manual-only hosted workflows, secret-free artifacts |
| Rust unit/oracles | One full locked workspace run including form policy/projection/receipt, quota, broker, provider/MCP/native/document protocols |
| Database integration | Disposable PostgreSQL tests for guards, concurrency, locks, rollback, crash and replay. Rehearse the reviewed migration in a separate disposable cluster and verify its catalog and grants against the pinned manifest. |
| Legacy parity | Python unit + PostgreSQL fixture integration using uv and isolated config; no real candidate DB or optional paid provider |
| UI/build | Frontend unit/typecheck/format/production build and generated API drift |
| Browser fixtures | Isolated headless Brave journeys for extension/native/task/form/Naukri queue; Edge build/fixture where available; frontend auth/review/control/accessibility journeys; no personal profiles |
| MCP/API integration | Real framed process and stdio/HTTP/socket calls into native host with fictional DB/providers; authentication/CSRF/signature/peer boundary tests |
| Resource/recovery | Same hardware/workload comparison of total processes, CPU/RSS, latency/Stop under load, connection peak and24-hour awake/locked observation after install |
| Live per-platform | Account/session/PDF proof, eligible inspected vacancy, authorized admission, exact truthful screening/upload and independent durable receipt; provider unavailable remains BLOCKED, never fixture PASS |

Run a newly built Brave extension through the actual Rust native host into the
Rust HTTP router and disposable PostgreSQL in one combined fixture. Use an isolated
headless profile, a fictional portal page and the executable-adjacent host config.
Verify selecting the connected browser, reading STOPPED status, refusing Start with
commands disabled, and saving a scoped portal observation. Keep the existing legacy
browser tests and database-only harness. This fixture cannot establish live focus,
applicant identity, or provider submission.

Use the combined report's starting and ending Git commit and cleanliness for the
installation review. The report records a clean-commit fixture pass only when
every stage passed and both observations match a clean commit.

Only the final combined gate establishes current full-source test results. If an actual
failure requires a fix, run the affected regression and repeat integration checks needed
by that change; do not rerun every unrelated suite after every edit. Completion cannot be
guaranteed by planning; code review and this evidence gate determine correctness.

## Progress reporting

The earlier 55% and 58% estimates were engineering judgments from earlier milestones.
Now that the current branch has a [combined validation baseline](../acceptance/local-combined-baseline-20261118.md),
report the exact outcomes at each gate and the capabilities verified on the laptop.
Track each deliverable through source implementation, fixture verification, installation,
and live acceptance. Reserve 100% for all agreed deliverables and applicable final gates.

## External gates retained

Pending owner sign-in/physical browser step has already been asked; do not repeat it.
Remote runtime role lacks CREATE and Rust runtime tables need reviewed operator migration;
do not widen runtime grants. Preserve STOP while inventorying/quiescing every legacy writer.
Automatic Brave window creation is suspended after actual focus failure. No new production
side effect is inferred from source completion. Ask only when a genuinely missing fact or
unavoidable owner/OS action blocks dependent acceptance, while continuing independent work.
