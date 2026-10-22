# Browser assistant delivery and ordered backlog

This is the first safe, testable assisted-browser slice. The ten requested phases
are not all complete. No employer adapter has automated submission authorization.

| Phase | Delivered in this slice | Remaining acceptance work |
|---|---|---|
| 1 Audit | Existing modules, PR #15/#16 and unpublished branches inspected; isolated feature worktree; private changes preserved | Reconcile other branches separately if requested; no merges or production activation |
| 2 Browser | Real Playwright dedicated profile, native form inventory, factual mapping, reviewed filling, validation, manual takeover/cancel | Wider custom widgets, cross-origin ATS frames, destination-reviewed multistep navigation and submission |
| 3 Knowledge | Reuses protected structured profile, projects/evidence, resources, encrypted resumes and packet answers | Structured current/expected compensation, availability/relocation fields and approved reusable answer management |
| 4 AI | Reuses grounding; optional local Ollama and gated Cohere evaluation adapters, deadlines, private request budgets and quota cooldown | Semantic approved-answer reuse, bounded trusted company research, explicit automatic local fallback and live local model verification |
| 5 Execution | Existing idempotent packets/job dedup, exact private PDF selection, revision locking, sanitized structure, manual receipt tracking, no replay | **Next task:** supported mock/employer adapter contract with revision-bound owner submission grants, durable attempt/outcome state, receipt verification and unknown-outcome recovery, with reviewed additive migration/ACL proposal |
| 6 AGY | Installed 1.4.4 inspected; authenticated loopback CLI reuses application APIs; no personal Chrome attachment | Optional MCP packaging and an owner-controlled AGY invocation demonstration |
| 7 Discovery | Existing discovery interfaces preserved, manual employer URL intake added; no LinkedIn/Gmail collection added | Integrate separately reviewed scheduling branch when authorized; future provider activation remains separate |
| 8 Dashboard | URL intake, dedicated browser open, Analyze/Fill/Review/Take Over/Cancel; answers/resume use existing editor; Submit disabled | Submission authorization, adapter receipts/failures and explicit unknown-outcome UI after Phase 5 |
| 9 Tests | Real Chromium fixtures, full backend/frontend regressions, PostgreSQL demo and Next.js/BFF browser journey | Expand concurrency/crash/failure matrix for future automated submission and destination adapters |
| 10 Delivery | Feature branch, code/tests/docs and reviewable PR | Remaining phases and genuine owner/account/production acceptance |

## Verification record

Results are recorded after the final checks below. They use fictional fixtures and
disposable local PostgreSQL 17 only. No private candidate import, real application,
provider/account activation, paid call, email, deployment or remote SQL was run.

- Focused real-browser/provider tests: **26 passed**.
- PostgreSQL/TCP/Chromium lifecycle demo: passed, including a manual fictional
  receipt and durable `user_reported_submitted`; automatic submission stays off.
- Next.js + actual BFF + FastAPI + PostgreSQL + dedicated Chromium: **1 journey passed**.
- Full backend regression with disposable PostgreSQL 17: **1,246 passed**, no skips;
  two existing pypdf deprecation warnings. Subsequent browser hardening was checked
  with focused browser tests, the PostgreSQL demonstration and the dashboard journey.
- Frontend: **34 unit tests**, type checking, formatting and production build passed;
  **six existing browser journeys** passed in addition to the new PG-backed journey.
- Ruff, whole-application Bandit, Python compilation, generated OpenAPI/TypeScript
  contract, dependency consistency, npm audit (zero vulnerabilities), staged
  whitespace and secret checks passed. No new secret baseline suppressions were
  added; the baseline only refreshes an existing README finding's line number.
- This is local evidence; hosted GitHub workflow results are separate from these
  checks. CI now installs the optional browser runtime and runs mock-only PG17
  lifecycle/dashboard checks.

The initial full regression found one obsolete assertion that every Cohere setting
was invalid. It was replaced with an unsupported-provider case; separate tests now
verify each Cohere approval gate and reject Cohere outside evaluation mode. The
initial dashboard journey's five-second assertion expired while a browser was
starting; its launch assertion now matches the bounded browser launch deadline.
A symlinked dependency directory could not be built by Turbopack; a normal isolated
`npm ci` resolved it. These are corrected findings, not successful first-run claims.

## Next implementation order

1. Define durable submission attempts and exact revision/URL/form/value/resume
   authorization; preserve Phase 9 SQL and propose any new migration separately.
2. Implement a mock-only submission adapter first. Persist dispatch before click;
   verify the mock's server receipt, recover unknown outcomes without replay, test
   independent concurrent workers, owner grant expiry/cancellation and false positives.
3. Extend the existing packet lifecycle and dashboard with the reviewed states,
   keeping self-report and verified receipts distinct. No real destination activation.
4. Add a documented employer adapter only after its applicant-side access rules and
   receipt semantics are verified; do not infer permission from an employer API.
5. Complete knowledge/semantic reuse and company-context retrieval, then broader
   custom widgets/navigation and optional AGY/MCP demonstration. Keep restricted
   portals, paid providers, LinkedIn collection and new Gmail ingestion disabled.

R1/R2, real candidate onboarding, employer permission, account authorization,
provider entitlement, production migration and live acceptance remain separate
operational gates. No code-complete label in this document satisfies those gates.
