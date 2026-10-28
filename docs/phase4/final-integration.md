# Phase 4 final combined integration and acceptance

**COMBINED ENGINEERING PASS. Permitted genuine source persistence/deduplication/matching passed; broader live application acceptance remains PARTIAL.** All final suite results below come from this frozen combined implementation, not separate agent results.

## Candidate and ancestry

Branch: `integration/phase4-final-20261028`. Linked worktree: `/Users/karanagg/Desktop/Projects/automated-apply-phase4-integrated`.

| Input | Full SHA | Integration |
| --- | --- | --- |
| Verified Phase 3.5 | `350f6dea28ae89e136987015aa9c15360d53f4ea` | Exact starting point |
| Phase 4 backend/extension | `993a6960dd2dd46c593a150840b62b444579af89` | Complete history-preserving merge |
| AGY dashboard | `b467904cfff2002d607461eadfa9d88122debc6c` | Resolved locally and merged with its complete history |
| PR #39 | `e57178b22e453119f4ba449dae28f36c01b6edc5` | Ancestor; still open and untouched |

Tested implementation: `995a30786fe392a91877710fd3eaa507b1e0e0ef`. The final report-inclusive SHA is `git rev-parse integration/phase4-final-20261028`. All four inputs above are ancestors. Freshly fetched `origin/main` was `ec5dc9b26363b762b4fa508e6d17583741101a5b` (PR #37 merge), also an ancestor. The primary checkout remains on `e08b7f0c6c961b0228eddfd70dabb8dbb4c63a88`; its dirty files/private configuration were preserved. No duplicate clone, source-agent branch rewrite, push, hosted job, merge of #39 or deployment occurred.

AGY's source branch was clean at the supplied pin. During combined testing AGY also supplied generated API types and a 15-second Vitest test timeout in the integration worktree; these were preserved and included in the final complete frontend rerun. The owner confirmed AGY would freeze that worktree. Both workers used the existing lock; this report counts Codex's combined-candidate receipts, not independent agent passes.

## Integrated behavior and corrected contracts

| Area | Result and combined evidence |
| --- | --- |
| Job search | Country, exact source experience level, publication age, `2-10`/`11-50` company evidence and approved numeric experience fit are backend filters before pagination. Unknown evidence does not pass. Chromium seeded 22 records with the India record outside the first page, then found it through the actual UI/backend country filter. |
| Source availability | Source IDs come from the registry; fallback Simplify identity is `simplify`, not `simplify_jobs`. The UI shows actual availability/adapter type and does not infer a green “Verified” state from a vendor name, missing metadata or account type. |
| Matching | Matched view sends a minimum score to the server. Approved-experience fit requires current owner-confirmed factual years and explicit published numeric listing bounds; title labels never establish years or eligibility. Optional salary/deadline refinements and salary/company sorting explicitly apply to the displayed page; no salary minimum or currency conversion is fabricated. Pagination remains usable when those refinements empty a page. |
| Application packets | Actual PostgreSQL/HTTP checks cover creation, immediate reuse, response-before-commit protection, idempotency, concurrent creation and truthful readiness. A packet is not an application submission. Removed the UI's ineffective rejection action rather than pretending it persisted employer status. |
| Gmail evidence | Account-specific lead `import_state`/`imported_job_ids` drive import badges and notices. A same-URL job elsewhere, a sibling link or a message-wide historical import does not prove this account's URL was imported. Historical ambiguity remains visible and reviewable. Signals remain tentative, with status unconfirmed. |
| Candidate knowledge | Actual owner UI/API/PostgreSQL journeys exercise career facts, protected versions, exact approval/history/reuse, conflict handling, fact-change staleness and unsupported/missing questions. A DOM field ID is no longer used as a durable saved-question ID; deep links use packet provenance when present, otherwise the queue. |
| Browser lifecycle | Current DOM inspection supplies field support. URL host recognition is informational. Existing field preservation, reviewed controls, manual handoff, missing answers, cancellation fences, page changes, multi-step review and canonical resume validation remain enforced. |
| Startup/company/contact evidence | Running PostgreSQL browser journeys cover India and 11–50 evidence filters, exact versus reported headcount, company source review and grounded answers. Inherited provider gates retain unknown/unverified contact states; source visibility or a leader/profile URL is not a verified contact or permission to collect. No actual Apollo contact lookup was authorized or performed. |
| Login | A real Chromium run exposed pre-hydration default GET form submission. Login now has a POST fallback and disabled controls until initialization. Server-render and JavaScript-disabled Chromium regressions verify that a passphrase cannot be put into a default GET URL through this form. |
| API types | Regenerated from the combined FastAPI application. OpenAPI adds precisely five job-search parameters; the rest remains structurally compatible with Phase 3.5. Internal normalized-job/Gmail dictionary fields remain runtime contracts, verified through focused and running-API checks. |

No new Phase 4 schema migration or dependency upgrade was introduced. All hosted workflow files are unchanged from Phase 3.5 and retain manual-only triggers.

## Final verification

Heavy suites ran sequentially using atomic `fcntl.flock` on the existing inode at `/tmp/automated-apply-heavy-tests.lock`; the inode was never unlinked. This task used its own `automated-apply-phase4-integrated-test:55439` disposable PostgreSQL 17 fixture. The native harness acquired the lock itself after the outer runner released it, avoiding nested-lock deadlock. Real data was never written to SQLite; the separate dashboard SQLite journey uses fictional fixtures only.

| Check | Final result |
| --- | --- |
| Full backend, disposable PostgreSQL 17, actual container restart | **2,607 passed**, zero failures/errors/skips; 785.48s; two existing PDF deprecation warnings |
| Gmail forward/replay/drift/rollback/RLS readiness | **Passed**, two schemas, failed-DDL atomicity, isolated accounts and session recovery |
| Full frontend Vitest | **198 passed**, 28 files |
| Production build, TypeScript, frontend formatting | **Passed** |
| Production frontend + FastAPI + PostgreSQL Chromium | **19 passed** |
| Complete dashboard Chromium, fictional isolated SQLite | **13 passed**, including scripts-unavailable login |
| Extension units/build | **55 passed**; final build passed |
| Seven URL-shape form fixtures in real Chromium | **7 passed**, zero form POSTs; zero live vendor workflows |
| DOM race / actual installed React isolated-world checks | **25 / 4 passed**, zero external requests/form POSTs |
| Popup / unanswered-field browser journeys | **Both passed**, including one-shot fill, preservation, stale DOM and manual controls |
| Actual MV3/native-host/FastAPI/PostgreSQL Chromium | **23 passed**, zero failures; zero form submit events/POSTs; 22 audit rows, all `submitted:false` |
| API regeneration/compatibility, dependency/security scans | **Passed**: exact generated types, five additive OpenAPI parameters, Ruff, full-app Bandit, unchanged-baseline secret scan; pinned Python and both full/production frontend JS audits report no known vulnerabilities |

Focused test counts overlap complete-suite results and are not added to them. Browser tests use fictional provider/employer/candidate data. Explicit mock-submission tests target the isolated local employer only; no genuine employer submission or Gmail write occurred.

Verified source trees: backend `958974332b23fdc379813d71b605ffbbe284e8d4`, frontend `75fbce35c5b368d48401670168d7f3204b5d81b9`, extension `6d5c812d672860f789e22d05a442f90a4abec511`.

A fresh [fictional dashboard screenshot](screenshots/integrated-jobs-fictional.png) was captured during the combined PostgreSQL Chromium suite. The [machine-readable verification manifest](verification.json) records totals and final check exits; the exact Git commit and source trees are listed above. Raw logs, JUnit, runner manifests and private match receipts are outside Git at `~/Library/Application Support/Automated Apply/phase4-integrated-evidence/`.

## Controlled 27-job performance acceptance

The [retained benchmark receipt](ingestion-benchmark.json) uses the actual ingestion/orchestration code, disposable PostgreSQL, a one-connection pool, a fictional Greenhouse response, simulated 30ms SQL latency and 100ms provider latency. Neither run contacted a live job provider.

| Measurement | Before | After |
| --- | ---: | ---: |
| Jobs committed | 27 | 27 |
| SELECT statements | 113 | 86 |
| Total measured time | 8.7646s | 7.7250s |
| Checked-out connections after run | 0 | 0 |
| Commit acknowledgments | Both received | Both received |

The reproduced cost was a separate legacy-URL query for each unseen posting. Exact and legacy URL candidates are now resolved in one read, with an uncorrelated existence guard that avoids loading legacy candidates when an exact URL exists. Source identity remains first, exact URL second, canonicalized legacy URL third; similarity alone never merges jobs. Transaction locking, savepoints, conflicting evidence and human application state are preserved. The regression failed on the original three-read implementation, passed with two reads after the fix, and focused identity/ingestion checks passed. The observed 27-job reduction is 27 reads and 11.86% elapsed time in this controlled comparison; timing is environment-dependent.

Three/27/100-job fixture runs all committed and returned their connections. This demonstrates a reproducible local improvement, not resolution of the historical approximately 95.06-second live 27-job failure. That incident lacks stage timings, so its original cause remains undetermined. New genuine one-job timings likewise do not establish 27-job live recovery.

## Genuine no-cost source observations

The sanitized [real-source receipt](live-source-observations.json) records **five credential-free GETs**: Ashby Sarvam twice, Lever Saviynt once, and SmartRecruiters' documented public company listing/detail once each. Every request returned HTTP 200. No candidate data or credentials were sent to those hosts.

- The first bounded samples normalized 20 Ashby, 10 Lever and one SmartRecruiters records. Local role/location filters retained one Ashby record; the other records were skipped, not invented or recast as suitable jobs. Zero retained results in those Lever/SmartRecruiters samples does not mean those employers have no relevant vacancies.
- The actual retained record is **Platform Engineer - AI Infrastructure**, Sarvam, **Bengaluru**, with its [official posting](https://jobs.ashbyhq.com/sarvam/fcb15601-6440-41f7-aa79-b9992057a4b2). The job and one source observation were committed to the existing approved online PostgreSQL database and matched locally against the currently owner-approved candidate profile.
- A new bounded Ashby run reobserved that record: **zero inserts, one update, one duplicate**; the same job ID, single source observation and human application state were preserved. Each run's idempotent replay made zero additional HTTP calls. Both live processes left zero connections checked out.
- Explicit country was absent even though the reported location was Bengaluru. Published numeric experience, structured required skills, company size/stage and salary were not established. These remain unknown; no approved-experience fit, 2–10/11–50 company classification or candidate suitability is certified. No packet was approved and no employer form was filled or submitted for this listing.

Board grants used for these bounded reads were process-local; live runtime configuration was not deployed or broadened. The complete credential/candidate-bearing target and match details remain private.

## Supported discovery and browser limits

The [evidence matrix](source-and-site-evidence.md) separates public discovery adapters, manual imports, URL eligibility, actual controls and genuine site acceptance.

Implemented no-cost public discovery adapters are **Greenhouse, Lever/global and EU, Ashby, SmartRecruiters, Remotive, Arbeitnow and Hacker News hiring**. Employer-specific ATS reads require explicit board configuration; metadata availability is not live connectivity. This integration refreshed live reads only for Ashby/global Lever/SmartRecruiters. Greenhouse and the remaining adapters have engineering coverage and documented interfaces, not a new live acceptance claim here.

**Workday, Simplify Jobs and generic company career pages remain manual discovery imports.** Taleo/Oracle URL detection establishes no dedicated vendor adapter or collection permission. Simplify form assistance is rejected before inspection. LinkedIn collection, private endpoints, session scraping, account rotation and bot bypass were not used.

Actual local Chromium verifies native text/textarea/select/radio/checkbox behavior, existing-value preservation, stale document/option races, one-shot authorization, cancellation, React-controlled state, manual sensitive/legal controls and zero unintended form POSTs. The dashboard engine additionally verifies bounded custom dropdowns, explicit multi-page review, manual server steps, canonical PDF/digest attachment validation and recovery after process loss. The extension leaves uploads or framework widgets manual where safe handling is not established.

Seven fixture URLs reproduce recognizable Greenhouse, global Lever, Ashby, SmartRecruiters, Workday, generic HTML and Google Forms shapes as defined by the fixture. EU Lever URL/identity guards have separate backend coverage. The seven DOM cases use intercepted fictional markup; they do not recreate whole live vendor frontends. MV3/native lifecycle coverage is also fictional and verifies URL preview/session observation and transport recovery. Its receipt explicitly records `form_fields_read:false` and `form_fields_filled:false`; the real DOM/React filling proofs come from separate Chromium suites. A complete physical-toolbar-to-native-host form-fill gesture remains unverified; preparation/authorization guards have separate backend/unit coverage. **No genuine Workday/Taleo/Simplify/employer workflow, physical toolbar grant, live employer autofill or submission is claimed.** URL eligibility is never automation permission.

## Gmail: implemented route, tested limits, live readiness

`POST /api/v1/integrations/gmail/accounts/{account_id}/sync` **already exists**. It synchronizes selected job-related evidence into local account-isolated storage; it does not synchronize or mutate an entire mailbox and does not import every message as a confirmed vacancy.

It requires owner API authentication, the staged schema, an independently connected read account, exact read-only scopes, verified account identity, enabled runtime/policy and a curated sender/label selection. Metadata-only reads require an explicit custom label and cannot use Gmail `q`. Selected body reads additionally require the reviewed body-access flag, appropriate independent scope and a stated purpose.

Processing is bounded to 25 messages/page, one–three pages, a 1–30-day backfill, 1–90-day retention and a 90-second operation timeout. Per-account/message identities, token generations, versioned policies, leases/checkpoints/page cursors, duplicate detection and retry/recovery tests prevent cross-account leakage, stale-selection continuation and blind replay. Retained evidence does not store raw bodies, subjects or sender addresses. Body keyword signals remain tentative, not confirmed employer status or proof of application.

A fresh read-only inspection of the actual target found:

- Read-only account schema: **absent**; restricted runtime/catalog boundary verified; **zero DDL**.
- `GMAIL_READ_SYNC_ENABLED=false`; `GMAIL_READ_BODY_REVIEWED=false`.
- Rendered `public` forward SQL SHA-256: `e61d2e23fb27991715e2689cda14273d11abf4aac04e71babaf8ef4f5c434ebd`.
- **Zero live OAuth flows, token refreshes, Gmail message reads, mailbox writes or sends.** Legacy compose authority was not reused.

The sanitized [readiness receipt](gmail-readiness.json) and [existing exact operator procedure](../phase3/phase35-gmail-operator.md) identify the separate gates. Owner actions are approval of that exact target/rendered migration with backup/recovery and writer coordination, then independent consent for each account and its scope/selection/retention; body access requires its separate review. A maintenance operator must recheck the catalog and target before approved DDL. Do not elevate the runtime role or apply a partial/drifting install.

## Failed-run accounting and publication

The first complete combined backend run passed **2,605 tests** before the final query optimization; it is baseline evidence, not the final backend total. The query-budget regression intentionally failed before the fix, then passed with 15 focused identity/ingestion cases. The first combined frontend run had 196 passes and one outdated message-wide import fixture assertion; the fixture was corrected to the URL-specific contract and the complete suite rerun.

The initial dashboard browser run had eight passes, three failures and one unrun successor: one provider-error rendering assertion timed out, and two subsequent logins exposed the actual pre-hydration GET defect. No pass is claimed for that run. After the guarded login change and frozen production rebuild, all 13 dashboard journeys passed, including error recovery and the additional scripts-unavailable regression. Both full PostgreSQL browser journeys were rerun on the final frontend; the final 19 passed. Tests were not changed to accept invented answers, submitted employers or cross-account imports. Secret scanning flagged nonsecret migration/Git checksums in JSON receipts. Those redundant JSON fields were removed; the exact checksums remain in this report and the private originals. The complete scan then passed with no secret-baseline expansion.

The single [publishable PR body](integration-pr.md) describes this actual integrated engineering result. PR #39 remains open. Publication order is owner review/merge of #39, publication/review/merge of the ready Phase 3.5 integration prerequisite, reconciliation of actual main while preserving this candidate's histories, then publication of this Phase 4 branch. Rerun checks affected by any reconciled source change. No prerequisite is auto-merged and no hosted job is dispatched.

Remaining external blockers are exact Gmail migration/account consent, reviewed rights/current free-credit/budget authorization for optional Apify/Apollo collection, genuine permitted applicant-site/physical gesture acceptance, and publication prerequisites. No provider entitlement, suitable vacancy, live timeout resolution or general vendor compatibility is inferred from the local engineering pass.
