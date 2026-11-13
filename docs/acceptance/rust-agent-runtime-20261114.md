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
