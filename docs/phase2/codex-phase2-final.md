# Phase 2 engineering and live acceptance — 2026-10-27

**ENGINEERING: INCOMPLETE. LIVE: BLOCKED.** The backend/extension implementation candidate is committed locally. Mandatory final PostgreSQL/browser/full-regression and combined frontend acceptance remain outstanding because the owner instructed Codex to wait for AGY's explicit heavy-test pause confirmation. That confirmation has not arrived. Earlier tests, fictional data and source review do not establish final integrated or live acceptance.

## Identity and ownership

- Branch: `feat/phase2-final-codex-engine`.
- Implementation SHA: `3ec8239348270c96454268a4b38b744447d5e8c2`.
- Base: exact reviewed PR #35 head `02bfb83a89f5e13f72a533aed87410b7e0a47d21`.
- Existing worktree: `/Users/karanagg/Desktop/Projects/automated-apply-codex-p22`. It was clean before the new branch was created. The original PR #35 branch is preserved.
- Delivery documentation is a subsequent local commit; the final delivery SHA is recorded in the delivery response and private manifest. No application code may differ from the implementation SHA without rerunning relevant checks.
- No push, new PR, merge, deployment, hosted Actions dispatch/rerun, billing change, migration, installed configuration change or extension permission change occurred. No new PR link exists. PRs #35/#36 remain subject to the owner's integration instructions.
- No frontend or AGY-owned file was edited. Read-only inspection found AGY's local `feat/phase2-final-agy-ui` at `08f795994ef4bec662395d42b9115c3bbfb8a3df`, newer than published #36 `0c274a372e50f94743cf6334a09588253e5bb473`. Its final test results are not confirmed.

## Acceptance inventory

| Area | Disposition | Evidence / remaining condition |
| --- | --- | --- |
| Free source registry, allowlists, fixed-host GET, normalized provenance | PASS targeted; live BLOCKED | Existing Lever/Ashby work retained; adapter/security tests pass; no employer board approved for a new live request |
| Ingestion/deduplication/preference matching | PASS targeted; final PostgreSQL PENDING | Existing locks, savepoints, idempotency, saved observations and profile-version ranking retained |
| Historical 27-listing timeout | PARTIAL | No historical phase trace establishes its cause; refreshed final latency experiments await the test window |
| Genuine source to packet | Implemented; fictional targeted PASS | Lever/Ashby were missing from packet platform registration. Existing public-listing adapter now supports their reviewed handoff destinations with same-board/job/host checks. No live packet created. |
| Profile, canonical resume, factual mapping | PASS targeted | Existing confirmed resources/version binding; selected canonical resume tested with fictional fixtures |
| Answer generation and approved Q&A reuse | PASS targeted | Deterministic-first extraction, reviewed bank, strict missing-fact behavior, topic/limit checks and optional provider gates |
| Owner review and durable packet mutation | PASS targeted; final PostgreSQL PENDING | API acknowledges after commit; failed commit returns 503. Revision archives preserve superseded human answers and resume snapshots in the existing private store. |
| Chrome extension/common form contracts | PARTIAL final acceptance | Existing native capability gates retained; new races/value/destination/completion guards implemented. Final real-browser rerun is blocked by the coordinated test-window hold. |
| Dedicated backend browser | PARTIAL final acceptance | Existing-value and destination-signature defects fixed; three actual Chromium regressions passed before subsequent changes. Final browser suite still required. |
| Dynamic/multi-step/reactive controls | Supported subset only | Existing dedicated-browser native/specific ARIA and in-page step contracts retained; changed structure, network-dependent steps, ambiguous widgets and unsupported controls require fresh analysis or manual takeover |
| Submission/status/recovery | PASS targeted; final recovery PENDING | Fill remains separate from submission; owner report and provider evidence remain distinct; ambiguous dispatch is never blindly replayed |
| Telegram | Mock targeted PASS; live BLOCKED | Private owner authentication, durable queue, 429 retry and restart/ambiguous-send behavior tested with fake Bot API; no real-send approval |
| Frontend/API compatibility | PARTIAL | Typed OpenAPI unchanged; AGY source review found specific UI corrections below; no combined build/E2E result |
| Full final candidate regression | NOT RUN / BLOCKED | Await explicit AGY pause confirmation, process check and atomic shared-lock acquisition |
| Genuine discovery → suitability → new packet → Chrome fill → restart | BLOCKED | Exact live source/database/profile/resume/destination permissions are missing; suitability has not been evaluated from new live evidence |

## Implemented behavior

The existing discovery, packet, answer and browser architecture is reused. No parallel application engine or browser framework was introduced.

1. Lever/Ashby discovery can now produce reviewable packets through `PublicListingPlatform`. The same ATS URL validator used by ingestion is reused for packet destinations. Switching board, posting ID, global/EU host, query redirect or employer domain invalidates handoff. This grants neither browser access nor submission permission. Ashby/Lever EU packet preparation does not imply that the manual extension has a verified fill adapter for those pages.
2. Discovery diagnostics distinguish durable provider pacing from adapter handling and accumulate repeated phase segments. Public transport records request/retry-wait, JSON decoding and normalization durations, attempts and decoded byte counts. ATS normalization is measured in its own parser loop. Final audit, ingestion and matching remain bounded; commit acknowledgement emits only opaque run ID and monotonic seconds. Nested timings overlap. Commit acknowledgement cannot be persisted inside the transaction it acknowledges, and is absent when acknowledgement is lost.
3. The extension rechecks its complete document/control/form-destination snapshot before every write and between reactive input/change events. It preserves initial and newly changed values in both manual and separate-worker modes. It consumes each DOM snapshot once, guards uploads against changed destinations/existing files, checks required fields after fill/upload, and rechecks the active page before recording completion. Native authorization must identify the originally reviewed plan/destination/document. Partial field success remains `needs_input`; no receipt becomes a submission.
4. The dedicated browser's signature now includes form destination/method/target/encoding. Existing text, selections, radio/checkbox groups and files are preserved instead of overwritten. Preserved answers are reported for owner website review and excluded from filled-field IDs. Existing per-field fresh inspection, network isolation, cancellation and durable interrupted intent remain in place.
5. Server-side field policy also rejects sensitive/self-identification and attestation labels in untrusted native inspections. A forged neutral group label cannot turn an email fact into consent. Ordinary checkbox/radio mapping no longer invents a negative value for an unmatched option. Passwords, OTP/MFA, payment/bank data, IDs, self-identification, legal attestations and unknown consent remain manual.
6. Grounded extraction selects evidence covering all requested topics and rejects constraints that would remove one. A question about a bug that was fixed requires both challenge and actual solution evidence. API integration requires personally attributable work rather than a skills list. No model supplies missing facts.
7. A reproduced API rewrite deadlock on a one-slot PostgreSQL pool is fixed by releasing the dedicated API's read transaction before independent quota/provider work, then checking a private profile/evidence/project/job fingerprint before saving. Packet revision/context is checked again and its field reloaded. Embedded callers retain transaction ownership; the read-release mode rejects staged ORM changes/nested transactions instead of committing them. The Phase 2 agent/form paths remain deterministic. This does not claim to redesign unrelated Phase 3 transaction orchestration.
8. Packet create/edit/questions/generation/review/report/tracking endpoints commit before acknowledging success. Before replacing a packet revision, the existing private `owner_preferences` store retains the old fields, human edits, review state, resume/context snapshot, UTC timestamp and digest under `packet_revision:{packet_id}:{revision}`. No archive is overwritten by a subsequent revision. Minimal historical schemas without that existing table retain legacy behavior and do not gain archive storage. Historical archives currently require authenticated operator database inspection; no frontend history API/UI was added.
9. Gemini now independently requires `GEMINI_CANDIDATE_DATA_AUTHORIZED`, default false, in both factory and transport. A key, enablement and budget alone cannot transmit candidate facts. This declaration changes source/.env.example only; no real runtime consent was enabled. Existing Cohere production/evaluation gates, explicit local fallback, budgets and unavailable-provider behavior remain intact.
10. Telegram `/jobs` reads the latest saved audit without running discovery, distinguishes empty history and failed/incomplete searches, and makes no suitability claim. Prepared campaigns include the exact saved packet reference. Existing one-owner/private-chat authentication, offset/outbox idempotency and no replay of ambiguous `sending` records remain intact.

## Local verification and evidence boundaries

All profiles, projects, PDFs, employers, jobs, packets, Bot API responses and browser pages used by this task were fictional. Pytest's existing HTTP-denial fixture prevented account/provider traffic; explicit mock transports handled feeds. Chromium used task-created profiles/intercepted fictional pages or loopback fixtures. Installed owner Chrome and its extension registration were not changed.

| Check | Result |
| --- | --- |
| Final implementation lightweight packet/answer/form/Telegram/ATS batch | 405 passed, zero failures/skips; 38.35 s, implementation SHA 3ec8239 |
| Additional discovery/deduplication/registry/database-safety/security unit batch | 105 passed; 6.88 s |
| Explicit API-integration/bug evidence, factual salary/notice, mapping and narrative grammar matrix | 63 passed; 5.01 s; overlaps the main batch |
| Operations/agent/private-owner mock batch during implementation | 189 passed; 17.83 s in the expanded operations/agent/private-owner/pairing/budget batch; includes overlapping tests |
| Extension unit/native-protocol suite | 44 passed, zero failures/skips; 7.22 s on committed implementation 3ec8239, also recorded in the private manifest |
| Extension build | Passed; stable ID `gdjbmkffcpicbpiikcohlmokkmcpipgp`; no manifest permission change or installation |
| Actual Chromium preservation/destination tests during implementation | 3 passed; 16.84 s; before later changes, not final-candidate proof |
| Actual Chromium DOM race regression during implementation | Original code reproduced false `form_filled` after a handler changed destination; revised intermediate implementation passed 8 cases, zero external requests/submissions |
| New final Chromium race/upload/self-identification cases | Authored; final execution held for AGY confirmation; not represented as passed |
| One-connection PostgreSQL optional-rewrite regression during implementation | Original failed with QueuePool size 1/overflow 0 at 2 s; corrected API boundary passed one case in 1.71 s before later changes |
| New combined PostgreSQL discovery/answer/review/handoff/restart/report journeys | Authored and collected for Lever and Ashby; not yet executed on final implementation |
| Full final backend suite / PostgreSQL 17 / recovery/latency benchmarks | NOT RUN at final implementation; blocked by test-window hold |
| Final frontend unit/build/Playwright/combined E2E | NOT RUN here; no confirmed AGY results or authorized combined candidate |
| Ruff E9/F/I, Python compilation, full-app Bandit, diff checks | Changed modules pass; conftest.py retains the same three pre-existing I001 import-order findings as the base; compilation/Bandit/diff checks pass |
| Native secret hook over tracked/new sources | Passed with unchanged policy/baseline and unchanged secret hashes |
| Typed API schema | Identical to saved baseline; compact canonical JSON 244,960 bytes, SHA-256 `026df66cd01740f9deb2c890583bd8e6c3769c3330e9a12067b1fb2a9f9b06d9` |

Counts above are per invocation and overlap; do not add them into a unique-test total or call them a full suite. Prior PR #35 full-suite and latency results remain historical and do not prove this changed implementation passed. Early commands referencing nonexistent Telegram/matcher test filenames collected no tests and were corrected. The initial extension invocation lacked a dependency-capable Python path; explicitly using the existing venv resolved that without dependency installation. A first fingerprint prototype attempted a deferred ORM attribute; it was corrected to fingerprint the public loaded profile contract and subsequently passed. These are recorded development failures, not passing checks.

The secret hook briefly refreshed baseline line metadata automatically. The original file was restored, and test environment setup was expressed without shifting those reviewed lines. The final native hook passes without a baseline edit, changed hashes or weakened detector settings.

Private machine evidence: `/tmp/automated-apply-phase2-final-evidence`. It is excluded from commits. It includes JUnit receipts, canonical OpenAPI, static/secret-check output and the final local manifest. No private acceptance data was generated or committed.

## PostgreSQL timeout/recovery/idempotency assessment

The historical online Greenhouse 27-listing timeout still has **no confirmed root cause**. No phase trace survived that run, and no new live reproduction was authorized. The prior PR #35 round-trip reduction and 50 ms/statement sensitivity model support database round trips as a hypothesis. They do not establish the historical cause or demonstrate an online repair. The newly reproduced answer-quota pool deadlock is a separate confirmed defect; it is not evidence about the Greenhouse timeout.

A new disposable `postgres:17-alpine` fixture, `codex-phase2-final-pg17`, was created on loopback port 55437 with an empty `candidate_profile_test` database. The existing test fixture creates/drops unique databases and uses pool size 1/max overflow 0. Restart testing is restricted to the explicit fixture-name/port pairs. No installed PostgreSQL/Supabase instance was restarted or altered. Full final restart/disconnect/concurrent claims/commit-acknowledgement/27-listing latency checks remain pending the shared test window. No timeout was increased and no ingestion concurrency or connection budget was expanded.

Same-key discovery returns its saved audit without a new provider call. Packet uniqueness/revision checks and owner-report replay preserve state. Existing ambiguous external submission evidence remains `submission_unknown`, with no blind retry. Final PostgreSQL evidence for the combined changed candidate is still required.

## Grounded answer evaluation

| Question / condition | Fictional result |
| --- | --- |
| Why join this company? | Reuse only a current explicitly approved same-job answer; absent approved interest/opportunity facts remains manual. No invented enthusiasm/company familiarity. |
| Describe your best project | Extract actual approved first-person contribution with references; requires review |
| Hardest bug fixed | Include approved challenge and solution; missing solution abstains |
| Which API integrated? | Quote the personally attributable approved integration; a skills list or unrelated project abstains |
| Expected salary / notice period | Exact approved compensation kind/currency/period and notice only; no salary inferred from search minimum; unsupported compound labels remain manual |
| Other job-specific written questions | Existing classifier/retrieval/provider contracts; unsupported questions remain manual |
| Word/character limits | Reject unsupported shortening or omitted requested topics; no truncation of factual values/URLs |
| Prompt injection / invented projects/metrics | Untrusted job/page data cannot establish candidate facts or permissions; conservative output rejection plus mandatory owner narrative review |
| Local provider unavailable / rate limited | Clear unavailable/manual state; no silent remote fallback, invented response or automatic 429 retry |

No real local model, Cohere or Gemini request was executed for this acceptance. Generative grounding guards are conservative checks rather than a general semantic proof; human review remains mandatory before insertion.

## Security and permissions audit

No live Lever/Ashby board, protected portal, paid actor, online database, installed browser permission or unattended schedule was activated. Source allowlists still default empty. LinkedIn remains reference/discovery/manual-only. No recruiter email, Gmail, LinkedIn message or real employer submission was sent. Telegram delivery remains blocked, and mocked messages are not delivery evidence.

Native/REST owner authorization and expiring one-use plans remain intact. Values and private resume bytes are not added to operational logs; fill receipts contain only identifiers/status. New diagnostics log only bounded timings/opaque run ID. Revision archives are private candidate records in the existing owner store, not public telemetry. The application is an authenticated single-owner system; this does not claim multi-tenant support. Final restricted-role/RLS and restart suites are pending, rather than inferred from unit authorization checks.

Default review remains on. No real execution adapter or unattended-submission enablement was added. Fixture-only loopback submit/receipt tests, when later run, must remain separately identified as fictional.

## AGY/frontend coordination and remaining integration findings

The owner was asked to relay a 25–35-minute pause request. The owner repeatedly confirmed that AGY's pause was **not yet confirmed** and explicitly instructed lightweight work only. No heavy-testing lock was acquired, no other process was interrupted, and no other agent's lock/file was deleted. A quiet process listing is not substituted for the required explicit confirmation.

Read-only review of local AGY `08f7959` found existing endpoint/typed payload compatibility and these corrections for AGY:

- Dedicated backend browser supports the approved encrypted canonical PDF contract; only the manual extension leaves file attachment manual. Its blanket no-upload wording is inaccurate.
- Existing answers are preserved; there is no overwrite option to describe as “explicitly reviewed for overwrite.”
- An ambiguous submission attempt must be reconciled through that attempt; the tracker rejects a new manual report until then.
- API/technical narratives use packet category `experience`, which the current generation-button category list omits.
- Backend enforces `max_words`; the new counter currently checks only `max_characters`.

Codex did not edit these frontend files. AGY build/unit/Playwright results and fixes must be reviewed on its actual final SHA. After separately approved #35/#36 merges, fetch actual main, preserve both histories, integrate/rebase locally, regenerate/check contracts as needed and run the combined candidate. No merge/publication approval is inferred here.

## Exact remaining permissions and completion gates

1. AGY's explicit heavy-test pause confirmation; then inspect terminal processes, acquire `/tmp/automated-apply-heavy-tests.lock` atomically with `fcntl.flock`, run PostgreSQL/backend/browser suites sequentially, release on all exit paths and notify AGY. Final full regression must name the actual tested final SHA; changed code invalidates earlier evidence.
2. Actual final AGY SHA and its test results, correction of the UI findings above, and separately approved earlier-PR integration before publication of a final backend/extension PR.
3. Exact owner-approved Lever/Ashby boards, employer identity/official-page evidence, read permission and request scope. A future approved check remains one board/provider, three selected jobs/board and eight total HTTP attempts including retries/re-observation; no checks are activated merely by this task.
4. Exact existing Supabase project/schema/restricted identity, approved profile/version/eligibility and canonical resume resource, and explicit write scope for discovery/observations/rankings and at most one suitable new draft packet. Credentials must stay in existing approved private configuration.
5. Exact permitted Chrome destination/platform permission, selected packet and explicit owner review/fill approval. No real external application submission is authorized.
6. Separate real Telegram-send permission for the existing bound private bot/chat before delivery acceptance. No real-send attempt occurred.

No source suitability determination was made because live checks were not authorized. This is a permission blocker, not evidence that no suitable jobs exist. Fictional listings are never presented as genuine opportunities.

## Recovery and cleanup

Use the existing Codex worktree/branch for continuation; no additional clone/worktree was created. The original checkout, PR #35 branch, AGY files, secret baseline and manual-only workflows are preserved. Dependency use is limited to the existing Python 3.11 venv, pnpm and existing Playwright packages; no model or package dependency was installed.

The task-created PostgreSQL fixture was stopped and removed after lightweight work; the final manifest records that cleanup. Recreate only a dedicated loopback fixture after the heavy-test window is confirmed. Only that exact task-created container may be cleaned up. Existing containers/images/services and owner data must be preserved. Temporary Chromium profiles are cleaned up by their fixtures. Private test receipts remain under the task's `/tmp` evidence directory; they can be removed after review without affecting application data. Never delete the shared lock pathname; release only a lock held by this process.

## Exact changed files

```text
backend/.env.example
backend/app/agent/executor.py
backend/app/ai/evidence.py
backend/app/ai/provider_factory.py
backend/app/ai/providers/gemini.py
backend/app/api/v1/application_answers.py
backend/app/api/v1/applications.py
backend/app/browser/dom.js
backend/app/browser/driver.mjs
backend/app/browser/field_policy.py
backend/app/browser/runner.py
backend/app/browser/service.py
backend/app/core/config.py
backend/app/local_agent/telegram.py
backend/app/repositories/application_packet.py
backend/app/services/application_answer_service.py
backend/app/services/applications/platforms/public_listing.py
backend/app/services/applications/service.py
backend/app/services/candidate_evidence_retrieval.py
backend/app/services/job_discovery_service.py
backend/app/services/job_sources/direct_api.py
backend/app/services/job_sources/public_ats.py
backend/tests/conftest.py
backend/tests/test_answer_topic_coverage.py
backend/tests/test_answer_transaction_boundary.py
backend/tests/test_browser_preservation.py
backend/tests/test_discovery_phase_timings.py
backend/tests/test_form_field_policy.py
backend/tests/test_llm_provider.py
backend/tests/test_packet_revision_history.py
backend/tests/test_phase2_final_postgres.py
backend/tests/test_phase2_telegram.py
backend/tests/test_public_ats_packets.py
backend/tests/test_public_ats_postgres.py
docs/phase2/codex-phase2-contract.md
docs/phase2/codex-phase2-final.md
extension/form-bridge.js
extension/form-dom.js
extension/tests/fill-races.browser.mjs
extension/tests/form-bridge.test.mjs
```
