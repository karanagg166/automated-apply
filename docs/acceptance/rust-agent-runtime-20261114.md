# Rust migration: native transport and coordinator milestones, 2026-11-14

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
