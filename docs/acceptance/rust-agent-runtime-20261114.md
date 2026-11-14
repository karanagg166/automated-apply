# Rust migration: native transport and coordinator milestones, 2026-11-14

Latest: [Milestone 12 — saved-profile job relevance](#milestone-12-saved-profile-job-relevance-endpoint).

Overall request: **IN PROGRESS**. Full Python replacement and multi-agent AI delivery
are not complete. Installed application services/extension/native wrapper were not changed.

Implementation branch: `feat/rust-agent-runtime`.
Implementation SHA: [`fcb2722`](https://github.com/karanagg166/automated-apply/commit/fcb2722).
Migration PR: [#50](https://github.com/karanagg166/automated-apply/pull/50), draft and unmerged.
Base: `chore/uv-python-tooling`, PR [#49](https://github.com/karanagg166/automated-apply/pull/49).
This stacks on existing Naukri implementation rather than reverting to older `main`.
[Execution plan](../plans/2026-11-14-rust-agent-migration.md).

## Changes

Rust native-host executable implements Chrome length-prefixed messaging, bounded unbuffered
pipe reads, private owner-only configuration, stable extension-origin verification, numeric
IPv4 loopback-only authenticated HTTP, fixed sanitized errors, response size/schema/request
checks, and retries only after explicit backend database rollback. Redirects/proxies/network
schema resolution are disabled. A generated public JSON schema catches malformed nested
requests. Existing backend cross-field/account/identity/resume/policy/quota checks remain
mandatory and are not replaced by this milestone.

Cargo dependencies are locked, compiler concurrency is two, release uses thin LTO. Rust CI
is manual-only and was **not dispatched**. pnpm and uv conventions are preserved. At this first milestone, the
agent-runtime crate was a declared workspace scaffold only; milestone2 below implements its core.

## Actual Mac resource evidence, fictional traffic

Apple Silicon Mac (`Darwin`, `arm64`), installed Rust1.99.1/Cargo1.99.1, Python3.11.18.
Isolated local Python environment installed with uv; 90 runtime packages compatible.
Release build completed in 2m20s under concurrent unrelated owner workloads; this is a
build observation, not a stable build-performance comparison.

20 measured successful health exchanges **per runtime**, plus one successful warmup per
runtime (42 HTTP fixture requests). Alternating Python/Rust order, same fictional localhost
HTTP server, explicit private fictional env, same typed request. No live database, browser,
Telegram, candidate files, AI providers or application endpoint contacted.

| Median process startup + one fixture exchange | Python | Rust |
| --- | ---: | ---: |
| Wall time | 610.979ms | 6.945ms |
| Process CPU time | 599.771ms | 4.775ms |
| Peak resident memory | 82,456KiB | 7,248KiB |

[Sanitized individual samples](rust-native-benchmark-20261114.json).
Measured wall time ~88x faster; CPU ~99.2% lower and peak RSS ~91.2% lower **for this
process workload only**. This does not establish whole-project idle/loaded savings.
GPU usage was not measured. The bridge does not invoke GPU inference.

## Verification and acceptance matrix

| Check | Result | Exact evidence |
| --- | --- | --- |
| Rust transport regressions | PASS | 14 tests; 0failed/0ignored; final run0.74s |
| Typed public-contract examples vs Python | PASS | 25fictional cases; not exhaustive business/cross-field parity |
| Actual Mac executable resource comparison | PASS | 20successful measured requests/runtime +2warmups |
| Public-schema drift check | PASS | `native_schema_current` |
| Cargo format / Clippy warnings denied / diff check | PASS | Local checks; 0Clippy warnings |
| Python dependency consistency | PASS | 90packages checked via `uv pip check` |
| Installed native host / extension focus acceptance | NOT TESTED | No deployment/browser/window changes |
| Real submission/account/history acceptance | NOT TESTED | No new applications/receipts or provider calls |
| Full Python runtime replacement | NOT TESTED | 355legacy application modules remain |
| Multi-agent coordinator/tools | NOT TESTED | Workspace scaffold only |
| Whole-project CPU/GPU/idle acceptance | NOT TESTED | Bridge-only benchmark; no GPU measurement |
| Hosted Actions / merge | NOT TESTED | Deliberately not dispatched/merged |

Sanitized failure codes exercised include `native_message_size`, `native_invalid_message`,
`native_private_configuration_required`, `native_origin_denied`, `native_capability_denied`,
`native_read_timeout`, `native_truncated_message`, `native_response_size`,
`native_request_id_mismatch`, `backend_invalid_response`, `backend_not_ready`,
`backend_authentication_failed`, `backend_transaction_rolled_back`, `backend_offline`.
An earlier intermediate test failed because the IPv6 endpoint restriction was edited
while a previous build was running; final rebuilt artifact rejects it and passes14/14.
An initial Clippy failure identified a complex fixture tuple; named alias resolves it.
No remaining failures in this milestone's final local checks.

## Reproduction

```sh
cargo test --locked --workspace
cargo fmt --all --check
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo build --locked --release --workspace
uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python -r backend/requirements-runtime.txt
uv pip check --python .venv/bin/python
uv run --no-project --python .venv/bin/python python -m rust.scripts.export_native_schema --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.native_contract_parity
uv run --no-project --python .venv/bin/python python -m rust.scripts.benchmark_native --iterations 20
```

Next: implement bounded specialist-agent coordination and durable PostgreSQL handoffs,
port provider/tool/worker/API services, prove contract parity and restart recovery, then
prepare immutable installation with existing STOP/rollback/focus/account/policy checks.
No recurring AUTOMATIC authorization, quota reset or uncertain-application replay is inferred.


## Milestone2: durable specialist-agent core

Implementation: [`52fdfa6`](https://github.com/karanagg166/automated-apply/commit/52fdfa6),
branch `feat/rust-agent-runtime`, [PR#50](https://github.com/karanagg166/automated-apply/pull/50).

Discovery, matching, answers, review and execution have distinct prompts and tool scopes.
A strictly typed proposal cannot contain a URL, recipient, approval grant, policy update
or shell command. Only tool-observed evidence IDs can be cited or passed between roles.
Ordered handoffs prevent skipping review. Backend-derived tool authority is a separate
non-deserializable type. Submission returns `submission_adapter_not_migrated` until the
existing identity/resume/account/quota/admission/receipt safeguards are ported.

A single borrowed PostgreSQL connection persists bounded private context, input/output
budget reservations, stable external-effect IDs and sanitized audit events. Lease tokens,
CAS revisions, an advisory lock and a global one-active-lease constraint prevent duplicate
work and cap active coordination across processes. Every provider/tool dispatch follows a
successful durable save. Expired model work retains its consumed allowance. Interrupted
external writes become `outcome_unknown`; no refund or replay is inferred. Read-only retries
consume the original call budget. Maximum external wait20s, lease90s, default model/tool
call caps16each and token reservation cap4000. No local model or GPU process starts.

The explicit SQL migration enables RLS and revokes public/Supabase-client table access.
It was applied **only to a newly created fictional PostgreSQL17 cluster on this Mac**.
No live DB connection, schema/ACL/policy/queue change or installed update was performed.
Application-role grants and target identity still need production deployment review.
Rust minimum version is1.94 because SQLx0.9 requires it; the Mac has1.99.1. Cargo packages
are private (`publish=false`); no new repository licensing grant is introduced.

| Check | Status | Exact evidence |
| --- | --- | --- |
| Agent state/authority/budget/context regressions | PASS | 15tests, 0failed, 0ignored |
| Native transport regressions | PASS | 14tests, 0failed, 0ignored, final run0.66s |
| Dedicated native PostgreSQL17 fixtures | PASS | 9tests, 0failed, 0ignored, 0.16s |
| Five-role durable workflow | PASS | Scripted model, 10decisions/5simulated tools; no real provider/browser |
| Concurrent workers/global capacity/expired lease fence | PASS | Actual PostgreSQL fixture; two independent connections |
| Lost external response/restart/no replay | PASS | Actual DB persistence + connection close/reopen; simulated external intent |
| Atomic audit/reservation failure | PASS | Injected audit constraint rejects write; 0model/tool dispatches |
| Client role/RLS privacy | PASS | Fixture client with SELECT grant sees0rows; owner sees1 |
| Format/Clippy warnings denied/locked release build | PASS | Local; release build1m20s, not a comparative benchmark |
| Python command-schema drift | PASS | `native_schema_current` after core integration |
| Real LLM and monthly provider budgets | NOT TESTED | Provider adapter still pending; no cloud calls/spend |
| Live Telegram/browser/application adapters | NOT TESTED | Traits and simulated adapters only |
| Agent worker/dashboard/STOP/owner-question integration | NOT TESTED | Core library only; no new daemon/API installed |
| Whole-project CPU/GPU savings / full Python removal | NOT TESTED | Legacy backend remains; original bridge benchmark is scoped above |

Totals: **38distinct Rust tests passed** across the standard suite (29passed, 9deliberately
ignored PostgreSQL cases) and the dedicated PostgreSQL harness (all9passed). The25earlier
public-contract parity cases are separate and are not included in38. Fixtures are not
production acceptance. The dedicated cluster used a random loopback port,16MiBshared
buffers and maximum8connections; it was shut down after tests. No existing services or
owner browser windows were changed.

An intermediate native fixture run failed2of14cases because accepted sockets inherited
nonblocking mode on macOS. Explicit blocking mode on each fixture connection fixes the
harness; the final14pass. Initial integration compilation caught temporary borrowed store
values; named store bindings fix it. Clippy caught a single-pattern match; final check
passes with warnings denied. No remaining failures in the final scoped validation.

Additional reproduction:

```sh
# Uses only a disposable fictional native PostgreSQL17 cluster.
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
# Override PostgreSQL tools location explicitly on a different development machine:
RUST_TEST_POSTGRES_BIN=/path/to/postgresql17/bin uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
```

Next: port provider consent/shared monthly usage/cooldowns and actual verified tool
adapters, then expose coordinator lifecycle/owner questions through the existing dashboard
and paired Telegram interface. Complete remaining Python API/worker/service ports and
actual installed/receipt/resource acceptance before calling either owner objective done.


## Milestone3: Rust Cohere transport and shared provider budgets

Implementation: [`a7610ec`](https://github.com/karanagg166/automated-apply/commit/a7610ec),
branch `feat/rust-agent-runtime`, [PR#50](https://github.com/karanagg166/automated-apply/pull/50).
[Official Cohere V2 contract](https://docs.cohere.com/reference/chat) checked during this work.

The coordinator can now use a Rust Cohere model adapter. It requires enabled/evaluation-key,
owner-text and candidate-data consent; reads only explicitly supplied backend configuration;
pins the official URL; sends bounded structured JSON; disables HTTP retries, redirects and
proxies; validates completion/message/usage/typed decisions; and never starts a local model.
Credentials are neither prompt fields nor debug output. The native host now also explicitly
disables the HTTP library's internal retries; its existing rollback-only retry loop remains.

Provider reservations use the **existing** `llm_monthly_usage` table and conservative token
allowances, not a fresh migration ledger. Existing requests/cooldowns survive; concurrent
reservations cannot bypass caps; cooldowns remain effective across month boundaries;
unknown results retain consumed requests; reported usage is recorded. The same borrowed
connection handles accounting, with no new live pool. The Rust SQL migration does not
create or reset the existing provider table. Tests create a fictional copy only inside the
disposable cluster. No actual private configuration/provider key was loaded or cloud request made.

| Check | Result | Exact evidence |
| --- | --- | --- |
| Cohere consent/schema/HTTP tests | PASS | 4tests; actual fictional local HTTP includes6response/status cases |
| Agent state tests | PASS | 15tests, 0failed |
| Native regressions | PASS | 14tests, 0failed, 0.70s |
| Native PostgreSQL17 fixtures | PASS | 13tests, 0failed/0ignored, 0.22s |
| Shared old-count/cooldown/concurrency/restart accounting | PASS | 4new actual PostgreSQL fixture tests |
| Python public-contract parity | PASS | 25cases against rebuilt release |
| Format/Clippy/schema drift/diff/locked release build | PASS | Build37.11s; no hosted execution |
| Live Cohere consent/key/account/billing acceptance | NOT TESTED | 0cloud calls/spend; no real credentials read |
| Default run limits for a live five-LLM-call workflow | NOT TESTED | Conservative input bound can reject before transport; integration/routing still required |
| Other providers, actual browser/Telegram tools and full Python replacement | NOT TESTED | Pending, production unchanged |

Current totals: **46distinct Rust tests pass** (33standard +13dedicated PostgreSQL).
The standard suite deliberately ignores those13DB tests; the dedicated harness runs all13.
The25parity cases remain separate. No unresolved failures in these final local checks.

TLS support added for cloud transport can affect feature unification in a workspace build,
so the Mac bridge comparison was repeated on this rebuilt release with20measured successful
requests/runtime +2warmups. Median Python/Rust: wall506.275/6.277ms, CPU498.521/4.293ms,
peak RSS82,432/7,616KiB. This is ~81xfaster wall time and ~90.8%lower RSS for the
startup-plus-local-fixture workload. [New sanitized samples](rust-native-cloud-build-benchmark-20261114.json).
The original milestone1 samples are retained. Neither run establishes whole-project/GPU
savings or production readiness. GPU remains unmeasured.

Remaining work: integrate efficient deterministic routing/context selection with the
specialists and approved provider budgets; port actual verified browser/Telegram/application
adapters and remaining providers; implement worker/dashboard/owner-question/STOP lifecycle;
complete all Python API/service ports; then perform actual installed acceptance and resource
validation. No submission allowance, quarantined-job replay, recurring AUTOMATIC or merge
is enabled by this milestone.

## Milestone 4: factual matching and PostgreSQL-backed agent tools

Implementation: [`6c6f43f`](https://github.com/karanagg166/automated-apply/commit/6c6f43f)
plus the confirmation-type correction
[`99b19fc`](https://github.com/karanagg166/automated-apply/commit/99b19fc), on
`feat/rust-agent-runtime`, [PR #50](https://github.com/karanagg166/automated-apply/pull/50).

The new Rust domain library ports both existing matching layers, including ordered skill
aliases, role spelling, verified experience, location/remote preferences, employment,
company exclusions, startup/stage preferences, salary comparison, unknown fields and
explanations. Frozen public HTML5/Unicode reference data preserve Python 3.11 decoding
and case behavior. Their reference version and scoped notices are retained under
`rust/domain/data/`. No candidate data is in those tables. Rust uses no Python at runtime.

Actual SQL-backed agent tools now read confirmed profile context, saved Naukri ranking
and bounded application history. Confirmation is bound to the current profile ID/version
and a nonempty string timestamp; malformed false/zero/collection confirmations are rejected.
Name, email, phone and current compensation are omitted from the returned matching context.
The ranking snapshot combines profile, saved jobs and history fences in one SQL statement.
It scans at most 100 saved Naukri jobs and returns at most 10. Retained receipts fence replay
by existence even when their contents need review. Unknown/submitting packets, admitted
queue work, duplicate requisitions and previously applied companies are excluded.

Only backend-observed job IDs can enter a job-specific proposal. A new ranking can revoke
old bindings, and membership is checked again at dispatch. Bindings and tool outputs are
persisted through the coordinator before later work. The real SQL tools are exercised
through the coordinator with scripted decisions; application preparation stops with
`tool_adapter_not_migrated`, without writing a packet or requesting owner approval for
missing implementation. This is a tested integration boundary, not completed application
or live five-agent acceptance.

| Check | Status | Exact evidence |
| --- | --- | --- |
| Matching/domain regressions | PASS | 8 tests, 0 failed |
| Agent state, authority and observed-job binding | PASS | 18 tests, 0 failed |
| Provider transport/consent regressions | PASS | 4 tests, 0 failed |
| Native transport regressions | PASS | 14 tests, 0 failed; latest standard run 0.69s |
| Dedicated native PostgreSQL 17 fixtures | PASS | 20 tests, 0 failed/ignored; final run 0.47s |
| Python/Rust scoring compatibility corpus | PASS | 1,300 fictional cases; both layers, complete lists/factors/unknowns/explanations |
| Public text-table drift / Rust format / Clippy / Python Ruff / diff | PASS | Checked locally; no hosted execution |
| Locked workspace release build | PASS | Local build; final confirmation correction build 3.71s |
| Actual owner database/schema/ACL acceptance | NOT TESTED | Only new disposable fictional PostgreSQL clusters used |
| Live posting age/applicant/quota/application admission | NOT TESTED | Ranking preview only; existing live policy unchanged |
| Rich project/resume context and all-platform canonical history | NOT TESTED | Remaining ports/review required before action adapters |
| Worker/dashboard lifecycle, browser, Telegram and application actions | NOT TESTED | Uninstalled; full service ports still pending |
| Whole-project CPU/GPU and real receipt acceptance | NOT TESTED | Component measurements only; no new live submission |

Current total: **64 distinct Rust tests passed** (44 standard + 20 dedicated PostgreSQL).
The standard run deliberately ignores those 20 database cases; the dedicated harness runs
all 20. The 1,300 matching cases and earlier 25 native-contract examples are separate.
No production connection, real AI request, mailbox read, profile save, Chrome action,
application, service restart, installation, hosted Action, cleanup or merge was performed.

The first differential run found 18 mismatches in retained equivalent Unicode skill labels;
normalizing source lists like the existing profile schema fixes them. Compilation/Clippy
also caught an iterator bound, late initialization and an unnecessary struct update; the
final checks pass. No unresolved failures in these scoped checks.

### Actual Mac warm computation measurement

Five measured samples per runtime, each calculating both matching layers and output
projections for the same 1,300 prevalidated fictional cases. Both runtimes warm their
regex/data caches first. Process startup, input normalization/validation and JSON input
parsing are outside this measurement. No database, AI or browser is involved.

| Median per 1,300-case batch | Python | Rust |
| --- | ---: | ---: |
| Wall time | 61.627ms | 12.729ms |
| Process CPU time | 61.622ms | 12.726ms |

This is about 4.8x faster computation and 79.3% lower CPU time for this warm workload.
[Sanitized individual samples](rust-matching-benchmark-20261114.json).
GPU was not measured; no inference was invoked.

The separate one-shot parity driver observed 191.495ms Python versus 470.777ms Rust, but
uses different boundaries: Python includes profile validation while imports are already
loaded; Rust includes process startup, JSON parsing/output and cold regex/data caches.
Those figures are not an equivalent-boundary speedup comparison. The warm result does
not erase cold costs or establish deployed service/whole-Mac resource acceptance.

Additional reproduction:

```sh
cargo test --locked --workspace
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
cargo build --locked --release -p automated-apply-domain --example match_contract
uv run --no-project --python .venv/bin/python python -m rust.scripts.matching_parity
uv run --no-project --python .venv/bin/python python -m rust.scripts.export_html_contract --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.benchmark_matching
uv tool run --from ruff ruff check --isolated --select E9,F,I rust/scripts/export_html_contract.py rust/scripts/matching_parity.py rust/scripts/benchmark_matching.py
```

Next: finish efficient specialist routing and the durable worker/owner-control lifecycle;
port rich verified context, preparation, browser/Telegram/application execution and remaining
API/provider/services; validate real installation and resources under existing STOP,
focus, account/resume/history/quota/rollback safeguards. Both owner objectives remain open.

## Milestone 5: deterministic saved-review worker and durable owner controls

Implementation: [`020a379121c3f7d2c68d96fe6acaa96f0a01d46d`](https://github.com/karanagg166/automated-apply/commit/020a379121c3f7d2c68d96fe6acaa96f0a01d46d),
branch `feat/rust-agent-runtime`, [draft PR #50](https://github.com/karanagg166/automated-apply/pull/50),
stacked on `chore/uv-python-tooling`. This milestone is a tested library/worker integration;
the authenticated HTTP host and dashboard wiring are the next boundary. It is not an
installed service, completed Python migration, or real application acceptance.

Five specialist roles now run a deterministic saved-job review through actual PostgreSQL
knowledge tools. The fixture completes in nine bounded decisions and four read tools, with
zero model calls, token reservations or provider requests. Separate decision limits bound
routing even when no inference is used. Existing records retain their previous model
consumption when the new decision counter is absent. No local model/GPU process starts.
This is factual review of saved jobs; workflow completion does not represent an application
submission or receipt. The current worker does not select a cloud inference provider.

The additive 002 migration defaults to STOPPED. Global and per-run controls require current
revisions; committed Pause/Stop fence the active worker immediately. Resume retains budgets
and read effect IDs, respects manual pauses, and never restarts quarantined external work.
A global Stop retains queued jobs without admitting them. Per-run Stop preserves terminal
completion/failure/unknown history. Control mode changes and a sanitized audit row commit
atomically; audit failure rolls the complete control transaction back. RLS also protects
control/audit tables from public clients even if SELECT is mistakenly granted.

Questions reference independently confirmed profile facts. They accept no raw answer or
new grant. A profile version must match persisted confirmation; notice period, authorization,
availability and compensation types/units are checked. Existing confirmed facts reconcile
without another owner action. Changed identities or uncertain external effects cannot be
reset through question resolution. Read-only review restarts with retained usage. Reconciliation
checks ten questions per scan, fairly rotating past missing older facts rather than starving
later known facts. No profile or provider save occurs.

`worker::serve` borrows its host's existing connection, sleeps when idle/stopped, heartbeats
every five seconds, and supports cancellation and committed-control wakeups. It creates no
pool or worker thread. A blocked-model test uses a separate owner connection and requires
the Stop transaction to finish within one second, without waiting for the 20-second model
timeout. It passes; the in-flight reservation remains consumed and stale saves are rejected.
This measures a test bound, not production stop latency.

| Check | Status | Exact evidence |
| --- | --- | --- |
| Provider, fact validation and terminal-history units | PASS | 7 tests: 4 retained provider + 2 fact schema + 1 terminal Stop |
| Coordinator, binding and budget regressions | PASS | 20 tests, including 2 new deterministic/legacy-budget checks |
| Matching/domain and native transport regressions | PASS | 8 domain + 14 native tests; final native run 0.77s |
| Dedicated native PostgreSQL 17 fixtures | PASS | 35 tests, 0 failed/ignored; final run 0.99s, fictional data only |
| Actual worker over PostgreSQL read tools | PASS | Included above: nine decisions, four reads, zero inference/token reservations/provider rows |
| Pause/Stop/resume/revision/audit failure and quarantine | PASS | Included above; no budgets refunded, stale workers fenced, external effects not replayed |
| Owner facts/version/identity and fair question scheduling | PASS | Included above; known facts reconcile, older missing facts do not starve the next batch |
| Rust format / Clippy with warnings denied / diff | PASS | Local checks; no hosted execution |
| Locked optimized workspace build | PASS | Local final incremental build 4.85s; earlier dependency rebuild 45.28s |
| Authenticated HTTP host / private config / compatible legacy process lock | NOT TESTED | Not implemented in this milestone; required before owner-data execution |
| Dashboard integration / reconnect supervision / immutable service installation | NOT TESTED | Host integration and actual Mac acceptance remain pending |
| Owner PostgreSQL migrations/ACLs and current account/policy integrity | NOT TESTED | No owner database connection or mutation |
| Browser / Telegram / application action adapters and real receipt | NOT TESTED | Existing installed services unchanged; migration ports remain pending |
| Worker/full-project idle CPU, RSS, GPU and production Stop latency | NOT TESTED | No new equivalent-boundary resource benchmark or installed measurement |

Current total: **84 distinct Rust tests passed**: 49 standard tests plus 35 dedicated
PostgreSQL tests. The standard command deliberately ignores those 35; the fixture harness
runs every one. This adds 20 tests to the previous total of 64. The earlier 1,300 matching
comparisons and 25 native contract examples are separate historical checks, not rerun here.
Their component benchmark results remain attributable to the implementations documented
above; they do not establish worker/full-project savings.

Sanitized development failures: the initial stricter fact-key test rejected the legacy
`notice_period` key with `unsupported_owner_question`; an explicit alias now preserves it.
Compilation caught a test comparison requiring private `ProfilePin` debug output and a
dynamic test SQL string (`E0277`); tests now use safe comparisons and literal queries.
Clippy caught nested conditions; final checks pass. No unresolved failure in this scope.

Reproduction from this branch, using only a disposable fictional cluster:

```sh
cargo test --locked --workspace
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all --check
cargo build --locked --release --workspace
git diff --check
```

No owner environment/provider key, production database, cloud inference, Chrome action,
Telegram message, Gmail read/draft/send, real profile save, application, installed-file
change, service restart, hosted Action, cleanup or merge occurred. Remaining work: standalone
private-config host and legacy lock, authenticated HTTP/dashboard controls and supervised
connection recovery; actual browser/Telegram/application adapters and rich verified context;
remaining API/service/provider ports and Python removal; then immutable installation,
rollback/focus/account/quota/history/receipt and measured full-project Mac acceptance.
Both requested outcomes remain open.

## Milestone 6: standalone Rust service and authenticated owner API

Implementation: [`96ad7118ac8c7026fa8ad8bb7af594bfc793ab15`](https://github.com/karanagg166/automated-apply/commit/96ad7118ac8c7026fa8ad8bb7af594bfc793ab15),
branch `feat/rust-agent-runtime`, [draft PR #50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling`. The standalone host is implemented; it is not installed.
Full Python removal and the requested real browser/Telegram/application agents remain open.

The `automated-apply-agents serve --config <absolute-private-file>` binary runs the saved-job
review worker and Axum owner API on a current-thread Tokio executor, with two persistent
SQLx connections for owner control and execution. It creates no pool/overflow and no process
per specialist. Startup checks the target database/schema/role and additive runtime tables;
it performs no DDL. Its printed readiness event contains the local address and review scope,
not secrets or profile facts. The existing dashboard is not wired to these new routes yet.

Private configuration is bounded to 1MiB, regular, owner-owned and inaccessible to group/other.
Symlinks, duplicate keys, dollar interpolation and ambient PostgreSQL overrides are refused.
Source inspection showed that SQLx's default URL parser inherits PG settings and can read
`.pgpass`; the host instead constructs explicit options with `new_without_pgpass` and fixed
host/user/database/port/password settings. Passwords are percent-decoded as URL data. Remote
production mode requires TLS verification, rejects port 6543, parameters/fragments and
nonpublic DNS results, and preserves the public-schema Supabase project/runtime-role pin.
Actual remote DNS, TLS certificates and live target ACLs have not been tested.

Every owner route requires a constant-time bearer-token check, loopback peer and explicit
Host/Origin trust. Duplicate credentials/origins and extension-client headers are denied.
Production TLS is mandatory: this HTTP host only trusts an explicitly configured loopback
TLS proxy with one HTTPS forwarding header; a forged HTTPS request-target string is denied.
Payloads are limited to 64KiB, eight concurrent handlers and a 20-second body timeout.
Typed intake/control/resolution bodies reject extra authority or raw-answer fields. Responses
include no-store/nosniff/no-referrer headers and omit raw tool context, personal facts and
configuration. Bounded run/event/question routes expose existing library lifecycle controls.

Before connecting, the host takes the exact legacy password-independent
`execution-<target_identity>.lock` kernel lease and retains the inode through shutdown.
The actual existing Python `process_lock` implementation, invoked through uv against the
fictional fixture target, detects the Rust-held lease and exits with fixture code 75.
A second Rust process exits with `execution_worker_already_running` before opening its
connections. PostgreSQL activity confirms exactly two host connections. A separate startup
with ambient `PGHOST` is refused with `ambient_postgresql_options_forbidden`.

SIGINT/SIGTERM cancel work, persist a global pause when running and clear the heartbeat.
Per-run notifications only interrupt the affected run; unrelated work retains its in-flight
reservation. Committed database state still fences every dispatch independently of wakeups.
The current host exits on database failure; reconnect supervision and deployment restart
acceptance remain to be implemented. No automatic schema repair, reset or replay is inferred.

| Check | Status | Exact evidence |
| --- | --- | --- |
| Agent/provider/fact/history/auth/cancellation unit tests | PASS | 12 tests, including 3 new API-boundary and 2 cancellation cases |
| Coordinator/binding/budget and private host/lock tests | PASS | 20 coordinator + 8 new host tests |
| Domain matching and native transport regressions | PASS | 8 domain + 14 native tests; latest native suite 1.53s |
| Dedicated native PostgreSQL fixtures | PASS | 38 tests, 0 failed/ignored; final run 2.16s |
| Real localhost owner HTTP server | PASS | Included above: authentication, duplicate token, origin/client denial, readiness, payload bound, CAS, audit and confirmed-fact resolution |
| Actual CLI process and worker on this Mac | PASS | Included above: private fixture config, STOPPED intake, authenticated Start, four database reads, zero model calls, duplicate refusal and SIGTERM pause/offline heartbeat |
| Actual Python/Rust kernel-lock coexistence | PASS | Existing Python implementation rejects the Rust-held fixture inode; two host DB connections retained |
| Source format / Clippy with warnings denied / diff | PASS | Local checks, no hosted execution |
| Locked optimized workspace build | PASS | Local release build completed in 1m35s; tests used the debug CLI executable |
| Production target DNS/TLS/ACL and actual TLS-proxy ingress | NOT TESTED | Production configuration tests parse fictional values without connecting |
| Supervised reconnect / dashboard integration / full legacy REST parity | NOT TESTED | Remaining implementation/integration boundary |
| Full Python removal / real browser / Telegram / application adapters | NOT TESTED | Existing runtime services remain unchanged |
| Installed Mac CPU/RSS/GPU, focus, rollback and actual application receipt | NOT TESTED | No live cutover, new submission or full-project resource measurement |

Current total: **100 distinct Rust tests passed**: 62 standard plus 38 dedicated PostgreSQL.
The standard run deliberately ignores those 38; the dedicated harness executes all of them.
This milestone adds 16 tests to the previous total of 84. Earlier separate 1,300 matching
comparisons and 25 native contract examples are retained historical evidence, not rerun.
Previous component timing/RSS comparisons remain tied to their earlier source SHAs; the
new host has no equivalent-boundary Python/full-project resource comparison yet.

Actual Mac evidence here means native kernel locks, HTTP sockets, PostgreSQL and process
signals against fictional data. It does not mean live portal, owner database or installed
service acceptance. No owner environment, private provider key, real AI call, Chrome action,
Telegram message, Gmail read/draft/send, profile save, application, installed-file change,
service restart, hosted Action, cleanup or merge was performed.

Sanitized failure history: initial lock/CLI fixtures were refused with
`private_worker_lock_required` because the temporary directory did not satisfy the required
0700 mode; the fixtures now explicitly create a private lock directory. The CLI initially
reported EOF before readiness as a consequence. An unused HTTP body import was removed.
All final scoped checks pass; no unresolved scoped test failure remains.

Reproduction (native PostgreSQL 17, fictional fixture only):

```sh
cargo test --locked --workspace
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all --check
cargo build --locked --release --workspace
git diff --check
```

The legacy-lock compatibility case uses uv with this worktree's existing development venv;
the Rust executable itself invokes no Python. Next: reconnect supervision and dashboard
controls, rich verified resume/project context, guarded browser/Telegram/application tools,
remaining API/provider/services and Python removal, followed by immutable installation,
rollback/focus/account/history/quota/receipt and measured whole-project Mac acceptance.
Both owner objectives remain active and incomplete.

## Milestone 7: supervised recovery and owner-bound Telegram agent tools

Implementation: [`90403e7ae9515f26dd676fc7af04a8ef6c1e0b19`](https://github.com/karanagg166/automated-apply/commit/90403e7ae9515f26dd676fc7af04a8ef6c1e0b19),
branch `feat/rust-agent-runtime`, [draft PR #50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling`. Full Python removal, browser/application execution, complete
legacy Telegram commands, installed resource/receipt acceptance and owner review remain open.

The Rust host now replaces lost API/execution connections with bounded backoff, closing the
old connection before opening its replacement. API operations are never replayed automatically.
The native PostgreSQL test terminates the API session, observes 503 and a durable unchanged
control revision, then reconnects on a later explicit request. A separate actual-CLI fixture
terminates the execution session: the same host process reconnects, completes another review
and returns to exactly two connections without resetting history, budgets or application state.
Shutdown reconciles global pause after all HTTP handlers drain. If it cannot confirm pause,
the host returns a fixed failure code rather than claiming a clean stop.

The optional Telegram relay runs inside this Rust process. It takes the legacy Telegram
kernel lock and uses one connection for the existing Telegram role: three persistent host
connections when enabled, two otherwise. No pool or process per agent is added. Production
transport uses the fixed [official Bot API](https://core.telegram.org/bots/api), four allowed
methods, no proxy/redirect/transport retry, and streamed responses capped at 1MiB. The fixture
mode requires its own numeric-loopback endpoint, so fictional tests cannot reach Telegram.
Bot identity/webhook checks precede processing; no webhook is modified or deleted.

Private owner/chat integer IDs, private-chat type, non-bot sender, forwarding and bot-mention
checks precede command dispatch. Supported commands include status/help/ping, saved run
listing, `/agents review`, and revision-fenced Rust-agent start/pause/stop. Unsupported
legacy/browser/application commands return a migration-unavailable reply and execute no
application action. This is a working new command path, not complete Telegram command parity.

Migration 003 preserves existing Telegram bot pins, offsets and delivery states, adding
private binding/cooldown/outbox metadata. Authorized command intake, offset advancement,
legacy reply and bound outbox insert commit atomically. Duplicate updates do not enqueue
another review. Unbound historical pending replies remain untouched. A send is marked
`sending` before network I/O; ambiguous sends remain quarantined in both outboxes and are
never replayed. Only a validated sent-message receipt marks it sent. Explicitly rejected
HTTP 429 requests can return to pending with a durable provider cooldown. The tested
600-second delay remains above 590 seconds after persistence; it is not capped down.

The execution-role notification tool accepts no model-supplied text, recipient or URL. It
records a stable owner-bound outbox intent and reports `pending`, not sent. With Telegram
configured, saved review performs ten decisions, four actual PostgreSQL read tools and one
notification tool, with zero inference calls/token reservations. The actual CLI fixture
receives two authenticated commands, runs all five roles, and confirms three messages to
its localhost fake Bot API (two command replies and one agent notice), with exactly three
host database connections. No real bot token or Telegram message was used.

| Check | Status | Exact evidence |
| --- | --- | --- |
| Agent/provider/fact/auth/cancellation and Telegram units | PASS | 18 tests: retained 12 plus 6 Telegram transport/owner/rate/webhook/size/receipt cases |
| Coordinator and private host/kernel-lock regressions | PASS | 20 coordinator + 9 host tests |
| Domain matching and native messaging regressions | PASS | 8 domain + 14 native tests; final native suite 1.55s |
| Dedicated native PostgreSQL fixtures | PASS | 43 tests, 0 failed/ignored; final run 6.87s |
| Actual host session recovery and no automatic HTTP replay | PASS | Included above; terminated fixture connections, same process survives, retained state and exactly two connections |
| Telegram cursor/idempotency/atomic rollback/quarantine | PASS | Included above; restart preserves sending/offset, historical pending stays untouched, outbox failure rolls back run creation and cursor |
| Durable 600-second cooldown and bot/owner pin changes | PASS | Included above; early dispatch denied and changed identities rejected |
| Actual CLI owner commands → five roles → bound notice | PASS | Included above; local fake Bot API only, ten decisions/five tools/zero model calls, three connections, SIGTERM pause |
| Format / Clippy with warnings denied / diff | PASS | Local checks; no hosted Actions |
| Locked optimized workspace build | PASS | Local build 1m09s; CLI functional tests use debug build |
| Real Telegram pairing/delivery/webhook/account acceptance | NOT TESTED | No real credentials or official Bot API call |
| Complete legacy Telegram/browser/application commands | NOT TESTED | Remaining ports; unavailable commands do not execute actions |
| Production DB outage/TLS/proxy/ACL and rollback deployment | NOT TESTED | Native fictional PostgreSQL and localhost HTTP fixtures only |
| Full Python removal and dashboard/API parity | NOT TESTED | Existing Python services and frontend still in place |
| Whole-project Mac CPU/RSS/GPU and actual application receipt | NOT TESTED | No new equivalent-boundary resource measurement or live submission |

Current total: **112 distinct Rust tests passed**: 69 standard plus 43 dedicated PostgreSQL.
The standard run deliberately ignores those 43; the dedicated harness executes every one.
This adds 12 tests to the previous total of 100. Earlier separate 1,300 matching comparisons
and 25 native contract examples are retained historical evidence, not rerun here.

Actual Mac evidence here covers kernel locks, process signals, terminated/replaced database
sessions, HTTP transport and complete fixture workflow. All profiles/jobs/owner IDs/messages
are fictional. This is not installed or live portal acceptance. No owner environment,
provider key, production database, cloud inference, Chrome action, Telegram message, Gmail
read/draft/send, real profile save, application, installed-file change, service restart,
hosted Action, cleanup or merge occurred.

Sanitized development failures: Clippy caught a collapsible shutdown condition and an unused
fixture import; compilation caught a moved shared wake handle, now cloned. All final scoped
checks pass. No unresolved scoped test failure remains. Operational limits still pending:
startup transport failure ends initialization; sequential Telegram polling can delay a notice
up to 25 seconds; live rollback must honor the persisted cooldown before starting an older
worker that does not read this new metadata. None of these are claimed as live acceptance.

Reproduction:

```sh
cargo test --locked --workspace
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all --check
cargo build --locked --release --workspace
git diff --check
```

Next: profile/resource/REST contract ports and rich verified resume/project context;
guarded browser/application admission/execution and full legacy Telegram commands; remaining
Gmail/provider/service ports and Python removal; then immutable installation, rollback,
focus/account/history/quota/receipt and equivalent-boundary Mac resource acceptance.
Both requested outcomes remain incomplete.

## Milestone 8: confirmed Decimal facts and profile contract preparation

Implementation: [`61f212f3ca33c439d17656d63c6f792305bc8e13`](https://github.com/karanagg166/automated-apply/commit/61f212f3ca33c439d17656d63c6f792305bc8e13),
branch `feat/rust-agent-runtime`, [PR #50](https://github.com/karanagg166/automated-apply/pull/50).

Profile compatibility inspection found that valid saved Decimal values such as trailing-zero,
exponent and signed-zero representations were incorrectly treated as missing expected
compensation. The Rust question resolver now checks their exact cent value with bounded,
checked integer arithmetic, retaining currency/period/kind and confirmed-profile requirements.
It changes no stored amount or profile fact. A PostgreSQL regression verifies five serialized
forms resume factual review without asking the owner again, preserving prior model usage.
Negative nonzero values, finer nonzero fractional precision and values above the existing
bound remain rejected. No salary preference is inferred as a personal fact.

Public create/update/read JSON Schema snapshots and a drift-check exporter now record the
existing DTO structure. They contain definitions, not candidate data, and load no settings.
They do not replace the profile API: semantic normalization/coercion, email/URL handling,
date order, authorization uniqueness, total payload bounds and repository/HTTP version/ETag
behavior still need their Rust ports and differential verification. No unused runtime
schema dependency was retained. See `rust/agent-runtime/schemas/README.md` for exact limits.

| Check | Status | Evidence |
| --- | --- | --- |
| Standard Rust regression suites | PASS | 69 tests: 18 library, 20 coordinator, 9 host, 8 domain, 14 native; latest native suite 0.80s |
| Dedicated native PostgreSQL fixtures | PASS | 44 tests, 0 failed/ignored; final run 6.82s; one new Decimal/fact regression |
| Public schema drift / exporter Ruff / Rust format / Clippy / diff | PASS | Local checks; snapshots regenerated from public source only |
| Locked optimized workspace build | PASS | Final local build 38.89s |
| Complete Rust profile API/custom validation/REST parity | NOT TESTED | Structural snapshots are preparation; route/repository implementation remains pending |
| Live profile facts, owner DB, installation, full-project resources | NOT TESTED | No owner data or installed service touched |

Total: **113 distinct Rust tests passed** (69 standard + 44 dedicated PostgreSQL).
Schema drift checks and earlier matching/native parity corpora are separate checks.
No unresolved scoped test failures. No new cloud, browser, Telegram, Gmail, profile-save,
application, installed-service, hosted Action, cleanup or merge operation occurred.
No new runtime CPU/RSS/GPU comparison is claimed; prior component measurements retain their
original scope and implementation SHAs. Both requested outcomes remain incomplete.

Additional reproduction:

```sh
uv run --no-project --python .venv/bin/python python -m rust.scripts.export_profile_schema --check
uv tool run --from ruff ruff check --isolated --select E9,F,I rust/scripts/export_profile_schema.py
```

Next remains complete profile/resource/REST compatibility and rich verified context, followed
by actual browser/application tools, remaining provider/Gmail/service ports and Python
runtime removal, then immutable live/rollback/focus/history/quota/receipt/resource acceptance.

## Milestone 9: durable graph, model review and human approval dashboard

Implementation: [`71af35a2aaec9d86a82c15d06790433c8e5703d9`](https://github.com/karanagg166/automated-apply/commit/71af35a2aaec9d86a82c15d06790433c8e5703d9),
branch `feat/rust-agent-runtime`, [draft PR #50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling` / [PR #49](https://github.com/karanagg166/automated-apply/pull/49).
Overall migration and live acceptance remain **IN PROGRESS**.

The Rust worker now persists an observable plan → typed decision → validation → tool →
observation → review graph with bounded replanning, missing-fact waits, human checkpoints,
provider cooldown, pause and uncertain-outcome reconciliation. The five specialist roles
have separate instructions and typed tool permissions and share one worker/lease. They are
not five always-running model processes. Deterministic steps remain the zero-inference
default; optional explicitly consented Cohere review is wired through the real executable.
The reviewer sees a bounded projection of source references and top-three ranking summaries,
verified experience and skill count, excluding contact/resume/free-text contents. Only
handoff, bounded fact questions and bounded replanning are offered by this reviewer schema.
No private model scratch thoughts are required or stored.

Human decisions bind the exact plan revision, current confirmed profile, prepared tool
results, known job references, limits and (when applicable) exact undispatched tool effect.
They expire after one hour. Approve, reject and request changes use CAS and atomic audit;
actor identity cannot be supplied by a model/client body. Changes recompute actual facts,
retain usage, and remain within the original replan/decision/tool/model/token caps. Prior
external effects and unknown outcomes cannot be replayed through a loop. A separately
approved tool still needs fresh backend authority, and approval never grants submission,
changes admission quotas or resets allowances. Old records retain usage and idempotency
when new graph/default limit fields were absent.

The new authenticated `/workflow` page shows interactive stages, specialist tool availability,
worker/run controls, prepared results, budget/audit state and human decisions. Creating a
review through the dashboard enables human review by default. A dedicated loopback-only
proxy checks owner session, host/origin and CSRF, bounds bodies/responses/deadlines, keeps
the bearer token server-side and performs no redirects or automatic write retries. A stale
checkpoint requires refresh and a new review checkbox. Unknown website/tool content is
rendered as escaped data. Missing facts link to the existing profile flow; the running
worker independently rechecks confirmed saved facts. Browser/application adapters are
visibly `not_migrated` and cannot be enabled through this approval UI.

| Check | Status | Exact evidence |
| --- | --- | --- |
| Standard Rust suites | PASS | 78 tests: 20 library, 20 coordinator, 7 graph, 9 host, 8 domain, 14 native; 0 failed; 49 PG cases deliberately ignored here |
| Dedicated native PostgreSQL fixtures | PASS | All 49 executed, 0 failed/ignored; final run 13.36s |
| Exact human review / changes / authority after approval | PASS | Included above: HTTP/CAS/forged actor/stale decision checks, real re-read loops, usage retention, no tool execution after changed authority |
| Actual CLI with optional reviewer and human gate | PASS | Included above: fictional localhost provider, one replan, 7 actual SQL reads, 2 model calls, 10,256 retained reserved tokens, cooldown wait without recharge, owner approve then completion, shared monthly requests exactly 2 |
| Cloud context bounds/privacy | PASS | Captured fixture requests <=5,000 bytes, output reservation 128 each; no fictional private contact/resume/key canaries; separate projection regression |
| Workflow component/proxy regressions | PASS | 10 Vitest cases across 2 files; final run 984ms; CSRF/auth/origin/routes/targets/body/response limits, no redirects/retries, exact revision, escaping and review reset |
| Production frontend build and TypeScript | PASS | Next.js build includes `/workflow` and `/api/workflow`; final compile 1.067s, TypeScript 1.849s; separate typecheck passed |
| Actual isolated Chromium journey | PASS | 1 journey, 2 explicit approval mutations, 0 automatic retries: stale rejection, refresh, checkbox reset, fresh decision and escaped content |
| Rust format / Clippy warnings denied / diff | PASS | Final local checks passed |
| Locked optimized workspace build | PASS | 42.85s local build; functional CLI fixtures use debug executable |
| Real cloud inference / owner browser / official Telegram / real applications | NOT TESTED | All new traffic uses fictional loopback fixtures; no owner accounts/keys/data touched |
| Full Python runtime/API/service replacement | NOT TESTED | Remaining profile/REST/services/browser/application/Gmail/provider ports are still open |
| Installed release / rollback / real focus/quota/receipt acceptance | NOT TESTED | No installation, service restart, production DDL or live action performed |
| Whole-project CPU/RSS/GPU comparison | NOT TESTED | No new equivalent-boundary benchmark; earlier component comparisons retain their scope/SHAs |
| Hosted Actions / merge / workspace cleanup | NOT TESTED | Not dispatched, merged or performed |

Current total: **127 distinct Rust tests passed** (78 standard + 49 dedicated PostgreSQL),
plus **10 frontend tests and 1 isolated browser journey**. Repeated runs and historical
1,300 matching comparisons/25 native parity examples are not added again to these totals.
[Sanitized fictional dashboard screenshot](../../rust/ui/workflow-fictional.png).
The Chromium fixture uses a separate headless profile and a local fake worker. It does not
validate the production owner browser or the Rust worker/Next.js together against live data.
The Rust CLI/PostgreSQL/provider integration is tested separately above. Playwright's pinned
headless shell was added to its development cache (99MiB download), retaining older caches;
no Chrome owner profile, window, foreground state, keyboard or clipboard was used.

Sanitized development failures: fixture setup initially referenced a nonexistent JSON
profile column (`42703`), corrected to the existing fictional preferences column. Tool
catalog compilation initially missed enum imports (`E0433`), corrected before final suites.
The first browser invocation lacked its pinned cached executable; the pnpm-managed headless
shell installation resolved it. Final scoped checks have no remaining failures. Fixed
failure codes exercised include `agent_revision_conflict`, `agent_approval_not_pending`,
`agent_approval_expired`, `agent_approval_context_changed`, `agent_replan_limit`,
`human_approval_required`, `csrf_required` and bounded proxy transport errors. No raw private
logs or personal data are published.

Reproduction from this worktree:

```sh
cargo test --locked --workspace
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
cargo build --locked --release --workspace
pnpm -C frontend install --frozen-lockfile
pnpm -C frontend exec vitest run --config ../rust/ui/vitest.config.mjs
pnpm -C frontend typecheck
FRONTEND_LOCAL_HTTP=true FRONTEND_ORIGIN=http://localhost:3000 FRONTEND_SESSION_SECRET=fictional-build-session-secret-minimum-thirty-two NEXT_TELEMETRY_DISABLED=1 pnpm -C frontend build
pnpm -C frontend exec playwright install chromium --only-shell
node rust/ui/browser-fixture.mjs
git diff --check
```

Next: complete profile semantic normalization and CAS CRUD/ETag compatibility, remaining
REST/services and rich verified context, then actual guarded browser/application and legacy
Telegram commands, Gmail/provider ports and Python removal. Perform immutable installation,
rollback, live account/focus/history/quota/receipt and whole-project Mac resource acceptance
only after those ports are complete. The graph milestone is not full project completion.

## Milestone 10: Rust primary profile normalization and CAS CRUD

Implementation: [`a4976d78a44447be256f62efc5ea0a6e97f851b3`](https://github.com/karanagg166/automated-apply/commit/a4976d78a44447be256f62efc5ea0a6e97f851b3),
branch `feat/rust-agent-runtime`, [draft PR #50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling` / [PR #49](https://github.com/karanagg166/automated-apply/pull/49).
Full migration and installed acceptance remain **IN PROGRESS**.

The standalone Rust host now implements owner-authenticated `GET/PUT/PATCH /api/v1/profile`
using its existing API connection. Authentication precedes bounded body reads; DTO validation
precedes If-Match preconditions. Create returns 201, read/update 200 and strong quoted ETags.
Changed PUT and every PATCH require the current version; stale and ambiguous preconditions
are rejected. A no-op PUT may omit If-Match, while a supplied version is atomically checked
even for a no-op. Source version increments and commit occur before acknowledgment. A failed
result validation or deferred commit constraint rolls the write back. Existing resume
associations, confirmation/history and unrelated fields are excluded from writes. No real
profile was read or saved, and no existing service/proxy was redirected.

The Rust contract preserves normalized dict input versus root ORM read behavior, partial
omission versus explicit null, Unicode skills/deduplication, email/URL normalization,
numeric/date coercion, exact Decimal serialization/cent bounds, chronological dates, complete
profile authorization uniqueness and the 64KiB serialized bound including defaults. Partial
preferences merge one level and revalidate the full resulting profile. Historical raw data
that differs from canonical input still requires a version before any rewrite. GET does not
normalize data in storage. UTC timestamp output retains microsecond precision. The existing
production/staging placeholder fence retains Python's Unicode case and word-boundary rules.

Compiled schema validators disable external/file retrieval and are cached. Public Python3.11
Unicode14 property tables, IDNA PVALID data and a fictional corpus are checked in; they contain
no candidate data. Exporters import public DTOs only, without settings or DB initialization.
The conformance source environment is Pydantic2.14.1/core2.50.1, email-validator2.3.0,
idna3.20 (IDNA data18.0.0). Rust dependencies reuse versions already present in the lockfile;
no runtime interpreter or cloud model is called by profile normalization/persistence.

| Check | Status | Exact evidence |
| --- | --- | --- |
| Standard Rust suites | PASS | 83 tests: 20 library, 20 coordinator, 7 graph, 9 host, 5 profile, 8 domain, 14 native; 0 failed; 54 PG cases deliberately ignored in this command |
| Dedicated native PostgreSQL fixtures | PASS | All 54 executed, 0 failed/ignored; final run 13.58s; 5 added profile integration tests |
| Fictional DTO conformance | PASS | 779 comparisons inside one profile test; accept/reject and canonical JSON match the public Python DTOs, including root ORM reads |
| Actual profile HTTP/CAS/commit visibility | PASS | Included above: owner auth before oversized body, 413/404/405/422/428/409/201/200, strong ETag, duplicate/stale headers, lowercase bearer, independent connection sees commit before HTTP ACK |
| Concurrent saves / unchanged values / history and resume integrity | PASS | Included above: one of two version4 writers succeeds, version5 retained; old confirmation untouched and becomes stale; resume association preserved; no-op timestamp/version unchanged |
| Result-validation and deferred-commit rollback | PASS | Included above: fictional DB triggers force invalid response and commit refusal; original row/version retained, no acknowledgment of success |
| Legacy raw normalization / merged payload / live fence | PASS | Included above: no silent rewrite without version, complete merged oversize rejected without a save, production placeholder input rejected |
| Public schema / Unicode / corpus drift checks | PASS | Local exporters with `--check`; no settings, owner data or network loaded |
| Rust format / Clippy warnings denied / exporter Ruff / diff | PASS | Final local checks passed |
| Locked optimized workspace build | PASS | Final build 1m06s; functional native/HTTP fixtures use debug executable |
| Graph UI, proxy and isolated browser evidence | PASS | Retained milestone9 evidence: 10 UI tests, 1 isolated Chromium journey and frontend production build; unchanged frontend not rerun for this profile port |
| Installed/live profile migration and complete profile feature surface | NOT TESTED | No service cutover; saved-job match, readiness/confirmation, resources and rich context endpoints remain open |
| Exact FastAPI validation-error arrays and all routing aliases | NOT TESTED | Rust uses sanitized `detail` strings; full per-input error arrays and routing parity are not claimed |
| Real account/browser/Telegram/Gmail/application or cloud inference | NOT TESTED | No real owner credentials/data, messages, profile save or application used |
| Whole-project CPU/RSS/GPU comparison | NOT TESTED | No new paired runtime benchmark; earlier native/matching component measurements retain their original scope/SHAs |
| Hosted Actions / merge / installation / cleanup | NOT TESTED | Not dispatched, merged, installed or performed |

Current total: **137 distinct Rust tests passed** (83 standard + 54 dedicated PostgreSQL).
The **779 DTO comparisons** are separate case coverage within one counted test. Retained
milestone9 frontend/browser results and earlier parity corpora are not counted as new Rust
passes. Actual Mac evidence uses the real Rust HTTP server and native disposable PostgreSQL;
all candidate/job/email/resume-link IDs and text are fictional. Production schema, roles,
identity, data, installed releases, Chrome focus and runtime resource acceptance remain open.

Sanitized development findings: comparison fixtures caught omitted nested defaults, complete
versus partial authorization rules, IDNA eligibility, float/integer underscore differences,
exact date parsing and root ORM whitespace behavior. SQLx rejected runtime-generated query
strings (`E0277`); final CRUD uses fixed audited SQL literals with bound data, without an
unsafe SQL assertion. Export import ordering was corrected (`I001`). All final scoped checks
pass; no raw private logs are published. Important tested failures include
`invalid_profile_input`, `profile_payload_limit`, `profile_version_required`,
`profile_version_syntax`, `profile_version_conflict`,
`fictional_or_placeholder_profile_rejected` and `profile_database_error`.

Reproduction:

```sh
cargo test --locked --workspace
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
uv run --no-project --python .venv/bin/python python -m rust.scripts.export_profile_schema --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.export_profile_unicode --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.profile_corpus --check
uv tool run --from ruff ruff check --isolated --select E9,F,I rust/scripts/profile_corpus.py rust/scripts/export_profile_unicode.py
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
cargo build --locked --release --workspace
git diff --check
```

Next remains the rest of the profile/resource/context/matching feature surface and other
REST/services, actual guarded browser/application execution, full legacy Telegram commands,
remaining Gmail/providers and Python removal. The graph currently uses deterministic
specialists with optional model review; expanding multiple model-backed role planning must
retain the same consent and total budget limits. Full project/live/rollback/focus/history/
quota/receipt/resource acceptance has not been achieved.

## Milestone 11: separately instructed planner and reviewer with pinned policies

Implementation: [`414e913691fa4829a793f72f551a97e603910c01`](https://github.com/karanagg166/automated-apply/commit/414e913691fa4829a793f72f551a97e603910c01),
branch `feat/rust-agent-runtime`, [draft PR #50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling` / [PR #49](https://github.com/karanagg166/automated-apply/pull/49).
Overall Python migration, full action tools and installed/live acceptance remain **IN PROGRESS**.

The graph supports two distinct model-backed roles: discovery planning after an actual saved
job read, and review after four factual tool results. Each request has its own role instruction
and schema; discovery selects a matching handoff or a bounded fact question, while review can
hand off, ask a bounded question or request a bounded replan. Runtime filtering also enforces
these allowed decisions, independently of the provider schema. Neither role can dispatch tools,
complete early, grant authority, change quotas or select arbitrary browser/application actions.
Matching/answer preparation and actual tool execution remain deterministic specialists.

`RUST_AGENT_REVIEW_MODEL=cohere` plus `RUST_AGENT_MODEL_ROLES=discovery,review` opts into both
roles, retaining all existing provider/candidate-data consents and shared monthly caps. Without
the role setting, Cohere remains review-only; the overall default is deterministic with zero
inference. These roles share the existing async client/worker/connection architecture; no
process, local GPU inference or database pool is created per agent.

New owner API runs pin provider, exact model ID and inference roles. Policy participates in
request-key idempotency and exact human approval binding. A pinned deterministic run cannot
acquire AI from a configuration change, and a pinned AI run cannot silently lose/switch its
model or roles. Missing/incompatible configuration manually pauses it without new spend;
restore configuration and explicitly resume, or stop it. Legacy unpinned records retain the
old review-only selection and never gain the planner. Existing approval hashing remains
compatible when no policy was stored. New Telegram reviews explicitly pin deterministic mode.

Recommended two-role limits allow one replan and four calls, reserving at most 15,712 input/
output tokens within the existing 16,000 cap. Explicit owner limits are never expanded. Default
owner API intake under configured inference uses bounded model budgets with the legacy read-
review human flag off; the dashboard explicitly creates human-review runs. Omitted limits
are distinct from null, and a client cannot supply its own model policy. The dashboard shows
available model roles and the selected run's pinned policy alongside its usage/audit state.

| Check | Status | Exact evidence |
| --- | --- | --- |
| Standard Rust suites | PASS | 87 tests: 23 library, 20 coordinator, 8 graph, 9 host, 5 profile, 8 domain, 14 native; 0 failed; 56 PG cases deliberately ignored here |
| Dedicated native PostgreSQL fixtures | PASS | All 56 executed, 0 failed/ignored; final run 23.08s; 2 additional integration cases |
| Actual CLI with two model roles and human gate | PASS | Included above: fictional localhost model, distinct discovery/review/re-review prompts, 3 requests, 7 SQL reads, one replan, 11,784 retained reserved tokens and owner approval before completion |
| Durable cooldown / shared provider budgets / bounded context | PASS | Included above: no recharge across repeated provider waits, monthly requests exactly 3, bodies <=3,800 bytes, output reservation 128 each, no contact/resume/key canaries |
| Pinned model configuration and idempotency | PASS | Included above plus library tests: changed policy conflicts rather than replacing a run; unavailable models pause with zero model/tool/token spend; role/model changes are rejected, deterministic/legacy runs gain no planner |
| Policy-bound approval / restricted model decisions | PASS | Graph/library regressions: changing pinned roles invalidates approval; tool dispatch/early completion/wrong handoff denied despite a model response |
| Profile DTO compatibility | PASS | Retained 779 comparisons rerun within the counted profile test; no profile port change here |
| Frontend component/proxy regressions | PASS | 10 tests across 2 files, 984ms; exact approval/review reset/auth/CSRF/boundary/no-retry cases |
| Frontend typecheck and production build | PASS | Final build compile 681ms, TypeScript 1.946s; workflow and protected proxy routes present |
| Isolated Chromium approval journey | PASS | 1 journey, 2 explicit mutations, 0 automatic retries; fresh deterministic policy shown; sanitized screenshot updated |
| Rust format / Clippy warnings denied / diff | PASS | Final local checks passed |
| Locked optimized workspace build | PASS | 1m07s final local build; CLI fixtures use debug executable |
| Actual cloud model behavior, entitlement and live paid budgets | NOT TESTED | No owner key or official provider call; generated decisions are fixture responses |
| Installed/live action tools and full Python replacement | NOT TESTED | Browser/application tools and remaining APIs/services are still pending; legacy live runtime unchanged |
| Deployment/rollback/focus/history/quota/receipt acceptance | NOT TESTED | No installed release, service or owner browser changed; no real application or message |
| Whole-project CPU/RSS/GPU comparison | NOT TESTED | No new paired benchmark; no whole-system resource claim |
| Hosted Actions / merge / workspace cleanup | NOT TESTED | Not dispatched, merged or performed |

Current total: **143 distinct Rust tests passed** (87 standard + 56 dedicated PostgreSQL),
plus **10 frontend tests and 1 isolated browser journey**. The 779 profile comparisons are
within one counted Rust test; repeated runs and historical matching/native corpora are not
added again. [Sanitized fictional dashboard](../../rust/ui/workflow-fictional.png).
All new model, profile, job, owner, database and message data are fictional. Actual Mac
process/HTTP/PostgreSQL/headless-browser evidence is separate from live account acceptance.
No real credentials, owner environment/data, Chrome windows/tabs, keyboard/clipboard,
Telegram/Gmail message, application, installed service, hosted Action or cleanup was used.

Sanitized development finding: Serde's internally tagged unit variant accepted an unexpected
field despite the enum's unknown-field setting. The policy now uses an empty struct variant,
and its regression explicitly rejects an `authority` field. Final scoped checks have no
remaining failures. Relevant fixed failures include `invalid_model_roles`,
`model_roles_require_provider`, `review_model_role_required`, `invalid_model_policy`,
`pinned_model_policy_unavailable`, `agent_model_action_denied` and
`agent_request_key_conflict`. Raw private logs are not published.

Reproduction uses the milestone10 Rust/PostgreSQL commands plus:

```sh
pnpm -C frontend exec vitest run --config ../rust/ui/vitest.config.mjs
pnpm -C frontend typecheck
FRONTEND_LOCAL_HTTP=true FRONTEND_ORIGIN=http://localhost:3000 FRONTEND_SESSION_SECRET=fictional-build-session-secret-minimum-thirty-two NEXT_TELEMETRY_DISABLED=1 pnpm -C frontend build
node rust/ui/browser-fixture.mjs
```

Next: complete remaining profile match/readiness/confirmation/resource/rich-context and other
REST/service ports; implement guarded browser/application execution and full legacy Telegram/
Gmail/provider functionality; remove runtime Python dependencies; then immutable installation,
rollback and actual focus/account/history/quota/receipt/whole-project resource acceptance.
This milestone implements multiple model-backed roles, but does not finish either requested
whole-project outcome or activate live automation.

## Milestone 12: saved-profile job relevance endpoint

Implementation: [`fe2c65970c99455fd07f58a597fe916731bdc667`](https://github.com/karanagg166/automated-apply/commit/fe2c65970c99455fd07f58a597fe916731bdc667),
branch `feat/rust-agent-runtime`, [draft PR #50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling` / [PR #49](https://github.com/karanagg166/automated-apply/pull/49).
Overall migration and live action acceptance remain **IN PROGRESS**.

The standalone owner API implements `POST /api/v1/jobs/<UUID>/match` using the previously
ported pure Rust base scorer. It independently loads the saved job and validated current
profile, preserving skill aliases/labels, score weights, explanations, remote preference and
unknown-experience behavior. Caller-supplied profile fields are ignored as in the original
saved-profile route. Unknown jobs are reported before missing profiles. The existing owner
host/origin/TLS/auth-before-body boundary applies, including case-insensitive bearer schemes,
64KiB bodies and sanitized detail errors. Scores are relevance, not application admission.

| Check | Status | Exact evidence |
| --- | --- | --- |
| Standard Rust suites | PASS | 87 tests, 0 failed; 58 dedicated PG cases deliberately ignored in this command |
| Dedicated native PostgreSQL fixtures | PASS | All 58 executed, 0 failed/ignored; final run 23.45s; 2 added saved-profile HTTP cases |
| Saved facts, exact response and no caller override | PASS | Included above: exact 86.67 result/skill labels/explanation from stored Rust/FastAPI facts despite a caller Python/experience override |
| No score/profile/history/model/application persistence | PASS | Included above: complete before/after raw job/profile/confirmation snapshots identical; agent runs, monthly usage and application packets remain empty |
| Unknown experience / missing job/profile / method and UUID handling | PASS | Included above: no invented seniority points, job lookup precedes profile error, owner auth 401, method405 with Allow POST, invalid UUID422 and missing records404 |
| Rust format / Clippy warnings denied / diff | PASS | Final local checks passed |
| Profile conformance / model graph regressions | PASS | Included in current suites: 779 DTO comparisons and retained actual CLI localhost dual-role/human-approval fixtures |
| Optimized build / frontend/browser rerun for this delta | NOT TESTED | Debug executable/library built by tests; no frontend changes. Prior optimized/frontend/browser acceptance remains pinned to milestone11 |
| Real saved owner data, installation, applications and resource comparison | NOT TESTED | Native PostgreSQL/HTTP data are fictional; no owner DB/profile/browser/provider or installed service touched |
| Hosted Actions / merge / workspace cleanup | NOT TESTED | Not dispatched, merged or performed |

Current total: **145 distinct Rust tests passed** (87 standard + 58 dedicated PostgreSQL).
Retained milestone11 UI/browser evidence is 10 frontend tests and one isolated Chromium
journey. The 779 profile cases are within one Rust test and are not added again to test totals;
no new 1,300-case matching oracle run or new CPU/RSS/GPU comparison is claimed.
No scoped test failure remains. New failure cases include `job_not_found`, `invalid_job_id`
and `match_method_not_allowed`; raw private logs are not published. There is no automatic
DDL, score save, agent/model run, application creation or policy/limit change in this endpoint.

Reproduce with the existing workspace tests, dedicated PostgreSQL harness, Rust format,
Clippy and diff commands. The existing frontend proxy/live services are unchanged. Remaining
profile readiness/confirmation/resources/rich context and other REST/services still need
Rust ports, followed by actual guarded action tools, Python removal and installed/live/
rollback/focus/history/quota/receipt/resource acceptance.
