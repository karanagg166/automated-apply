# Rust and multi-agent migration

Owner request: replace Python runtime services with Rust, reduce measured Mac resource use,
and support coordinated AI agents using Telegram, browser and application tools.
Working branch: `feat/rust-agent-runtime`, stacked on `chore/uv-python-tooling` (PR #49).
The existing Python backend contains 355 tracked application modules / 56,272 lines;
this is a staged behavioral migration, not a claim that scaffolding replaces the backend.

## Acceptance sequence

1. Rust workspace, locked Cargo dependencies and low-contention compilation. Port native
   messaging transport, schema, private configuration, bounded reads, backend authentication,
   response validation and rollback-only retries. Compare against actual Python executable
   using fictional localhost HTTP requests on the owner's Mac. Preserve installed wrapper.
2. Durable coordinator with specialist discovery, matching, grounded-answer and review
   agents. Models propose typed tool calls; a separate broker enforces owner/policy grants.
   Bound active tasks, token/tool budgets and provider retries. Default local inference off.
   Persist agent handoffs, leases, budget consumption and uncertain side effects in PostgreSQL.
3. Port tool adapters and workers: existing extension transport, Telegram owner pairing,
   verified candidate/project/resume contexts, queue, history reconciliation and application
   admission. Preserve exact API/OpenAPI and extension contracts during cutover. Existing
   Python adapters are transitional dependencies until individually replaced and accepted.
4. Port REST/dashboard, database repositories, AI providers, Gmail read/draft and remaining
   maintenance commands. No runtime Python dependency is permitted at final acceptance.
5. Full contract/regression validation, isolated PostgreSQL failure/recovery checks, real Mac
   idle/loaded CPU/RSS/latency comparisons, and honest GPU evidence. Install immutable
   releases with rollback under STOP. Verify real account/history/policy/resume integrity,
   inactive browser focus and restored readiness. Do not replay quarantined jobs or exceed
   remaining admission allowance. Confirm actual receipt before recurring AUTOMATIC.

## Invariants

- pnpm for JavaScript; Cargo for Rust; uv for remaining Python tooling.
- No local model/GPU process starts merely because multiple agents exist. Prefer deterministic
  routing and reuse verified results; one browser executor and bounded model concurrency.
- PostgreSQL remains the durable queue; no Kafka, Redis or new live connection pool introduced
  during development. Fixture-only data may use in-memory test doubles.
- Model output, Telegram text, websites and job descriptions cannot grant privileges.
- Preserve current saved policy (age14, applicants1000, score50, any verified skill), history,
  hourly1, lifetime supervised cap3 and actual consumed admissions. Read current state at
  cutover; never overwrite it with defaults or assume the third attempt remains unused.
- Gmail READ + CREATE DRAFT ONLY. No CAPTCHA/rate-limit bypass, uncertain-action replay,
  owner keyboard/clipboard, active-tab edits or browser foreground changes.
- No Chrome WebUI/settings automatic navigation; native inactive setup path still needs
  complete real focus acceptance before unattended extension replacement.
- No hosted Actions, cleanup, deletion or merge before completed/reviewed/validated delivery.

## Completion ledger

| Deliverable | State |
| --- | --- |
| Rust native transport | Implemented;14tests +25parity examples +Mac fixture benchmark; uninstalled |
| Agent coordinator and specialist roles | Core library implemented;15state tests and scripted five-role workflow; live providers/adapters pending |
| Durable PostgreSQL runtime and restart recovery | 9actual Mac PostgreSQL fixture tests passed; production migration/ACL/install pending |
| Verified profile / saved matching / history read tools | Implemented with actual PostgreSQL fixtures; 1,300 matching comparisons pass; uninstalled |
| Rust browser / Telegram / application adapters | Pending |
| Full Python removal and API parity | Pending |
| CPU / RSS / GPU resource acceptance | Native and warm matching component gains measured; whole-project/GPU acceptance pending |
| Immutable install / rollback / real submission acceptance | Not performed |

The session cannot self-resume after a platform usage-limit reset unless the hosting
application supplies scheduling. Keep this plan, commits and acceptance reports as the
resume record; do not implement a loop that attempts to bypass platform usage limits.

Milestone implementations: `fcb2722` native host and `52fdfa6` durable coordinator;
[PR#50](https://github.com/karanagg166/automated-apply/pull/50).

Provider milestone: `a7610ec` adds fixture-tested Cohere V2 and the shared legacy monthly
ledger.46Rust tests now pass (33standard+13native PostgreSQL), plus25parity examples.
No provider key, real cloud call, runtime installation or owner DB change. Worker routing,
actual tools, other providers and full backend/API migration remain open.

Matching/knowledge milestone: `6c6f43f` + `99b19fc`; 64 Rust tests pass (44 standard +
20 dedicated PostgreSQL), plus 1,300 scoring comparisons. Warm 1,300-case computation
uses 61.622ms Python versus 12.726ms Rust CPU in the published paired fixture benchmark.
Actual action adapters, worker lifecycle, full backend replacement and installed acceptance remain open.
