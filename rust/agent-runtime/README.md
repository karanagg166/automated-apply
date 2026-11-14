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
implemented and fixture-tested. No live provider call has been performed. Rich resume/project
context, Telegram pairing, browser execution, queue admission, other provider adapters,
dashboard integration and real receipt acceptance remain to be ported. Nothing in this library grants new submissions,
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
and close connections. A database failure currently ends the host; reconnect supervision
and deployment restart behavior remain to be implemented and accepted.

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

Dashboard wiring, reconnect supervision, remaining API/action ports and real installation/
resource acceptance remain open. Never run this worker alongside the installed Python
executor against the owner's data. It currently reviews saved jobs only.
