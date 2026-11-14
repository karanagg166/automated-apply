# Rust and multi-agent migration

Owner request: replace Python runtime services with Rust, reduce measured Mac resource use,
and support coordinated AI agents using Telegram, browser and application tools.
Working branch: `feat/rust-agent-runtime`, stacked on `chore/uv-python-tooling` (PR #49).
The existing Python backend contains 355 tracked application modules / 56,272 lines;
this is a staged behavioral migration, not a claim that scaffolding replaces the backend.

## Acceptance sequence

1. Rust workspace, locked Cargo dependencies and low-contention compilation. Port native
   messaging transport, schema, private configuration, bounded reads, backend authentication,
   response validation and rollback-only retries. Compare against actual Python executable
   using fictional localhost HTTP requests on the owner's Mac. Preserve installed wrapper.
2. Durable coordinator with specialist discovery, matching, grounded-answer and review
   agents. Models propose typed tool calls; a separate broker enforces owner/policy grants.
   Bound active tasks, token/tool budgets and provider retries. Default local inference off.
   Persist agent handoffs, leases, budget consumption and uncertain side effects in PostgreSQL.
3. Port tool adapters and workers: existing extension transport, Telegram owner pairing,
   verified candidate/project/resume contexts, queue, history reconciliation and application
   admission. Preserve exact API/OpenAPI and extension contracts during cutover. Existing
   Python adapters are transitional dependencies until individually replaced and accepted.
4. Port REST/dashboard, database repositories, AI providers, Gmail read/draft and remaining
   maintenance commands. No runtime Python dependency is permitted at final acceptance.
5. Full contract/regression validation, isolated PostgreSQL failure/recovery checks, real Mac
   idle/loaded CPU/RSS/latency comparisons, and honest GPU evidence. Install immutable
   releases with rollback under STOP. Verify real account/history/policy/resume integrity,
   inactive browser focus and restored readiness. Do not replay quarantined jobs or exceed
   remaining admission allowance. Confirm actual receipt before recurring AUTOMATIC.

## Invariants

- pnpm for JavaScript; Cargo for Rust; uv for remaining Python tooling.
- No local model/GPU process starts merely because multiple agents exist. Prefer deterministic
  routing and reuse verified results; one browser executor and bounded model concurrency.
- PostgreSQL remains the durable queue; no Kafka, Redis or new live connection pool introduced
  during development. Fixture-only data may use in-memory test doubles.
- Model output, Telegram text, websites and job descriptions cannot grant privileges.
- Preserve current saved policy (age14, applicants1000, score50, any verified skill), history,
  hourly1, lifetime supervised cap3 and actual consumed admissions. Read current state at
  cutover; never overwrite it with defaults or assume the third attempt remains unused.
- Gmail READ + CREATE DRAFT ONLY. No CAPTCHA/rate-limit bypass, uncertain-action replay,
  owner keyboard/clipboard, active-tab edits or browser foreground changes.
- No Chrome WebUI/settings automatic navigation; native inactive setup path still needs
  complete real focus acceptance before unattended extension replacement.
- No hosted Actions, cleanup, deletion or merge before completed/reviewed/validated delivery.

## Completion ledger

Current profile ports include CRUD/CAS, saved-job matching, atomic owner confirmation,
saved-resume selection and read-only onboarding readiness. Milestone14 `f872319` passes
154 Rust tests (90 standard +64 dedicated PostgreSQL), with 95 URL/345 resume/80 readiness
comparisons inside one test. Resource/evidence writes, link resolution and rich private
context remain next. Installation and full Python removal have not happened.

| Deliverable | State |
| --- | --- |
| Rust native transport | Implemented;14tests +25parity examples +Mac fixture benchmark; uninstalled |
| Agent coordinator and specialist roles | Five-role saved-review worker runs actual SQL tools without inference; live action adapters pending |
| Durable PostgreSQL runtime and restart recovery | CAS controls, retained budgets, fair factual questions and quarantine tested; production migration/ACL/install pending |
| Verified profile / saved matching / history read tools | Implemented with actual PostgreSQL fixtures; 1,300 matching comparisons pass; uninstalled |
| Rust Telegram | Owner commands, Bot API and bound durable delivery integrated; actual CLI fixture passes; legacy commands/live acceptance pending |
| Rust browser / application adapters | Pending |
| Full Python removal and API parity | Pending |
| CPU / RSS / GPU resource acceptance | Native and warm matching component gains measured; whole-project/GPU acceptance pending |
| Immutable install / rollback / real submission acceptance | Not performed |

The session cannot self-resume after a platform usage-limit reset unless the hosting
application supplies scheduling. Keep this plan, commits and acceptance reports as the
resume record; do not implement a loop that attempts to bypass platform usage limits.

Milestone implementations: `fcb2722` native host and `52fdfa6` durable coordinator;
[PR#50](https://github.com/karanagg166/automated-apply/pull/50).

Provider milestone: `a7610ec` adds fixture-tested Cohere V2 and the shared legacy monthly
ledger.46Rust tests now pass (33standard+13native PostgreSQL), plus25parity examples.
No provider key, real cloud call, runtime installation or owner DB change. Worker routing,
actual tools, other providers and full backend/API migration remain open.

Matching/knowledge milestone: `6c6f43f` + `99b19fc`; 64 Rust tests pass (44 standard +
20 dedicated PostgreSQL), plus 1,300 scoring comparisons. Warm 1,300-case computation
uses 61.622ms Python versus 12.726ms Rust CPU in the published paired fixture benchmark.
Actual action adapters, worker lifecycle, full backend replacement and installed acceptance remain open.

Worker lifecycle milestone: explicit STOPPED default, revision-checked global/run controls,
atomic sanitized control audit, stale-worker fencing, persistent factual questions and fair
reconciliation. Deterministic saved review uses nine decisions/four actual SQL tools and zero
model calls. A host executable, private config/shared process lock, authenticated HTTP controls,
dashboard integration and reconnect supervision remain next; browser/Telegram/application
adapters, full Python removal and installed resource/receipt acceptance remain open.

Standalone host milestone: private literal configuration, guarded PostgreSQL TLS/target,
shared legacy execution lock, current-thread Tokio/Axum owner API and actual CLI/HTTP fixture
acceptance. Two persistent DB connections; no pool/overflow or process per role. Python-held
configuration/history is unchanged. Next: supervised reconnect, dashboard controls, rich
verified context, actual browser/Telegram/application tools and remaining API/service/provider
ports; then Python removal and installed resource/receipt acceptance. No live cutover yet.

Recovery/Telegram milestone: in-process bounded DB recovery, no HTTP write replay, shutdown
pause reconciliation, and an optional owner-bound Telegram relay/notification tool. Native
PostgreSQL/CLI/localhost Bot API fixtures cover real process recovery, cursor idempotency,
unknown-send quarantine and durable 600-second cooldown. Enabled mode uses three persistent
connections for the existing API/execution/Telegram roles; disabled mode retains two.
The saved-review path uses no inference. Remaining legacy REST/profile/resource/browser/
application/Gmail/provider/service ports, rich context and complete Telegram command parity
must be implemented before Python removal and live installation/resource/receipt acceptance.

Graph and approval milestone: durable plan/decision/validate/tool/observe/review stages,
bounded review loops, exact version/profile/result-bound owner decisions, and a private
Next.js workflow dashboard. Optional opt-in Cohere review now runs through the real Rust
host after actual read tools; local provider fixture verifies one replan, cooldown without
recharging, two inference reservations and human approval before completion. Deterministic
specialists remain the default. Tool availability is explicit; unmigrated application and
browser adapters cannot be activated by owner review. Continue with profile semantic/CRUD
ports and remaining REST/services before full Python removal and live resource acceptance.

Primary profile milestone: pure Rust create/update/ORM-read normalization, 779 fictional
Python DTO comparisons, Unicode/IDNA snapshots and strong ETag parsing. Standalone owner
GET/PUT/PATCH now uses existing PG API connection with complete merged validation, CAS,
commit-before-ACK, no-op/raw normalization distinction and preserved resume/history/
confirmation. Native PG fixtures cover concurrent changes and forced response/commit
rollback. Uninstalled; legacy proxy untouched. Sanitized validation detail strings replace
the full FastAPI input-error array. Profile saved-job match, readiness/confirmation,
resources/context and all remaining services still need ports and live acceptance.

Multiple-model role milestone: opt-in discovery planner plus reviewer, each with separate
model instructions and constrained runtime decisions after real source reads. New owner API
runs pin provider/model/roles in idempotency and approval bindings. Configuration changes
cannot silently upgrade/downgrade a pinned run; missing models pause without new spend.
Deterministic defaults and Telegram reviews remain zero inference. Dual-role recommended
budgets fit four calls/one replan within the existing16,000 total cap; actual CLI localhost
model fixture verifies discovery+review+re-review, monthly3 requests,7SQLreads and human
gate. Remaining tool adapters, feature/API ports and installed resource/live acceptance
remain open; multiple actual cloud role calls have not been exercised.

Saved-profile match endpoint: protected POST/api/v1/jobs/<UUID>/match reuses the pure Rust
base scorer, reads the saved job/profile, preserves missing-record order and unknown
experience, and ignores caller profile overrides. Native PG/HTTP fixtures verify exact
results with no score/profile/history writes, AI usage or application creation. Uninstalled;
remaining profile readiness/confirmation/resources/context and other services still pending.

Owner profile confirmation: POST/local-agent/profile-confirmation now locks the primary
profile, binds explicit review to its expected version, and atomically requests the legacy
safe filter recheck when the version was not already confirmed. Repeated current review
retains recheck progress; changed versions/failure roll back without quota/history/fact
changes. Native PG/HTTP tests cover commit visibility, delegated client refusal, a concurrent
version change and failed recheck persistence. Uninstalled; resources/readiness/full context
and the remaining feature/action ports still need completion.
