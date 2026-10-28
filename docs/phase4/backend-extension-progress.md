# Phase 4 backend and extension progress

**Backend/extension increment verified locally. Broad live application acceptance remains PARTIAL.** No frontend source was changed. AGY integration of the additive filters and URL-specific Gmail import states remains separate frontend work.

Branch: `feat/phase4-codex-job-engine`. Worktree: `/Users/karanagg/Desktop/Projects/automated-apply-codex-p4`, linked to the original repository. Initial base: Phase 3.5 integration `d1c2f44e98e809259ff2a558de688aa6fecc9e9d`; its later transaction/runtime corrections are preserved through merge ancestry. Source candidate before report commits: `7e7bedc41c4fbfcaa88e7defc343a789a7a85550`. Resolve the report-inclusive final head with `git rev-parse feat/phase4-codex-job-engine`.

## Implemented behavior

- Added a separate, bounded SmartRecruiters public Posting API adapter with explicit employer allowlists, strict company/posting/URL identity, source publication evidence, local normalization, pagination, request/response caps and existing durable source pacing. It never follows untrusted `ref` URLs, supplies internal-posting credentials or submits applications.
- Preserved Greenhouse, global/EU Lever, Ashby, Remotive, Arbeitnow and Hacker News hiring adapters. Simplify, Workday and company career pages expose explicit manual-import states. Manual imports require factual listing records and remain unconfirmed; no hidden endpoints or unrestricted crawler were added.
- Added job-search filters for explicit country, experience label, actual publication freshness and current nonconflicting 2–10/11–50 company evidence. Approved-experience filtering requires current owner-confirmed years and an explicit numeric listing range; unknown requirements do not become suitability. Same-posting range refresh/removal invalidates obsolete comparisons. Existing skills, role, remote/hybrid/onsite, source evidence, deduplication and human application decisions are preserved.
- Added tentative recruiter-response, employer follow-up and application-update signals from selected Gmail message bodies. Metadata subjects do not establish employer status. Origin account/message evidence remains protected and isolated. URL-specific import states prevent one new import from marking every sibling URL imported; unmapped historical imports retain their ambiguity.
- Extended URL eligibility to Ashby, EU Lever, SmartRecruiters and recognizable Workday applicant paths. SmartRecruiters permits its exact documented `oga=true` view. Generic employer forms require exact configured public origins and use the existing DNS-pinned dashboard browser. The separate command worker keeps its fixed ATS-host boundary. Eligibility never grants site permission or certifies a vacancy.
- Added extension cancellation fences for preparation and native authorization. Late/cancelled responses cannot restore a plan or trigger filling. Restricted Simplify/LinkedIn/Gmail pages are rejected before form DOM inspection. Existing values and files remain preserved; refresh/restart requires fresh inspection/review rather than mutation replay.
- Fixed a shared transaction-ordering defect: packet/browser dependencies now finish before response delivery. Immediate follow-up requests cannot race an uncommitted packet revision; commit failure returns sanitized HTTP 503. Deterministic response-order tests, actual PostgreSQL/TCP reuse, concurrent packets and both cancellation paths verify this. The fix is also incorporated into the same Phase 3.5 integration candidate.

The reusable browser architecture retains text, textarea, radio, checkbox, native select, guarded React event delivery, supported custom-dropdown review, conditional/re-render detection, explicit multi-step review and canonical PDF/digest validation. The extension keeps framework/custom widgets and file uploads manual when safe event or file handling is not established. Sensitive self-identification, legal attestations, consent and CAPTCHA stay manual. Submission stays off and owner-operated.

Unknown factual questions continue through the existing durable NEEDS_INPUT queue: exact protected context, missing evidence, versioned draft, separate factual approval, scoped reuse and staleness after fact changes. No experience, salary, employment history or accomplishments were invented.

## Final local validation

| Check | Result |
| --- | --- |
| Full backend with disposable PostgreSQL 17 and actual container restart | **2,605 passed**, zero failed/errors/skipped; 781.89s; two existing PDF deprecation warnings |
| Final focused transaction/Gmail/forms/packet checks | **108 passed**; included cases overlap the full suite |
| Cancellation, transaction, packet/concurrency and form focused group | **101 passed**, including actual cancellation before/after mock dispatch |
| Full frontend Vitest | **185 passed**, 25 files |
| Production frontend build and typecheck | Passed with worktree-local locked dependencies |
| Production frontend + FastAPI + PostgreSQL Chromium | **17 passed** |
| Full dashboard Chromium suite, fictional isolated SQLite fixture | **12 passed** |
| Extension units/build | **55 passed**, build passed |
| Seven ATS/generic/Google Forms Chromium fixtures | **7 passed**, zero form POSTs; no live-site claim |
| DOM races / actual installed React isolated worlds | **25 / 4 passed**, zero form POSTs |
| Popup and durable unanswered-field journeys | Both passed |
| Actual MV3/native/FastAPI/PostgreSQL Chromium | **23 passed**; zero form submit events/POSTs; 22 retained history rows all `submitted:false` |
| Gmail migration readiness | Passed; staged migration unchanged; no live DDL |
| Changed Python Ruff / full-app Bandit / existing-baseline secret scan | Passed; no baseline widening |
| Pinned Python / production frontend vulnerability audits | No known vulnerabilities |
| Generated API types and standalone TypeScript compilation | Passed |
| API compatibility comparison | Exactly five additive search query parameters; remainder byte-for-structure equal to the Phase 3.5 export |
| Frontend and hosted workflow source diff | Empty; workflows remain manual-only |

The full backend began at `9033b2d4c3eeefb34130b1b596598b0e73a03166`. Later changes before the remaining checks only align the runtime lower bound with the already locked/installed FastAPI 0.143.1 and add documentation/history merges; application/test source and installed dependencies stayed the same. Backend source tree for the verified increment: `2316338a0cf72f492fe12b30f9d5ecdb1c5835a0`; extension tree: `6d5c812d672860f789e22d05a442f90a4abec511`. Reconciling the completed Phase 3.5 report/history must preserve these source trees; otherwise rerun affected checks.

Heavy groups ran sequentially using the existing `/tmp/automated-apply-heavy-tests.lock` inode. The MV3 harness acquired the lock itself. Tests used only disposable loopback PostgreSQL and fictional candidate/employer/provider data. Actual mock submissions exist only in explicitly authorized fictional test fixtures; zero genuine employer submissions occurred.

## Genuine versus fixture acceptance

A separate production-adapter read of the documented public SmartRecruiters company board returned one actual posting from two credential-free GET requests, both HTTP 200, with successful normalization and no rejected evidence. Nothing was persisted, matched to candidate facts or submitted. This establishes one genuine public feed/schema path; it does not establish India/startup suitability or every employer board's availability.

All seven form-site fixtures, React cases, Gmail messages/accounts, unknown answers and application workflows in automated regression are fictional. No genuine Workday login/workflow, physical extension toolbar grant or real employer autofill is claimed. See the [source and site evidence matrix](source-and-site-evidence.md) for exact URL and widget limits. Workday discovery remains manual; server-dependent steps, unsupported packet adapters/widgets and missing destination evidence require explicit manual review/handoff.

The historical 27-job, approximately 95.06s live discovery timeout remains undiagnosed because it lacked stage evidence. Phase 3.5's instrumented fictional benchmark committed 27 jobs in 8.86s under simulated 30ms SQL/100ms provider latency, with 8.54s ingestion and 0.12s provider time. This sensitivity experiment is not a claim that the original live incident was resolved. No expanded live provider run was used to reproduce it.

## Gmail, providers and remaining integration

Gmail's complete local read-only account/scope/isolation/recovery tests and migration-readiness verifier pass. Live schema/runtime activation, each account's own consent, curated selection, restricted-scope review and any body-purpose approval remain external operator steps. No live migration, Google message read, send, compose, forward, mark-read, archive, modify or delete was performed. Use the [exact Phase 3.5 operator procedure](../phase3/phase35-gmail-operator.md).

Apify/Apollo metadata integrations and rights/budget/credit gates are retained unchanged. No paid Actor execution, Apollo enrichment, account rotation, personal LinkedIn cookie use or outreach occurred. Current account credits/collection rights were not newly verified and do not become authorized from a successful metadata check.

AGY's [backend/API contract](backend-api-contract.md) documents all new fields and parameters, safe unknown states, URL-specific Gmail badges and type regeneration. Internal `NormalizedJob` range fields and Gmail dictionary response additions are runtime contracts; the existing OpenAPI does not export them as dedicated components. The generated frontend types add the five query parameters. AGY owns frontend consumption and type-file updates; Codex did not modify `frontend/**`.

Publication remains in dependency order: owner review/merge of #39, reconcile actual main, publish the single ready Phase 3.5 integration PR, then publish dependent Phase 4 work as appropriate. No auto-merge, deployment or hosted CI dispatch/rerun was performed.

## Failed and interrupted runs retained

Initial focused checks exposed test-fixture keyword overrides, one-connection fixture transactions and URL-specific Gmail ambiguity; these were corrected and the focused/full suites rerun. The first complete backend run had **2,600 passed and one real packet-revision race failure**. The transaction-order regression reproduced response-before-commit deterministically; the source fix passed focused tests and the final full suite. A following run was interrupted after old cancellation fixtures deadlocked while waiting for a response their delayed dependency prevented; the fixture was corrected for function-scoped transactions and both actual cancellation scenarios passed before the final full run.

Other interrupted runs were stopped to apply reviewed URL/legacy-evidence corrections and are not passing full-suite evidence. A frontend build failed because Turbopack rejected a dependency symlink outside the worktree; installing the unchanged frozen lock locally resolved it. The API verifier initially assumed internal `NormalizedJob` was an exported component; the corrected comparison established exactly five additive parameters and identical remaining schema. All original receipts remain outside Git at `~/Library/Application Support/Automated Apply/phase4-codex-evidence/`, including JUnit, source manifests, actual public-read receipt, generated types and failed/interrupted logs.
