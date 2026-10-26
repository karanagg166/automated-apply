# Command execution verification — 2026-10-26

Base: `7dfe694fa0166c88131a2f4b529d0b6ea5c77ce4`,
`feat/phase1-local-connections`. PRs #20 and #21 were already integrated and were
not integrated again. Work is isolated on `feat/agent-command-execution`.
The original worktree's untracked `AGENTS.md` and unfinished registry were inspected
and preserved; there was one agent writer and no delegated writers.

## Final local validation

| Check | Result |
|---|---|
| Full backend, including all disposable PostgreSQL integrations | **1,807 passed**, zero skipped; 140.73 seconds |
| Command execution tests included above | 26 passed |
| Command PostgreSQL 17 acceptance included above | 1 passed |
| Typed planner tests included above | 18 passed |
| Official Cohere V2 mocked provider contracts included above | 28 passed |
| Frontend unit tests | **50 passed**, eight files |
| Chromium browser E2E | **10 passed**, including new Agent workflow |
| Extension v1.2.1 tests | **27 passed**, build passed |
| Frontend typecheck, production build, Prettier | Passed |
| Modified Python Ruff E9/F/I; full backend application Bandit; compileall | Passed |
| Python pinned dependency audit and pnpm audit | Zero known vulnerabilities |
| pip dependency consistency | Passed |
| Tracked-file detect-secrets baseline check and diff whitespace check | Passed |

Two existing pypdf `add_js` deprecation warnings remain in security fixtures.
No test, assertion, security detector or coverage requirement was disabled.
All heavy local runs held the existing shared flock. No Ollama/model generation
was used. Disposable PostgreSQL 17 was task-created at localhost port 55444; owner
Supabase and candidate records were never test targets.

Final-head GitHub Actions links and commit/PR identifiers are in the PR and delivery
report. Local checks are not represented as remote CI acceptance. Workflows now
also run for a PR targeting Phase 1, including full backend and frontend suites and
the existing public-schema/native-host lifecycle acceptance.

## Executed outcomes (fictional fixtures)

- `Find backend jobs in India`: real saved job reads and deterministic matching.
  Browser fixture: four saved results, then `Only companies with 2–10 employees`
  returns one proven match and one unknown-size candidate. Rankings survive reload.
- The full 10-job Python/Indian-startup/2–10 employee/rank/prepare-best-five command
  resolves the single eligible fixture job and prepares its actual persisted packet;
  no job IDs or packets are invented to reach the requested maximum.
- `Prepare applications for the first one`: existing packet service persists one
  packet. Repeating the command cannot create another candidate/job packet. Missing
  profile review abstains without creating a packet; changed facts mark old packets
  stale and return `needs_input`.
- `Apply to the first one`: waits for nonce/revision-bound draft approval. Submission
  approval is rejected. Browser cancellation remains cancelled after reload.
- `Use Quick-Clinic as my main project`: selects an exactly named approved fixture
  project. Its approved contribution and source references enter preparation results.
  An unknown/unapproved project returns missing information.
- `Find backend jobs in India from Arbeitnow`: the actual free adapter parses mocked
  HTTP source data; the existing discovery/ingestion services save its discovery run,
  job, source observations and campaign references. This is explicitly a fixture,
  not a live portal finding. An uncertain pre-existing discovery run is not reissued
  or reported successful. Naukri returns manual/unconnected rather than paid dispatch.
- A real Cohere adapter over MockTransport parses an official V2 JSON envelope into
  Understanding, reaches the real executor and saved job, and records one reserved
  request plus 42 input / 7 output tokens. Separate V2 tool-call tests validate
  JSON-string function arguments and reject forged/unavailable actions.

Telegram tests exercise authenticated message intake, duplicate delivery, natural
follow-ups, saved positional preparation, and a real polling-loop transport failure
after task acceptance. The campaign finishes once; ambiguous reply delivery remains
`sending` and is not replayed. A separate completion reply is uniquely queued when
acceptance was already dispatched. API tests verify owner auth/history/cancellation;
the browser uses the actual Next.js BFF, FastAPI and worker. Browser screenshots are
retained in the frontend CI artifact (`command-execution-dashboard.png`).

## Durability and permissions

The PostgreSQL test applies the existing public bootstrap in a newly created local
database with unique isolated role names. It uses the production restricted grants,
including **no UPDATE grant on agent_operations**. Campaigns use private mutable
owner-preference records; tool/intake receipts remain append-only. Two competing
claims admit one worker, including when the active row is locked by a heartbeat.
Heartbeat, lease expiry, fencing, cancellation, new executor instance and reopened
engine preserve actual packet/results without duplication. A simulated failure
between packet insertion and progress commit rolls both back before bounded retry.
The adapter → discovery → ingestion → PostgreSQL chain is included.

The fixed eleven-tool registry validates identity, typed arguments, exact planned
step, genuine result IDs, platform policy, reviewed facts, draft scope and budgets.
Forged SQL/shell tools, cross-owner identities, invented IDs, exceeded budgets,
unauthorized submission and replay conflicts fail closed. Prompt-injection listing
text never becomes an instruction. `fill_application` and `submit_application`
remain unavailable. No real application submission or email send occurred.

## Outstanding live boundaries

No Cohere key is present in the process environment, backend `.env`, or private
Phase 1 configuration inspected. Evaluation key status, live model access and
account-level quota are unverified; **live Cohere acceptance is blocked**. Before
activation the owner must confirm a free evaluation key and the separate command
text / candidate data consents, then run a small fictional-data evaluation.

The feature branch is not installed into the owner's existing runtime. Live
Telegram/online-database acceptance requires deploying the reviewed release using
the existing approved configuration. No production DDL, host deployment, launchd
change or new cloud hosting was performed. Physical locked-screen/sleep/offline
acceptance is not claimed by these simulated restart/network tests. A sleeping Mac
still pauses local work; no 24/7 control plane is claimed.

Automatic submission remains blocked by the explicit capability gate, absent
independently accepted portal filling/submission integrations, and the requirement
for exact owner submission approval. Account sign-in observations cannot remove
these blockers.
