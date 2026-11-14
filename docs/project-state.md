# Project resume record

Read this file, `AGENTS.md`, the ownership registry and the current branch diff before
continuing after an account switch. Source of truth: this repository and
`karanagg166/automated-apply`; private state stays in ignored `.local/` and the approved
online PostgreSQL database. A missing Codex sidebar entry does not establish deletion.

## Current work

Development branch: `feat/rust-agent-runtime`, PR #50, base `chore/uv-python-tooling`
(PR #49). The Rust migration is incomplete. Installed legacy services and the extension
must not be mistaken for development. Resume this checkout and preserve inherited dirty
PDF/document-worker work. No new worktrees or source copies.

Latest owner steering, 2026-11-15: complete agentic automation; provide Apify MCP and
Telegram tools; prefer Safari, Edge or Brave over Chrome. Existing quotas, first-receipt,
identity/resume, focus, budget and uncertain-action rules remain. Browser changes need
fresh account binding and actual focus/receipt validation. Never copy cookies or silently
fall back to Chrome.

## Continuity

`uv run --no-project python scripts/project_continuity.py snapshot` preserves available
local project transcripts and metadata in owner-only `.local/codex-history/`. Immutable,
SHA256-checked 1MiB chunks share unchanged prefixes; snapshots never erase old history.
Auth, environment files and other projects are excluded. `verify` checks retained history.
`install-backup` installs a five-minute macOS background backup; it never launches a
browser or edits Codex's DB. `resume` displays this file. Backups are never uploaded.
`recover --thread-id THREAD_ID` reconstructs a private JSONL export from retained chunks
even if the source/index entry later disappears; it does not change account ownership
or make the app show a chat belonging to another account. Take a snapshot immediately
before switching accounts to cover the five-minute scheduling gap.

Local investigation: 133 indexed Codex threads, 101 for this project; three project
transcript files remain at their indexed paths. The account-filtered app listed two
active threads and no archived threads. The cause of missing files is unproven. Do not
rewrite account ownership or claim missing transcripts recovered. App-owned history
visibility cannot be repaired by changing this project's application.

Implemented in this continuation: private scheduled backups/recovery, the official
four-tool public Apify MCP registration, a native Rust MCP tool bridge and fixed
owner-bound Telegram notice API, encrypted PDF/document-worker port, and explicit
Brave/Edge browser selection. Brave was installed and passed 44 execution plus 32 queue
checks on fictional provider pages. The four application LaunchAgents remain
unregistered as recorded during the earlier migration cleanup; port8000 is offline.
Do not mistake the independent history-backup LaunchAgent for a running application.
See [MCP and browser setup](agent/mcp-and-browsers.md) for actual tool scope and commands.
Implementation `7659dfd69e2438a70d649c0cbccdcfab7f98db49`; [published checkpoint](acceptance/agent-integrations-and-continuity-20261115.md)
records245 Rust tests,20 Python browser checks,ten continuity tests,397 extension unit
tests and76 Brave fixture cases. Full live acceptance remains incomplete.

## Remaining acceptance

Finish and test PDF, Rust service/API/browser/application/Gmail ports and integrations.
Validate every job platform with real account evidence. Complete STOP-mode installation,
rollback, focus, policy/history/identity/PDF integrity and CPU/RSS/latency measurements.
Fixture success does not count as a real application. No hosted Actions; merge only
after the owner's completion conditions hold.

Detailed plan: [Rust migration](plans/2026-11-14-rust-agent-migration.md). Publish each
milestone and exact test counts in `docs/acceptance/`, update the PR and this record,
and preserve the ownership handoff. Never publish private transcripts or credentials.
