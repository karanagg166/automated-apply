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
Two available older transcripts were reconstructed privately under
`.local/codex-history/recovered/`; those exports do not restore Codex sidebar entries.

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

Later operational continuation: API and execution services now run from immutable
`8e985c91c58588c9a9160a3e206e760426ac1bfc`; API health/readiness passed. Saved queue
remains STOPPED revision162, supervised4/hourly1, with three uncertain applications
quarantined and zero strict worker receipts. Do not infer unused admissions from today's
daily counter. The additional allowance is exactly the owner's fourth supervised attempt.

Rust native bridge `2e54eec15493f07aba8f112703ca8a4bdb4c3492` is installed for the distinct
Brave host, using direct executable launch and adjacent private config. Chrome's agent
registration was not changed. Native health, profile connection and27 installed file
hashes passed in actual Brave with commands disabled and no site grant. Current source
`1ec7995ff6b92d81eb1590fcdf97ae46690aae23` removes the unsuccessful automatic reload/repair
path and refuses disabled extensions or original portal tabs during setup. A failed reload
temporarily left DISABLE_RELOAD; subsequent cold-start verification restored the main
extension. The temporary helper was verified unregistered and retired. Do not replay any
consumed maintenance intent. Source127 standard Rust tests pass;121 PG tests remain the
previous unchanged baseline; two new setup-policy tests pass. Full maintenance/locked
focus and live application acceptance remain open.

Latest setup steering: the owner explicitly requested autonomous Playwright setup.
A single owned background headful Brave instance is in use; never launch a second process
against its profile or take over another browser. macOS reported the screen locked and
AXWindows hidden; one unlock request was sent. Later independent extension readback
confirmed Naukri permission granted and unrelated example.com denied; queue remains
STOPPED revision162. Verified Naukri identity was recovered privately by matching retained
actual profile UI evidence to the current approved hash. One ordinary email-verification
request failed with “Something went wrong”; delivery is unconfirmed, do not resend. The
matching project's Gmail account requires reauthorization on actual search (409), despite
its saved connected status. No password was changed.

Existing Chrome Profile8 is PROFILE_OFFLINE (heartbeat over52hours old; absent from saved
active profiles). A persisted connected flag is not a live connection. No inactive Chrome
profile document was available. Native setup helper3744b12 now permits only the approved
ordinary profile request and refuses Chrome WebUI; nine tests pass. Its actual invocation
failed PROFILE_OFFLINE before creating an intent/tab. The missing Chrome native-host
registration was restored to the same canonical immutable Rust2e54 executable used by
Brave; actual framed API health passed, but Chrome's extension reconnection is unaccepted.
The original registration was absent, so rollback removes only the new hash-matched
manifest. No Chrome extension was updated and no browser was launched or activated.
Actual sampled OS focus/window order and selected Chrome tab IDs remained unchanged.
See [the native profile/account report](acceptance/native-profile-setup-20261115.md).

The remaining physical step is owner unlock/opening the existing approved Chrome Profile8
once, or account sign-in in the owned Brave window. The existing launcher refuses startup
while another Chrome profile runs to preserve owner focus. Do not ask for terminal or
extension-configuration work again. Keep queue STOPPED, Brave commands disabled, all three
uncertain applications quarantined and all maintenance/verification intent metadata private.
Continue independent Rust ports while waiting; full migration is not complete.

Rust local-model milestone `06f9b4c7abe2e10fb6198886747ac5e1d2efcfb6` ports explicitly enabled
Ollama structured drafts. It preserves the legacy optional owner-preference ledger,
consumed quotas/cooldowns, locality checks before candidate text, bounded HTTP and the
shared generation permit. Fresh129 standard +131 disposable PostgreSQL tests pass (260
distinct); Clippy and formatting pass. No real model was started or downloaded. AGY,
local fallback and the separate rearranger remain pending. See
[the local-model report](acceptance/rust-ollama-20261115.md).

Rust notification milestone `8e35f7ad5a5ba845c516cb7622be1ecc6adb3da5` adds owner inbox,
mark-read and saved delivery-history routes on the existing connection. Fresh129 standard
+135 disposable PG tests pass (264 distinct); Clippy/formatting pass. Independent read-only
review found no blocking defect; stricter query/response caps are documented. No production
notification dispatch/data change or Rust runtime installation occurred. Notification
preferences/synchronization and the remaining services still need ports. See
[the notification report](acceptance/rust-notifications-20261115.md). Next independent
work is the complete saved-jobs listing/detail/match/shortlist flow while Profile8 remains
offline and the owner's physical browser step is pending.

Saved-job screen milestone `2195b4c8ac9b144138912eb9309171bace790a05` ports complete listing,
full17-field details, GET/POST matching and row-locked shortlisting. Fresh129 standard
+140 disposable PostgreSQL tests pass (269 distinct); Clippy/format/diff pass. No-op
timestamps, method-specific match lookup order, concurrent progression and suppressed
updates are covered; no production job write or application authority. See
[the job catalog report](acceptance/rust-job-catalog-20261115.md). Continue application
packet lifecycle/review/readiness and immutable snapshots next, preserving all legacy
queue/admission/quarantine constraints. Native Profile8 remains offline; the owner's
physical browser step is still pending and must not be inferred from “continue”.

## Remaining acceptance

Finish and test PDF, Rust service/API/browser/application/Gmail ports and integrations.
Validate every job platform with real account evidence. Complete STOP-mode installation,
rollback, focus, policy/history/identity/PDF integrity and CPU/RSS/latency measurements.
Fixture success does not count as a real application. No hosted Actions; merge only
after the owner's completion conditions hold.

Detailed plan: [Rust migration](plans/2026-11-14-rust-agent-migration.md). Publish each
milestone and exact test counts in `docs/acceptance/`, update the PR and this record,
and preserve the ownership handoff. Never publish private transcripts or credentials.
