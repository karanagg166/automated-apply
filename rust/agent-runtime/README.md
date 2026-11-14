# Durable specialist-agent coordinator

This library is under development and is not installed in the owner's runtime.
It has five roles: discovery, matching, answers, review and execution. Each role has a
fixed tool subset and a fixed next-role transition. Model proposals are strictly typed,
can reference saved job IDs and observed evidence, and cannot supply a browser URL,
recipient, policy change, shell command, credentials or approval flag.

The coordinator persists model/input/output token reservations before inference, and
stable effect IDs before tool dispatch. Reserves survive a lost model response. Expired
read-only work can be retried within its original call budgets; interrupted external
writes become `outcome_unknown` and require reconciliation. Completion describes the
agent workflow, not proof of an application receipt. Submission remains explicitly
unavailable until its guarded adapter is migrated and accepted.

`Store` borrows one PostgreSQL connection. Claims use a transaction advisory lock and
one global active-lease constraint; CAS revisions and random lease tokens fence obsolete
workers. Run state and sanitized audit events update atomically. Context is private,
limited to16KiB/observation and64KiB/run, and never copied into the event table. The new
SQL tables use RLS with no client policies; public/anon/authenticated access is revoked.
Deployment must explicitly review application-role grants and existing target identity.
No process applies this SQL automatically or connects to the owner's database.

```sh
cargo test --locked --workspace
cargo clippy --locked --workspace --all-targets -- -D warnings
# PostgreSQL17 binaries are already available on this Mac; no Docker/service changes.
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
```

The dedicated harness starts and stops its own fictional localhost PostgreSQL cluster.
It compiles before startup, uses at most8connections and16MiBshared buffers, rejects
nonfixture database URLs, and never reads the project's env files. Default workspace
tests deliberately skip these integration cases; the dedicated harness runs them all.

The worker now runs five deterministic saved-review roles over actual PostgreSQL read
tools. Its integration tests use fictional profiles/jobs in a disposable database; earlier
coordinator tests also retain scripted model proposals and simulated write adapters.
The Cohere V2 transport, explicit consent and shared monthly usage/cooldowns are
implemented and fixture-tested. No live provider call has been performed. Owner controls,
workflow dashboard, bound Telegram relay and profile/resource APIs are implemented with
fictional fixtures. Rich resume/project context, full Telegram command parity, browser
execution, queue admission, other providers and real receipt acceptance remain open.
Nothing in this library grants new submissions,
turns on recurring AUTOMATIC or starts Ollama/GPU inference.

Library references: [Tokio](https://docs.rs/tokio/latest/tokio/),
[SQLx PostgreSQL](https://docs.rs/sqlx/latest/sqlx/),
[Cargo profiles](https://doc.rust-lang.org/cargo/reference/profiles.html).

Cohere uses the existing `llm_monthly_usage` table; it never creates a separate allowance.
Its provider URL is fixed, HTTP retries/proxies/redirects are disabled, the full request
is byte bounded and responses are streamed into a128KiBlimit. Consent and monthly limits
are checked before transport; unknown responses consume their reservation. HTTP429 adds
a durable cooldown. [Official V2 contract](https://docs.cohere.com/reference/chat).

The small default per-run input budget can reject a cloud request before transmission.
Worker integration must allocate/route requests within the existing approved budgets;
this library is not a claim that default settings support a live five-LLM-call workflow.

Actual PostgreSQL-backed read tools now implement saved Naukri search/ranking, confirmed
profile context and bounded application history. Profile confirmation is bound to the
current ID/version. A ranking snapshot combines profile, jobs and replay fences in one SQL
statement; it excludes known/unknown admissions, submitted packets, retained receipts and
prior applied companies. This is ranking preview, not live posting-age/applicant/quota
admission. Exact remaining platform/history normalization and action adapters must still be
completed before production cutover.

Only backend-observed job IDs may be proposed for job-specific tools. Binding changes from
ranking revoke old IDs, and binding membership is checked again at dispatch. Read-tool
outputs are persisted through the same coordinator before any later action. Unsupported
adapters produce a migration diagnostic; they do not ask the owner to approve missing code.

The additive `sql/002_control.sql` migration starts globally STOPPED. It is explicit,
like migration 001; development only applies it to disposable fixtures. Owner commands
require a current revision. Pause/Stop fence active leases and record mode changes in a
separate sanitized audit table, atomically. Start resumes globally paused work, preserving
budgets and pending read effect IDs; it preserves manual pauses and quarantined external
actions. Per-run Stop preserves completed/failed/unknown history. Global Stop retains queued
work without admitting it. No authority, application quota or provider usage is refunded.

`worker::serve` borrows its host's connection and supports cancellation and committed-control
wakeups. It sleeps when idle/stopped, heartbeats every five seconds, and bounds reconciliation
to ten questions per scan with fair scheduling. It does not create a pool or extra worker
threads. A normal saved-job review takes nine bounded decisions and four database tools,
with zero model calls/token reservations. Independent decision limits prevent an unbounded
deterministic loop. Interrupted model reservations remain consumed.

Owner questions accept references to existing confirmed profile versions, not raw answers
or grants. Notice period, work authorization, compensation units and availability use the
existing profile schema's fact types. Already known facts reconcile automatically; changing
profile versions restarts read-only review without resetting usage. Changed identities and
uncertain external effects require reconciliation. No profile/provider save occurs here.

The standalone `automated-apply-agents` binary now hosts these controls on numeric IPv4
loopback (default port 8011), using a current-thread Tokio executor and Axum. It requires
`serve --config /absolute/private/runtime.env`; it never auto-loads an ambient env file or
applies migrations. The file must be owner-owned, regular, at most 1MiB and inaccessible
to group/other users. Values are literal: duplicate keys and dollar interpolation are
rejected. PostgreSQL environment overrides are also rejected; SQLx never reads `.pgpass`.
Secrets and DSNs are absent from its fixed errors and readiness event.

The production target preserves verified remote PostgreSQL TLS, the pinned public-schema
Supabase project and unprivileged runtime role. URL parameters, fragments, transaction
pooler port 6543 and nonpublic resolved addresses are refused. The owner API requires TLS
in production; this HTTP listener accepts HTTPS termination only with explicitly configured
loopback proxy trust and one `X-Forwarded-Proto: https`. An HTTPS request-target string
does not establish TLS. Actual production DNS/certificate/proxy acceptance is still pending.

The host obtains the same password-independent `execution-<target_identity>.lock` kernel
lease as the Python worker before opening its two persistent connections (control/execution).
It never unlinks lock files. Fixture tests prove that the actual Python `process_lock`
implementation detects the Rust-held lease, and a duplicate Rust process is refused.
SIGINT/SIGTERM cancel the worker, persist a global pause when running, clear its heartbeat
and close connections. Lost execution/control connections are replaced with bounded
1/2/4/8/16/30-second backoff. An attempted HTTP operation is never replayed automatically;
clients inspect current revisions after a failure. Every replacement rechecks the target
and schema, closes the failed connection first, and preserves leases, budgets and unknown
effects. Final shutdown reconciles pause after all HTTP handlers drain; an unconfirmed
pause produces a fixed failure code.

| Method | Owner route | Purpose |
| --- | --- | --- |
| GET | `/health` | Public bounded liveness and review scope |
| GET | `/ready` | Authenticated database target/schema readiness |
| GET / PUT | `/api/v1/rust-agent/control` | Read mode / revision-checked mode change |
| GET / POST | `/api/v1/rust-agent/runs` | Bounded list / idempotent saved-review intake |
| GET | `/api/v1/rust-agent/runs/{id}` | Sanitized state and usage summary |
| POST | `/api/v1/rust-agent/runs/{id}/control` | Revision-checked pause/resume/stop |
| GET | `/api/v1/rust-agent/runs/{id}/events` | Bounded sanitized audit history |
| GET | `/api/v1/rust-agent/questions` | Missing confirmed facts |
| POST | `/api/v1/rust-agent/runs/{id}/questions/{question}/resolve` | Reference a confirmed profile version |

Every owner route requires the configured bearer token and explicit Host/Origin trust.
Extension-client headers and duplicate credentials/origins are rejected. Requests are
limited to 64KiB and eight concurrent handlers; body reads time out after 20 seconds.
Request structs reject extra authority/answer fields. Responses omit raw tool contexts,
personal facts and secrets, and carry no-store/nosniff/no-referrer headers. Per-run controls
only cancel that run's in-flight wait; other saved-review work keeps its reservation.

Fixture mode requires both `ENVIRONMENT=testing` and `RUST_RUNTIME_FIXTURE=true`, the exact
disposable harness database URL and an explicit private `--fixture-lock-directory`. It
cannot select another database, production lock directory or network listener. The dedicated
PostgreSQL harness exercises the actual CLI, HTTP server, worker, duplicate locks and SIGTERM
against fictional data. It does not install a service or use an owner environment.

Dashboard wiring, remaining API/action ports and real installation/
resource acceptance remain open. Never run this worker alongside the installed Python
executor against the owner's data. It currently reviews saved jobs only.

Optional Telegram runs in the same Rust process, enabled only by explicit private
`RUST_TELEGRAM_ENABLED=true`, the existing bot token and verified positive owner user/chat
IDs. It takes the legacy `telegram-<target_identity>.lock` before API calls and borrows one
additional persistent connection for the existing Telegram role: three connections total
when enabled, two otherwise. No connection pool or process per agent is added. Production
uses the fixed official Bot API, with proxies/redirects/retries disabled and a streamed 1MiB
response limit. Fixtures require an explicit numeric-loopback endpoint; they cannot call
the official API. See the [official Bot API contract](https://core.telegram.org/bots/api).

The current Telegram port supports `/ping`, `/help`, `/start`, `/status`, `/jobs`, and
`/agents status|review|runs|run <UUID>|start|pause|stop`. Owner/chat IDs, private-chat type,
non-bot sender and forwarding checks precede commands. Bot and owner binding changes are
refused. Telegram cannot supply arbitrary methods, recipients, message bodies, browser
URLs or submission authority. Unsupported legacy/browser/application commands explicitly
remain unavailable; this is not complete Telegram command parity.

Migration 003 adds private binding/cooldown/outbox metadata while preserving existing
`agent_telegram_state` offsets/bot pins and `agent_telegram_deliveries`. Incoming command,
offset and bound reply commit together. Unbound historical pending replies are left alone.
Dispatch is recorded as `sending` in both outboxes before network I/O; an interrupted or
ambiguous send stays quarantined. Only a validated sent-message receipt marks delivery
sent. A verified HTTP 429 can requeue it with a durable cooldown; a 600-second provider
delay stays 600 seconds. Oversized/unrecognized delays require reconciliation and cannot
be capped down to bypass the provider. No webhook is changed or deleted.

With Telegram enabled, saved review adds one execution-role notification tool: ten bounded
decisions, four actual data reads and one bound notification intent, with zero model calls.
The tool reports `pending`, not sent; delivery confirmation is separate. The relay uses
long polling and preserves the legacy sequential poll/delivery pattern, so a notification
created during an idle poll can wait for that poll (up to 25 seconds). Its reconnects
preserve the outbox/cursor and never replay `sending` messages. On rollback, honor the
recorded cooldown before restarting an older worker that does not read this new metadata.
Actual owner pairing, live delivery, deployment/rollback and complete legacy commands still
need acceptance. This development did not read a real bot token or send a Telegram message.

## Graph, reviewer and human checkpoints

Migration `004_graph.sql` adds audit projections only. Apply reviewed SQL 001–004 in order
on an authorized target before starting this development host; the executable never performs
DDL. Existing serialized runs default to graph revision 1, zero replans and no human-review
requirement without losing usage. Request-key idempotency normalizes these new defaults.

The durable graph records planning, typed model decision, validation, tool dispatch,
observation, review, bounded replanning, owner input, owner approval, provider cooldown,
pause, reconciliation and completion. Five specialist roles share one worker and the
existing database queue. They have different instructions and typed tool permissions;
they are not five independent inference processes. At most one lease executes globally.
Replanning targets discovery/matching/answers, clears invalid downstream results, retains
spent allowances, and cannot replay a prior external effect. Default loop limit is two;
three is the hard maximum. Decision summaries and tool observations are exposed; private
model scratch thoughts are neither required nor stored.

`RUST_AGENT_REVIEW_MODEL=deterministic` is the default and uses zero inference. Optional
`cohere` calls the existing bounded Cohere adapter only after four real factual read tools.
It requires the existing explicit provider/candidate-data consents and approved monthly
budgets. The cloud projection contains source IDs, top-three ranking summaries, verified
experience and skill count; it excludes contact/resume/free-text contents. Provider cooldowns
are persisted without charging another run reservation. The reviewer can hand off, ask a
bounded fact question or request a bounded replan; it cannot invoke application/browser tools.
Fixture mode additionally requires `RUST_COHERE_FIXTURE_ENDPOINT=http://127.0.0.1:<port>/v2/chat`;
production rejects that override. No real cloud call was used for acceptance.

New authenticated routes under `/api/v1/rust-agent`:

- `GET /capabilities`: actual tool availability, specialist roles and recommended budgets.
- `GET /runs/<UUID>/plan`: concrete prepared results and current plan/checkpoint.
- `POST /runs/<UUID>/approvals/<UUID>` with `expected_revision` and exactly one decision:
  `approve`, `reject` or `request_changes`. Actor identity is server-owned.

`human_review: true` pauses execution-role work until the exact review is approved. Every
backend tool can additionally require a separate approval of its stable, undispatched effect.
Approval binds the plan revision, profile version, results, known job references, configured
limits and (for tool approval) exact pending action. It expires after one hour. Owner API
approval independently checks the current confirmed profile and CAS revision. Approval
never grants application authority, changes quotas, resets budgets or overrides fresh tool
policy checks. Reject stops the run; request changes recomputes actual source facts within
the same bounded budget. Stale decisions are rejected; uncertain effects stay quarantined.

The authenticated Next.js `/workflow` page shows interactive stages, run/worker controls,
prepared results, actual tool availability and approve/reject/request-changes controls.
Review with human approval is the dashboard default. Its dedicated `/api/workflow` proxy
requires owner session, exact origin/host and CSRF for mutations. Set server-only
`RUST_AGENT_URL=http://127.0.0.1:8011` and `JOB_AGENT_API_TOKEN` matching the host. The proxy
accepts only numeric loopback, fixed paths and bounded JSON; no redirect, proxy or write
retry is used. For HTTPS frontend ingress, explicitly set `RUST_AGENT_TRUST_LOOPBACK_PROXY=true`
on the frontend and `RUST_AGENT_TRUST_LOOPBACK_PROXY=true` in the Rust host configuration; the
frontend derives the forwarded protocol from its validated configuration, never user input.
Do not place the bearer token in a public/`NEXT_PUBLIC_` variable.

The graph currently executes saved-job review and optional bound Telegram notices.
Browser/application tool signatures are explicitly `not_migrated`; they remain unavailable
through the worker and approval UI. Full Python removal, profile/service/API ports,
production installation, live actions and whole-system CPU/GPU acceptance remain open.

## Primary profile API port

The same authenticated host additionally handles `GET`, `PUT` and `PATCH /api/v1/profile`.
It uses the existing API connection and existing candidate table, with no pool, new role or
automatic DDL. Authenticate before reading a bounded 64KiB body. DTO validation precedes
If-Match precondition checks. Create returns 201, read/update 200, with a strong quoted ETag;
PATCH requires If-Match, and changed PUT requires it. No-op PUT can omit the header; a supplied
version is checked atomically even for a no-op. Unknown/stale versions are never retried.

Normalization preserves the original partial-field, root ORM read, nested JSON and Decimal
semantics. A raw historical row that differs from canonical input still requires a version
before being rewritten. Partial preferences preserve omitted facts, and the complete merged
profile must fit its existing bound. Explicit column writes preserve active resume links and
all history/confirmation records; a real changed version makes an old confirmation stale.
Response validation and commit complete before acknowledgment; failure rolls back. GET never
rewrites facts. Timestamps retain UTC/microsecond output. Production/staging reject placeholders.
See [contract source and fixtures](schemas/README.md).

This port is uninstalled. The existing frontend/backend proxy still uses the legacy service.
Validation failures expose sanitized `detail` messages rather than copying FastAPI's full
per-input error arrays. Profile readiness/confirmation, resource/context
and remaining APIs/services still need Rust ports before removing Python or cutting over.

## Multiple model-backed agents

To opt into both planning and review, set `RUST_AGENT_REVIEW_MODEL=cohere` and
`RUST_AGENT_MODEL_ROLES=discovery,review` in the host's explicit private configuration.
Existing provider/candidate-data consents and monthly budgets are still required. With no
role setting, opt-in Cohere preserves review-only behavior; deterministic mode remains the
default. Unsupported/duplicate roles and a planner without the reviewer are rejected.
These roles share one async client, worker and existing execution connection; no model/GPU
process, pool or worker process is started per agent.

Discovery first observes the real saved-job read, then its model selects the matching
handoff or a bounded missing-fact question. Review first observes all four factual read
results, then its separately instructed model selects execution handoff, a bounded question
or a replan. Both schemas and runtime checks restrict these decisions: these model roles
cannot dispatch tools, complete early, grant authority or add application permissions.
Deterministic matching/answer/tool execution preserves independently verified facts.

New owner-API runs pin provider, exact model identifier and model roles. The policy is part
of request-key idempotency and approval binding. Changing runtime configuration cannot add
inference to a pinned deterministic run or change an existing run's roles/model. Missing or
incompatible model configuration manually pauses the run without spending; restore the
configuration and explicitly resume, or stop it. Legacy unpinned records retain their
bounded review-only behavior and never gain the new planner. New Telegram-created saved
reviews are explicitly deterministic; they do not silently acquire paid inference.

Recommended dual-agent limits permit one replan, four model calls and at most 15,712 reserved
input/output tokens (3,800 input bytes/tokens plus 128 output per call), within the existing
16,000 cap. Monthly reservations remain shared with the legacy ledger; cooldown waits do
not reserve another call. Explicit owner limits are never expanded automatically. When
limits are omitted from an owner API intake, configured inference gets its bounded default
budgets with the legacy read-review human flag off; the dashboard supplies explicit limits
with human approval on. Null or forged policy/limit fields are rejected. Capabilities and
the dashboard show available roles and the selected run's pinned policy.

Acceptance uses a localhost fake model through the actual Rust CLI: discovery → review →
recheck → review, three requests, seven SQL reads, 11,784 retained reserved tokens, durable
cooldowns and human approval before completion. Both prompts and shared monthly counts are
checked; no real cloud inference is claimed. Browser/application adapters, full Python
removal and installed/live/resource acceptance remain pending.

`POST /api/v1/jobs/<UUID>/match` now computes relevance from the saved job and current saved
profile using the existing pure Rust base scorer. Caller-supplied profile fields are ignored,
as in the legacy saved-profile route. Results retain scores, skill labels, explanation and
unknown-experience behavior. This owner-only endpoint neither persists candidate-derived
job scores nor creates agent/model/application work. Relevance is not application admission.
Unknown jobs are reported before missing profiles; the normal owner/auth/body boundary applies.

`POST /api/v1/local-agent/profile-confirmation` records explicit owner review of an exact
saved profile version. Its strict body requires `expected_version` and `owner_confirmed`;
transport rejects delegated extension clients. The profile row is locked before comparing
versions. Confirmation and the existing `apply_filter_recheck` intent commit atomically,
then the worker receives a wake hint. Reconfirming a current version preserves recheck IDs,
cursors and progress. No facts, application counters, filters, automation modes or resume
associations change. This confirms a version; full readiness, identity/PDF and submission
checks remain separate requirements. No live profile was confirmed during development.

Saved resource ports now include `GET/POST /api/v1/candidate/resources`,
`GET/POST /api/v1/candidate/evidence` and `PATCH /api/v1/candidate/evidence/<UUID>`.
They retain explicit confirmation, profile-scoped IDs, duplicate/primary conflicts and
standard GitHub/LinkedIn/portfolio links stored only on the profile with an expected version.
Evidence corrections require fresh confirmation unless the owner explicitly confirms the
correction. Partial project replacement fills defaults without inventing missing facts.
Writes validate returned records and commit before acknowledgment, without automatic retry.

List pagination accepts one `offset` (0..100000) and one `limit` (1..100); duplicate/unknown
query parameters are rejected. Resolved links use a separate bounded per-type inventory,
including primaries outside the current list page. Unconfirmed or ambiguous saved resources
and cleared profile links suppress environment defaults. The existing optional
`CANDIDATE_RESUME_DRIVE_URL`, `CANDIDATE_GITHUB_URL`, `CANDIDATE_ORIGINAL_LINKEDIN_URL`,
`CANDIDATE_PORTFOLIO_URL`, `CANDIDATE_LEETCODE_URL`, `CANDIDATE_CODEFORCES_URL`,
`CANDIDATE_GFG_URL` and `CANDIDATE_HACKERRANK_URL` may be supplied through the private literal
configuration. Defaults must pass public HTTPS syntax checks and remain unconfirmed.
These checks perform no URL, DNS or resume fetch. Private PDF storage/download and other
answer services still need migration.

Additional standalone owner inspections are `GET /api/v1/rust-agent/resume-selection`
(optional `selected_id=<UUID>`) and `GET /api/v1/rust-agent/profile-readiness`.
They use repeatable-read, read-only profile/resource snapshots. A resource inventory above
10,000 fails closed instead of selecting from a truncated list. A private resume reference
is selected only with an exact canonical UUID and `source_type=private_upload`; creating
private-upload authority is unavailable through the public resource-write contract.
The exact legacy resource hash uses raw saved references and Python Unicode/datetime
spelling. A selected reference does not mean a file was uploaded or independently verified.
Complete profiles still require owner confirmation and do not assert identity acceptance.

`POST /api/v1/candidate/resources/resolve` accepts only a bounded `question` and returns the
existing deterministic answer contract. It uses a read-only profile/resource snapshot and
Unicode 14 word/case normalization. Confirmed links include provenance; defaults require
review. Compound/narrative/additional-fact questions request input rather than returning an
unrelated link. File questions return at most100 saved resume references, accessibility
`not_checked` and `file_upload_required`; they never fetch or upload bytes. Questions cannot
set confirmation, model/provider policy, browser destinations or application permission.
