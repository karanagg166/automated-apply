# Runtime ownership and connection budget

Development source is not the installed runtime. The complete Rust HTTP/execution host
has not been installed. The installed native bridge forwards to the legacy API; that
does not make it an independent PostgreSQL writer. Do not infer simultaneous live
Python/Rust table writers from both implementations existing in Git.

The deployment strategy is a whole writer-family cutover. During development Rust
contracts use a disposable, fictional PostgreSQL instance. Do not split production
mutations between languages, enable a second background worker or expose a migrated
endpoint merely because its fixture passes.

| Table / state family | Current production writer | Replacement after accepted cutover |
| --- | --- | --- |
| Candidate profiles, resources, evidence, projects and private resume records | Python API / authorized resume worker | Rust profile, knowledge and document services |
| Jobs, companies, observations, discovery runs and enrichment budgets | Python API / authorized discovery worker | Rust ingestion, discovery and enrichment services |
| Packets, fields, append-only events and submission evidence | Python API / execution worker | Rust packet and guarded execution services |
| Execution preferences, commands, policy, quotas and unknown-action quarantine | Python API / execution worker | Rust guarded execution service; preserve every consumed admission |
| Notifications, preferences and delivery outboxes | Python API / Telegram worker | Rust API / owner-bound Telegram relay |
| Connected accounts, encrypted OAuth state, Gmail cursors, drafts and retention | Python account services | Rust account services; READ + CREATE DRAFT ONLY remains |
| Contact/outreach evidence, drafts and budgets | Python services | Rust services under the same owner grants; no implicit sending |
| `rust_agent_*` coordinator state | Rust fictional development harness; no production acceptance claimed | Rust coordinator only |

Current source enforces a cooperating-process fence at the exact password-independent
database/schema target. Python API, execution and Telegram service leases acquire a
shared `writer-<target>.lock`; the Rust host takes that file exclusively **before any
database connection**. Existing per-service exclusive leases remain. The discovery CLI
also joins this fence. Files are private, owned regular files opened without following
symlinks; closing/crashing releases the kernel lease without unlinking the inode.

This is a single-host boundary, not a distributed PostgreSQL ACL or a claim about old
installed binaries. All retired writers must first stop, including resume/command/browser
CLI operations and ad hoc operational scripts. Older releases do not acquire the new
family lease. Containers must share the lock directory to coordinate; separate container
filesystems or a second host are not supported cutover topologies. Do not activate Rust
until a release inventory proves every remaining writer participates or is stopped.

## Exact connection ceilings

| Process / activity | Ceiling from source |
| --- | --- |
| Rust control HTTP connection | 1 persistent |
| Rust execution coordinator connection | 1 persistent |
| Rust Telegram enabled | 1 persistent; 0 when disabled |
| Rust HTTP/background answer generation, private document or account IO | 1 transient shared permit across those operations |
| Rust public feed discovery | 0 additional; releases the existing control connection during HTTPS IO |
| Complete Rust family | **4 peak with Telegram; 3 without**; no pool or overflow |
| Each Python SQLAlchemy business pool | `DB_POOL_SIZE + DB_MAX_OVERFLOW` per process; source defaults 1 + 0 |
| Python readiness probe | At most 1 transient API probe, coalesced; no retained idle readiness connection |
| Prepared standalone discovery worker | 2 + 0, from `deploy/automation-worker.compose.yml`; opt-in, not launched here |

For a Python API + execution + Telegram profile with all three configured to 1/0,
the conservative peak is **4** (three business slots plus the readiness probe).
An additional 1/0 resume worker makes **5**. Adding the prepared discovery worker
makes **7**. These are configuration calculations, not a fresh installed-process count.
Any other process, pool overflow or operator session must be added explicitly.
The source fence prevents adding the Rust family to a cooperating Python family;
it does not reduce the existing Python family's pool allocations.

Provider/pooler capacity and PostgreSQL role limits were **not freshly sampled for this
review**. Do not substitute the server's `max_connections` for the hosted pooler's cap.
Before cutover record each actual role's limit, pooler mode/capacity and already-used
sessions, keep an operator/recovery slot, and verify the four-slot Rust peak under load.
No new production worker, role grant, schema migration or runtime installation occurred.

## Cutover gate

1. Finish endpoint/service/provider parity and the shared security contract checks.
2. Preserve private configuration, approvals, policy revisions, history, quotas and
   uncertain jobs; inventory the exact installed releases and rollback references.
3. Keep the queue STOPPED, quiesce every Python writer, and verify no in-flight unknown
   mutation is retried. Do not reset allowances or replay quarantined jobs.
4. Rehearse the reviewed schema package in combined validation. The operator package
   checks the saved STOPPED application queue and any saved legacy preparation control
   before creating the Rust schema. After the reviewed migration, run the candidate
   binary's `cutover-preflight --config /absolute/private/runtime.env` command.
   It uses one read-only database transaction to check target/readiness and STOPPED
   controls and records sanitized revisions and role session counts. Confirm pooler
   capacity, retired writer state and the family lease independently before installing
   one Rust family.
5. Validate actual account/resume/readiness, focus preservation, restart recovery and
   resource use before enabling authorized work. Roll back failed acceptance.

The local dashboard candidate uses `node frontend/run-local-rust.mjs
--frontend-config /absolute/private/frontend.env --runtime-config
/absolute/private/runtime.env --port 3000` in its launch definition. The Node
process serves the prepared standalone build directly. It keeps the dashboard's
existing owner login configuration and takes its API token, socket and optional
approval key from the same private file as the Rust host. Both dashboard API
routes use that socket. The combined runner prepares standalone static assets
at build time and checks both authenticated routes through a fictional socket.

The pending owner browser/account step, missing strict worker receipt and per-platform
live acceptance remain separate gates. Passing a process lease test does not satisfy them.

## Queue scheduling source checkpoint

The configured execution worker now runs saved-source intake, filter reconsideration and
local factual preparation on its existing connection, gated by the separate saved queue
policy. The Rust coordinator RUNNING flag does not activate an application queue or
rewrite its authority. An API/background questionnaire task shares the one transient
long-request slot with HTTP inference/document/account IO and the provider concurrency
gate. It releases the control mutex before opening that transient connection and never
holds the owner transaction during inference. No additional persistent slot is added.
Idle hints are read-only; local scheduling heartbeat writes are limited to30 seconds
when nothing changes. These are source bounds, not measured production timing/resource
results. A busy coordinator/model operation can delay its next local scheduling tick;
final latency/load acceptance must measure this. Native browser polling/profile work
continues on the separate API control connection.

After handlers and background tasks drain, final host quiescence pauses a RUNNING
application queue through its existing fences, preserving uncertain actions and quotas,
then pauses the Rust coordinator. It does not resume either control on restart. This
source is uninstalled and its new scheduling/connection/shutdown tests remain UNRUN
until the agreed final combined gate.
