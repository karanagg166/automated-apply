# Agent tools, browser and continuity checkpoint — 2026-11-15

Implementation: [`7659dfd69e2438a70d649c0cbccdcfab7f98db49`](https://github.com/karanagg166/automated-apply/commit/7659dfd69e2438a70d649c0cbccdcfab7f98db49),
branch `feat/rust-agent-runtime`, [PR #50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling` ([PR #49](https://github.com/karanagg166/automated-apply/pull/49)).
Resumed from `27a9040597f09526094e14291a55d68e5daaed39`, retaining the unfinished PDF port.
**Whole-project acceptance is IN PROGRESS. This is not 100% completion.**

## Delivered behavior

The official Rust MCP SDK3.10.0 now serves bounded native stdio tools through the
authenticated Rust API. Naukri and Instahyre tools read saved jobs; they do not claim
live platform execution. Matching/history remain scoped to saved, verified data.
Optional Telegram notices use the existing paired owner and durable outbox, with one
deterministic notice per run. Arbitrary recipients, text, URLs, policy overrides,
application submission and paid actor execution are not exposed.

The resumed PDF port now handles native encrypted upload, bounded extraction, download
and owner confirmation, retaining legacy Fernet bytes and canonical-resource checks.
An isolated lopdf worker replaces Python on this path. Suggestions stay untrusted until
review. Drive imports continue to require their separate review path. This does not
complete the remaining service migration or remove the installed Python services.

Brave is installed locally and is the new source default for the browser assistant;
installed Edge can be selected explicitly. Existing private config overrides remain.
The Rust inventory supports Brave/Edge/Safari choices while reporting outstanding
binding/focus/transport prerequisites. Safari inventory is not a working Safari adapter.

Private Codex project snapshots, recovery exports and a five-minute macOS backup job
preserve available local history independently of the signed-in account. The repository
now has a [resume record](../project-state.md) and [tool setup guide](../agent/mcp-and-browsers.md).
No transcript, title, credential, private PDF or raw private log is published here.

## Acceptance matrix

| Check | Result | Exact evidence and limits |
| --- | --- | --- |
| Standard Rust workspace | PASS | 124 passed, zero failed; dedicated PG cases intentionally ignored by this command |
| Dedicated native PostgreSQL17 | PASS | 121 passed, zero failed/ignored,31.64s; fictional data only |
| Distinct Rust total | PASS | 245; corpus branches remain within their containing tests |
| Native MCP protocol/API | PASS | Actual stdio initialize, catalog and tool calls through loopback authenticated HTTP/SQL; no secret in results; seven read tools with Telegram disabled |
| Saved Naukri/Instahyre tools | PASS | Platform isolation, bounded limit1–50, strict inputs and no application/run creation; saved data only |
| Telegram notification tool | PASS | Configured owner binding, one outbox row across repeated requests; dispatched unknown send stays `sending` and cannot be claimed again; no real message sent |
| Native private PDF lifecycle | PASS | Four PG/HTTP cases: upload/decrypt/download, primary/version/digest checks, Drive refusal, deferred commit rollback, corrupt ciphertext, auth/content-type/size/worker failures |
| PDF/legacy compatibility | PASS | 24 fictional PDFs evaluated in two modes inside one test; ten suggestion and two Fernet examples inside two other tests; corpus regeneration matches |
| Continuity regression suite | PASS | Ten tests, zero failures; source disappearance/index changes, exact recovery, dedup, partial records, permissions, corruption, absent store, symlinks, traversal and auth exclusion |
| Actual local backup | PASS | 101 project thread records; three available project transcripts preserved;98 indexed transcript paths missing; zero unsafe/unreadable entries at final snapshot |
| Actual older-transcript export | PASS | Two retained older project transcripts reconstructed privately:29,334,516 and8,604,472 bytes; Codex DB unchanged. These are local exports, not restored sidebar entries |
| Scheduled backup | PASS | `com.automated-apply.codex-history` registered,300-second interval, actual last exit0; does not start application services |
| Restore missing chats to Codex sidebar | BLOCKED | Account-filtered app lists two active threads and zero archived; local DB has133 records overall. Missing98 project transcripts were not recovered and the deletion cause is unproven. Account ownership is not rewritten |
| Apify MCP registration | PASS | Codex and VS Code point to the official hosted endpoint restricted to four discovery/docs tools; actual initialize and tools/list HTTP200, exact four-tool catalog, zero actor runs or candidate data sent |
| Brave installation | PASS | Installed Brave157.1.99.57; underlying browser157.0.8103.79; no personal cookies/profile imported |
| Actual Brave extension execution fixture | PASS | 44 cases,122.625s; inactive-tab guards, questionnaires, PDF/account matching, independent receipt checks; zero live Naukri/unexpected requests and zero choosers |
| Actual Brave queue fixture | PASS | 32 cases,85.602s; source facts/search, policy conflicts, Stop and owner-tab guards; zero live Naukri/unexpected requests and zero choosers |
| Python browser regression on Brave | PASS | 20 passed,107.97s: six engine checks plus14 existing browser-assistant cases on fictional localhost forms |
| Extension Node suite | PASS | 397 passed, zero failed/skipped,10.686s |
| Lint/format/contracts | PASS | Workspace/all-target Clippy with warnings denied; Cargo fmt, targeted Ruff E9/F/I, Prettier and Git diff checks; legacy FastAPI export/type regeneration gives no generated frontend diff |
| Existing live application services | BLOCKED | API/execution/frontend/Telegram LaunchAgents remain unregistered with `.plist.disabled` files, as recorded at prior cleanup preflight; port8000 health/readiness unreachable. No implicit restart/cutover performed |
| Real Naukri/Instahyre browser account/application acceptance | NOT TESTED | No live portal navigation, account binding, Apply admission, submission or new worker receipt |
| Edge/Safari live operation | NOT TESTED | Edge selectable but not installed; Safari needs its own transport/focus validation. No substitution of Playwright WebKit for actual Safari |
| Installed Rust cutover/rollback/identity/policy/history/PDF integrity | NOT TESTED | Production runtime not replaced; current consumed allowance not read or reset |
| Whole-path OS foreground focus | NOT TESTED | Headless fixture tab guards passed, but no OS before/after capture. Codex MCP add completed an OAuth flow; its foreground effect was not measured, so it is not accepted as unattended/focus-safe maintenance |
| Whole-project CPU/RSS/GPU/latency comparison | NOT TESTED | No like-for-like complete-system benchmark or performance improvement claim |
| Hosted Actions/merge | NOT TESTED | Manual-only triggers retained; no dispatch or merge |

The four actual Apify catalog tools are `search-actors`, `fetch-actor-details`,
`search-apify-docs` and `fetch-apify-docs`. The OAuth flow does not establish API
credits, entitlement or spending approval. New tools may require a fresh Codex/IDE
session before appearing in its connected catalog. The custom Rust MCP bridge needs
the new Rust API; it cannot be represented as working against the disabled legacy API.

## Failures found and resolved

The inherited PDF parser initially joined adjacent positioned lines, corrupting word
boundaries. In-memory extraction now preserves vertical text boundaries. Another parity
case distinguished an empty EmbeddedFiles dictionary from actual attachments; the two
existing validation/extraction policies retain their intentional difference.

The first expanded PG run had119 passes and one failed fixture assertion: after its
deliberately rejected commit, the API correctly applied its reconnect backoff and
returned503 rather than the fixture's immediate409 expectation. The fixture now waits
for that bounded recovery before the unrelated integrity check. Focused4/4 and the full
121/121 rerun pass. No live transaction or personal data was involved.

Brave's first fixture startup exceeded the existing ten-second startup wait. An isolated
headless diagnostic created its endpoint in6.2s; both complete Brave journeys then passed.
No fallback browser or personal profile was used. The first Python browser run had eight
passes/twelve launch failures because its old Playwright Chromium1208 executable was
absent. Explicit Brave selection reuses the installed app; all20 then pass without
installing a redundant browser. The extension suite initially had two stale fixtures:
version1.3.11 asserted against1.3.40, and an incomplete settings DOM/window/alarms mock.
The stable-ID assertion remains; the mock now covers initialization. All397 pass.

Sanitized application failure codes include `invalid_tool_arguments`,
`unsupported_job_platform`, `telegram_adapter_not_enabled`, `private_resume_changed`,
`canonical_resume_changed`, `drive_resume_review_required`, `private_pdf_integrity_failed`,
`document_worker_unavailable` and `mcp_outcome_unknown_do_not_replay`. Raw logs remain
in ignored private storage. No environment file, auth file, real candidate/resume,
mailbox content or screenshot is included in this publication.

## Timing and storage limits

The timed rows above are actual component/fixture runs on this Mac, not production
throughput. At one five-snapshot observation,15 transcript references represented
199,149,494 logical bytes while44 shared chunks occupied42,150,662 bytes. That compares
retention representations within this backup, not whole-laptop disk reclamation.
Chunks retain unchanged1MiB prefixes instead of copying every complete transcript.
Current debug/test target measured approximately2.6GiB at an observation; compiler time
and accumulated build size do not establish whole-project resource savings.

## Reproduction and next actions

```sh
CARGO_INCREMENTAL=0 cargo test --locked --workspace
CARGO_INCREMENTAL=0 uv run --no-project python rust/scripts/run_postgres_tests.py
CARGO_INCREMENTAL=0 cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.pdf_corpus --check
uv run --no-project python -m unittest discover -s tests -p 'test_project_continuity.py' -v
uv run --no-project python scripts/project_continuity.py snapshot
uv run --no-project python scripts/project_continuity.py verify
pnpm -C extension test
AUTOMATED_APPLY_TEST_BROWSER=brave pnpm -C extension exec node tests/naukri-execution.browser.mjs
AUTOMATED_APPLY_TEST_BROWSER=brave pnpm -C extension exec node tests/naukri-queue.browser.mjs
AUTOMATED_APPLY_TEST_BROWSER=brave uv run --no-project --python .venv/bin/python python -m pytest backend/tests/test_browser_engine.py backend/tests/test_browser_assistant.py -q
uv run --no-project --python .venv/bin/python python backend/scripts/export_openapi.py
pnpm -C frontend api:types
git diff --check
```

Take a manual snapshot immediately before an account switch to cover the five-minute
schedule gap. `recover --thread-id THREAD_ID` reconstructs a retained private transcript
even after its source/index entry disappears. It cannot recreate bytes that were already
missing or change the proprietary app's account visibility.

Continue the [migration plan](../plans/2026-11-14-rust-agent-migration.md): remaining
REST/provider/browser/application/Gmail/service ports, supervised reconnect/controls,
fresh browser account/extension binding, complete foreground preservation, reviewed
STOP-mode cutover/rollback, actual policy/history/identity/PDF/resource verification,
and a genuine worker receipt before recurring AUTOMATIC. Preserve lifetime/hourly
allowances and quarantine; do not assume any admission remains unused. Validate each
later platform independently. No merge until the owner's completion condition holds.
