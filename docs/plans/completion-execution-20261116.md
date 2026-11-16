# Complete-source delivery plan — 2026-11-16

Use the canonical Rust/Tokio/Axum/SQLx runtime and existing PostgreSQL state. Finish
research, contracts and module boundaries before implementing the remaining services;
write their regression fixtures during implementation but execute the combined local
acceptance once the complete source is integrated. Preserve the installed legacy family
until STOP-only whole-family cutover is ready. This plan supplements the existing
[migration plan](2026-11-14-rust-agent-migration.md), not a replacement of its scope.

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
5. Publish intermediate code milestones with prior evidence identified as prior and
   new validation explicitly NOT TESTED. Keep this resume record current across accounts.

Static inventory read243 decorated API route declarations from21 Python source files
without importing application configuration. These are declarations, not an API coverage
score: `include_router` prefix composition, mounts, disabled routes and native variants
require reconciliation against the frozen OpenAPI and frontend/extension callers.
Private inventory `.local/completion-route-inventory.json` contains source paths only.

## Ordered actions

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
- [ ] Publish final exact results/remaining external gates and merge only when the owner's
  completion and review conditions hold;100% requires all applicable acceptance gates.

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

The existing runner is the starting point, not yet a complete end-to-end gate: it omits
UI/browser journeys, several extension browser fixture suites and PostgreSQL-backed Python
integration. Extend it during source integration with a disposable DB lifecycle and strict
stage isolation. Do not run it now or operate the owner's browser to execute fixtures.

| Stage | Planned verification |
| --- | --- |
| Static contracts | HTTP security drift, schema/OpenAPI/frontend/native DTO parity, native route coverage, manual-only hosted workflows, secret-free artifacts |
| Rust unit/oracles | One full locked workspace run including form policy/projection/receipt, quota, broker, provider/MCP/native/document protocols |
| Database integration | One complete disposable native PostgreSQL run: production-equivalent guards, CAS/concurrency, real locks, role/schema checks, rollback/unknown commit, crash/restart/no replay |
| Legacy parity | Python unit + PostgreSQL fixture integration using uv and isolated config; no real candidate DB or optional paid provider |
| UI/build | Frontend unit/typecheck/format/production build and generated API drift |
| Browser fixtures | Isolated headless Brave journeys for extension/native/task/form/Naukri queue; Edge build/fixture where available; frontend auth/review/control/accessibility journeys; no personal profiles |
| MCP/API integration | Real framed process and stdio/HTTP/socket calls into native host with fictional DB/providers; authentication/CSRF/signature/peer boundary tests |
| Resource/recovery | Same hardware/workload comparison of total processes, CPU/RSS, latency/Stop under load, connection peak and24-hour awake/locked observation after install |
| Live per-platform | Account/session/PDF proof, eligible inspected vacancy, authorized admission, exact truthful screening/upload and independent durable receipt; provider unavailable remains BLOCKED, never fixture PASS |

Only the final combined gate establishes current full-source test results. If an actual
failure requires a fix, run the affected regression and repeat integration checks needed
by that change; do not rerun every unrelated suite after every edit. Completion cannot be
guaranteed by planning; code review and this evidence gate determine correctness.

## Progress reporting

The old55% number was a rough engineering estimate, not measured production acceptance.
After three published native browser lifecycle/broker/task milestones, report approximately
58% complete /42% remaining on the same rough basis. This is a judgment estimate, not route
coverage or a conversion from test counts. Hold it while new code is untested. Announce
meaningful increases in commentary with the completed capability and evidence; track source
implemented, fixture verified, installed and live accepted separately. Reserve100% for all
agreed deliverables and applicable final gates; do not claim external availability forever.

## External gates retained

Pending owner sign-in/physical browser step has already been asked; do not repeat it.
Remote runtime role lacks CREATE and Rust runtime tables need reviewed operator migration;
do not widen runtime grants. Preserve STOP while inventorying/quiescing every legacy writer.
Automatic Brave window creation is suspended after actual focus failure. No new production
side effect is inferred from source completion. Ask only when a genuinely missing fact or
unavoidable owner/OS action blocks dependent acceptance, while continuing independent work.
