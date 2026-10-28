# Phase 3.5 final integration — preparation report

## Final publication dependency recheck — 2026-10-28

**ENGINEERING: BLOCKED / NOT EVALUATED on combined source. LIVE ACCEPTANCE: BLOCKED.** This section supersedes the source pins and pending-work status in the historical preparation record below. It does not replace its test receipts or failed-run history.

GitHub PR #39 remains **OPEN and unmerged**, with expected head `e57178b22e453119f4ba449dae28f36c01b6edc5`, no recorded reviews, `mergedAt: null` and no actual merge commit. Both GitHub CLI and the GitHub connector confirmed that it is unmerged. The connector's non-null `merge_commit_sha` on this open PR is a synthetic mergeability commit, not an actual main merge. Remote `refs/heads/main` is currently `ec5dc9b26363b762b4fa508e6d17583741101a5b`, verified with `git ls-remote`; it is the Phase 2 merge and must not be reported as the PR #39 merge.

The exact dependency is owner review/approval and merge of [PR #39](https://github.com/karanagg166/automated-apply/pull/39). This task did not merge it. **Actual Phase 3 main merge SHA: unavailable. Final Phase 3.5 integration branch/SHA: not created. Final Phase 3.5 integration PR: not published.**

Only a documentation handoff was prepared in a new linked worktree of the original repository:

- Branch: `prep/phase35-final-handoff-20261028`.
- Worktree: `/Users/karanagg/Desktop/Projects/automated-apply-phase35-handoff-20261028`.
- Starting commit: `ae84afc1b72f3dda44de50026a56aa962698ae77`.
- Exclusive change: this report. No backend, frontend, extension, migration, configuration or workflow modification.

All existing branches/worktrees remain preserved. No final integration, clone, push, force-push, hosted workflow, deployment or live activation occurred. No message was sent to AGY; no heavy suite was started, so there was no new heavy-test lock acquisition or competing test run. Post-merge work must coordinate the shared lock with AGY before running suites.

### Exact source pins and history preservation

| Source | Exact current commit | Verified ancestry |
| --- | --- | --- |
| Codex implementation | `e84e45bf70a62871d04c0fd3c147c4df50e400fb` | Contains PR #39 head |
| Codex preflight | `ae84afc1b72f3dda44de50026a56aa962698ae77` | Contains full Codex implementation and Gmail fix `709c814ea3062338f8cc8a4cc620a4e7d2facaba` |
| AGY final delivery | `63dd23eb82feb0e149fb7c42827fc402b38c6d92` | Contains PR #39 head and original AGY commit `08a065fce9d9c744e9c3f252025f8f5833620808`; diverges from preflight at PR #39 head |

AGY's final review document embeds the older SHA `cbfa7db92c9402cdbf900bf65302ad5fda884113`. The delivered Git commit is **63dd23eb82feb0e149fb7c42827fc402b38c6d92**, as required by the owner. Preserve that exact commit and all of its changes in final integration. Compared with the originally reviewed AGY commit, it changes seven frontend feature files, the Phase 3 browser journey file and adds its final review report. It retains the filter reset, OAuth scope labels, disabled-action explanations, Actor inspection retry, profile conflict handling, packet refresh and non-submission UI changes. None was discarded or overwritten during this recheck.

| Source component | Git tree object |
| --- | --- |
| Codex backend | `028100a853a6067bc93e900030ad19aa57b9cdd3` |
| Preflight backend, including Gmail persistence fix | `7f0a88f16560e5cc76d35f1a58b5a9742ccaf427` |
| Codex/preflight extension | `ca50b760762170d7e5b288cf6dd49dfd601e77d4` |
| AGY final frontend | `bd9b076720254bedc53c445b1dd7f8dd8566cad6` |

Pinned preflight SHA-256 checksums:

- `backend/app/integrations/gmail/read_service.py`: `2120e0198b025aafbf6e37649be4db4632702192ac681536d7056afbbe7a59c1`.
- `backend/tests/test_phase35_gmail_import_recovery.py`: `2968889bdb837902dbc1a215898cf9096c470f94cc5b30b30ea11d43672814bc`.

After the dependency opens, fetch actual main, record the actual PR merge and current main SHAs, and repeat ancestry checks against that baseline. Create the one final integration branch/worktree there and merge the pinned histories with history-preserving merge commits. Verify all three pinned heads are ancestors of the final candidate. The new handoff branch contains the original preflight history and this report; preserve it too. If GitHub used squash/rebase merging, explicitly reconcile baseline contents and history rather than assuming ancestry. Keep primary checkout and agent worktrees intact.

### Source findings still present in AGY's exact final commit

These findings were rechecked against `63dd23eb82feb0e149fb7c42827fc402b38c6d92`; they require coordinated resolution and regression verification before combined acceptance:

| Finding | Current evidence and required acceptance |
| --- | --- |
| Startup sorting | `startups.tsx` sorts only `result.data.startups`, after pagination. Implement global sorting or explicitly label page-only behavior and verify multiple pages. |
| Actor configuration attribution | `apify-sources.tsx` compares source portal IDs to Actor IDs with equality/substring checks. Use a reviewed explicit mapping or show unknown association; metadata must never grant collection rights. |
| Gmail import result | `connected-emails.tsx` retains `inserted_count || 1`, and message-level `imported_job_ids` control duplicate badges. Preserve the preflight backend 409 fix; display exact validated ingestion counts and test individual URL identity in multi-link messages. |
| Browser fill status | `browser-assistant.tsx` still checks unsupported lifecycle strings `filled` / `manual_submission_required` and submission execution completion for a fill badge. The unit fixture still casts `lifecycle_state: "filled"` through `as any`. Bind the badge to actual current fill analysis/receipts, preserve cancellation/freshness and test valid contract fixtures. |

AGY reports 183 Vitest tests, production build/typecheck/formatting, five Phase 3 Chromium journeys and twelve browser journeys. These are historical AGY branch claims, not a fresh combined acceptance result. Its five Phase 3 journeys do not by themselves establish every owner-required critical check, including 2–10 employees, browser-bound OAuth cookies/scopes, missing profile preconditions (428), failed-persistence frontend recovery, refresh/restart durability or MV3 recovery.

### Current verification accounting and remaining sequence

No engineering suite ran in this dependency recheck: **0 test cases executed, 0 fresh passing cases, 0 fresh failed cases; no runner skip total exists**. All requested combined suites remain **NOT RUN / dependency-blocked**, not passed or counted as skipped test cases. Historical 83-case preparation, 30 HTTP assertions and all original failures remain below unchanged. There is no new security/dependency audit, running API acceptance or Chromium result for combined source.

Documentation validation passed `git diff --check`, exclusive-report-change verification, exact pinned-ref and baseline-ancestry assertions, and manual-only trigger checks for all three workflow files. Source-branch workflows are unchanged from PR #39. These are preparation checks, not engineering test-suite totals.

The post-merge sequence below remains required under atomic locking at `/tmp/automated-apply-heavy-tests.lock`, preserving the existing inode and every failure receipt. Record exact implementation SHA, backend/frontend/extension tree hashes, fixture/runtime identity and commands before testing. Run heavy suites sequentially and handle harness-owned locks without nested deadlock. Resolve source findings before the full run; rerun affected checks if source changes afterward.

Combined acceptance must explicitly cover all owner-required cases: failed Gmail persistence; two-account isolation; denied send/modify/delete/archive; browser-bound OAuth cookies and scope denials; durable NEEDS_INPUT after refresh/restart; factual save before separate human approval; exact evidence/context reuse and stale invalidation; profile 409/428; startup 2–10 and 11–50; metadata without collection rights; provider-reported contacts remaining unverified; preserved form values with zero automatic submission; React DOM races and MV3 restart recovery. Use actual FastAPI, disposable PostgreSQL and the production-built frontend, distinguishing fictional provider/employer transports from genuine live acceptance.

### Outstanding operator gates

The detailed Gmail SQL hashes, staged migration/recovery/consent plan and provider findings below remain historical preparation evidence. No live inventory, provider pricing, allowance, credential or consent was refreshed in this recheck; revalidate them at their own approval gate.

| Gate | Concrete operator action before execution |
| --- | --- |
| Phase 3 baseline | Review and merge PR #39 if approved; independently verify GitHub merged state before final integration. |
| Live Supabase DDL | Confirm exact target/schema, backup and recovery rehearsal, maintenance identity/window, stopped writers and current catalog preflight. Review the rendered forward SQL/hash and separately approve only that transaction; verify forced RLS and restricted runtime grants afterward. No runtime privilege elevation. |
| Deployment/runtime | After combined engineering acceptance and final PR review, separately approve the exact runtime/extension artifact, target and rollback artifact; perform readiness checks before enabling workers. PR merge alone is insufficient. |
| Each Gmail account/read | Resolve restricted-scope and retention readiness, confirm schema, then separately consent each account and scope. Approve curated label/sender selection and bounded initial metadata sync; inspect attribution, retries, expiry and zero mailbox mutations before adding another account or body scope. Legacy compose consent is insufficient. |
| Apify Actor execution | Verify source rights, exact Actor/input/pricing/current account allowance and explicit run/result/cost limits. Obtain bounded execution approval separately; metadata access alone grants no collection permission. Do not rotate accounts or use personal LinkedIn cookies. |
| Apollo lookup | Owner supplies an eligible credential privately; verify endpoint rights and actual credit pool, then separately approve a bounded lookup and budget. Provider-reported contact data stays unverified without independent evidence. |
| Genuine employer acceptance | Owner selects the exact vacancy/destination and explicitly authorizes the fill gesture after reviewing evidence. Observe preservation/no automatic submission. Any application submission requires its own explicit authorization; no Gmail/LinkedIn message is automatically sent. |
| Hosted GitHub Actions | Keep all three workflows manual-only. No dispatch or rerun without deliberate owner authorization. |

Publish exactly one Phase 3.5 integration PR only after the dependency, source findings and full combined local checks pass. Report ENGINEERING PASS only for that tested combined candidate; retain genuine live acceptance gaps separately. Do not automatically merge or deploy it.

## Historical preflight record at ae84afc

Observed 2026-10-28. **ENGINEERING: FAIL** (final acceptance gate unmet; no combined candidate tested). **LIVE ACCEPTANCE: BLOCKED**. Successful preparation checks below do not establish either final engineering acceptance or live activation.

## Baseline gate and provenance

[PR #39](https://github.com/karanagg166/automated-apply/pull/39) was checked through GitHub before work: `OPEN`, `mergedAt: null`, `mergeCommit: null`, head `e57178b22e453119f4ba449dae28f36c01b6edc5`, base `main`. The required owner-approved merge has not occurred. No final integration branch, dependent PR, push, merge, deployment or hosted workflow was performed. Actual main merge SHA and final integrated SHA are therefore **not available**.

| Source | Verified commit | Relationship |
| --- | --- | --- |
| Phase 3 baseline / PR #39 | `e57178b22e453119f4ba449dae28f36c01b6edc5` | Common ancestor of both Phase 3.5 branches |
| `feat/phase35-codex-activation` | `e84e45bf70a62871d04c0fd3c147c4df50e400fb` | Three commits above baseline: `3a22b6f`, `f2613ce`, `e84e45b` |
| `feat/phase35-agy-ui-hardening` | `08a065fce9d9c744e9c3f252025f8f5833620808` | One commit above baseline |
| Preparation fix / tested implementation | `709c814ea3062338f8cc8a4cc620a4e7d2facaba` | Child of the complete Codex history; no AGY merge |

Both supplied agent worktrees were clean at inspection. They share the primary repository's `.git`; no clone was created. Primary checkout remained on `integration/phase2-combined-20261027` at `e08b7f0c6c961b0228eddfd70dabb8dbb4c63a88`. Agent branches and private configuration were untouched.

Safe preparation uses linked worktree `/Users/karanagg/Desktop/Projects/automated-apply-phase35-preflight-20261028`, branch `prep/phase35-final-preflight-20261028`. This is **not** the final integration candidate. The requested `integration/phase35-final-20261028` branch remains reserved for the verified post-merge baseline.

Exact tested source tree objects:

| Tree | Git object |
| --- | --- |
| Preparation backend | `7f0a88f16560e5cc76d35f1a58b5a9742ccaf427` |
| Codex/preparation extension | `ca50b760762170d7e5b288cf6dd49dfd601e77d4` |
| Preparation frontend (Phase 3 baseline, not AGY) | `91a20cf1bf2bc6719c24548f330fd0fd93f2217b` |
| Reviewed AGY frontend | `c9d2c310331297ffaee262f4fa2038bd49126891` |

The subsequent report-only commit changes no tested backend, extension or frontend source tree. AGY's existing report names an older final SHA and lists 15 files; Git establishes the actual delivered SHA above and 14 changed files. Original branch test totals remain historical branch evidence, not combined results.

## Exact changed files

Codex Phase 3.5 versus the common baseline (17):

```text
backend/app/browser/driver.mjs
backend/app/integrations/gmail/schema.py
backend/app/integrations/gmail/schema_checksum.py
backend/app/repositories/job.py
backend/app/services/job_discovery_service.py
backend/scripts/benchmark_discovery.py
backend/scripts/migrations/phase35_gmail_readonly_rollback.review.sql
backend/scripts/migrations/phase3_gmail_readonly.review.sql
backend/scripts/phase35_runtime_audit.py
backend/scripts/verify_phase3_integrations_postgres.py
backend/tests/test_discovery_phase_timings.py
backend/tests/test_public_ats_postgres.py
docs/phase3/activation-codex.md
extension/form-dom.js
extension/tests/fill-races.browser.mjs
extension/tests/form-bridge.test.mjs
extension/tests/react-forms.browser.mjs
```

AGY Phase 3.5 versus the common baseline (14):

```text
docs/phase3/activation-agy.md
frontend/src/features/apify-sources.tsx
frontend/src/features/applications.tsx
frontend/src/features/browser-assistant.tsx
frontend/src/features/candidate-knowledge.tsx
frontend/src/features/connected-emails.tsx
frontend/src/features/startups.tsx
frontend/src/features/unanswered-questions.tsx
frontend/tests/applications.test.tsx
frontend/tests/browser-assistant-improvements.test.tsx
frontend/tests/candidate-knowledge.test.tsx
frontend/tests/connected-emails.test.tsx
frontend/tests/startup-filters.test.tsx
frontend/tests/unanswered-questions.test.tsx
```

Preparation-only changes (three files including this report):

```text
backend/app/integrations/gmail/read_service.py
backend/tests/test_phase35_gmail_import_recovery.py
docs/phase3/phase35-final-integration.md
```

The two original branch file sets do not overlap. This is an ancestry/file review, not a claim that a merge or its runtime behavior has passed.

## Defect fixed in isolation

**Gmail reviewed-lead import acknowledged failed persistence.** `JobIngestionService` returns structured failed/rejected counts. The single-lead Gmail wrapper previously returned those results as HTTP 200 even when zero jobs were persisted. AGY's success notice then evaluated `inserted_count || 1`, claiming one vacancy was added.

The wrapper now raises `gmail_lead_import_failed` through the existing HTTP 409 boundary when ingestion fails, rejects the record, or returns anything other than one job ID. It leaves evidence unmarked for review/retry. A commit failure also continues to propagate as an error. Regression cases inject actual repository persistence exceptions (`SQLAlchemyError` and conflicting-identity `ValueError`), assert HTTP 409 and unchanged evidence, then verify successful retry, durable evidence annotation and duplicate recognition. Both cases failed against the original implementation and passed after the fix.

No request/response field changed. Generated API types from this backend are byte-identical to AGY's committed `frontend/src/types/api.d.ts`.

## Contract review and AGY handoff

The running preparation backend used actual local FastAPI sockets and disposable PostgreSQL 17. Provider transports and candidate data were fictional; no production frontend was attached. Thirty HTTP assertions covered authentication, unknown-question generation, deduplication, durable reads, draft edit, stale edit rejection, unsigned approval denial, signed exact approval, approval replay denial, history, answer reuse, profile edit, stale profile rejection, stale-answer blocking, two-account evidence isolation, cross-account import denial, duplicate import, Apify rights/accounting, forbidden Actor metadata, provider status, startup filters and browser status. A running OpenAPI snapshot was retained privately.

| Contract area | Preparation finding / remaining acceptance |
| --- | --- |
| Startup filters and evidence | Country/industry, 11–50 range versus exact count, technical staff and size evidence have backend regression coverage. Search request rejects unsupported sort fields with 422. No genuine company or employee collection was authorized. |
| Startup sorting | **AGY fix pending:** `StartupExplorer` sorts only the current 12-result page after backend pagination. Sorting by company, job count or headcount cannot order the whole result set. Define global backend sorting or explicitly label page-only sorting; add a multi-page regression. |
| Startup contacts | List cards expose aggregate contact counts. They do not supply the provider-reported versus source-backed contact distinction claimed by AGY's report. Validate actual contact evidence through the recommended-contacts/detail workflow before accepting workflow D. A count alone is not verification. |
| Apify metadata/rights/budget | Backend reports local reservation accounting and `execution_authorized:false`; unallowlisted Actor metadata is HTTP 409. **AGY fix pending:** configured Actor badges compare Actor IDs with source portal IDs (`naukri`, `wellfound`, etc.). `SourceConfig` provides no Actor-ID mapping. Show unknown association or use a reviewed safe mapping; do not infer association from portal IDs. Surface source-query failures explicitly. |
| Apollo eligibility/evidence | Provider guards cover unsupported premium/unreviewed account capability, credit and rate-limit gates. Fresh private configuration has no `APOLLO_API_KEY`; actual eligibility and contact evidence remain blocked. |
| Gmail accounts/scopes/sync | Read accounts use separate tables, exact read grants, generation fences, per-account policies/cursors/evidence and bounded sync. Focused tests cover metadata/body scope separation, refresh/reconnect, sync leases, rate limits, pool restart, deduplication and reviewed imports. Running HTTP checks verify two-account isolation and GET-only fictional mailbox calls. |
| Candidate facts/versioning | Profile writes use `If-Match`; a stale existing version actually returns **409**, not 412. Missing/invalid preconditions are a separate precondition path. AGY handles both 409/412. Backend profile edits make existing exact answer approvals stale and block reuse. Full AGY CRUD through Chromium remains untested here. |
| NEEDS_INPUT | Running backend verified create/read, deduplication, drafts, exact signed approval, replay rejection, history, versioned reuse and stale blocking. AGY UI retains draft/error handling in source review; dashboard-to-database browser acceptance awaits integration. |
| Browser statuses | **AGY fix pending:** the new badge compares lifecycle values `filled` and `manual_submission_required`, neither of which exists in running `PacketRead.lifecycle_state`. Actual fill completion is represented by browser analysis diagnostics such as `filled_review_on_website`; native receipts have a distinct `form_filled` state. `execution` is submission-attempt state, not fill completion. Bind the badge to actual current fill receipts/diagnostics, preserve cancellation/freshness checks, and add a real response fixture. Current new test forces `lifecycle_state:"filled"` through `as any`, bypassing the contract. |
| Gmail frontend result reporting | Backend failure acknowledgment fixed above. **AGY follow-up pending:** remove `inserted_count || 1`, retain exact zero/count/error semantics, and type/validate the ingestion result. Message-level `imported_job_ids` also cannot prove every URL in a multi-link message was imported; deduplicate badges by actual job/URL identity. |

These are prepared findings for the frontend owner. No AGY frontend fixes were authored or claimed completed by Codex, and no external message was sent. Combined acceptance requires resolving these findings with AGY before the final full run.

## Fresh local verification and failure history

Atomic `fcntl.flock(LOCK_EX | LOCK_NB)` used the existing inode at `/tmp/automated-apply-heavy-tests.lock`. Each test group ran sequentially; the lock was released without unlinking it. A busy lock would have stopped preparation tests without starting a container. Only this task's disposable container was started/stopped. No active agent's tests were interrupted.

Private receipts, exact commands, JUnit XML, source probes and logs are under `~/Library/Application Support/Automated Apply/phase35-final-preflight-20261028/` with restricted directory permissions. They are excluded from Git. No credentials, real candidate facts or mailbox content are included in this report.

| Fresh check at implementation SHA `709c814ea3062338f8cc8a4cc620a4e7d2facaba` | Result |
| --- | --- |
| Focused backend: Phase 3 contracts, Gmail, provider guards, startup research, missing input, PostgreSQL integrations/public ATS, discovery timings and new import recovery | **83 passed, 0 failed, 0 skipped**, 16.06s; JUnit retained |
| Standalone Gmail migration/recovery verifier | **PASS**, PostgreSQL 17, both `job_agent` and rendered `public`; also included in focused total |
| Running FastAPI/PostgreSQL contract probe | **30 HTTP assertions passed**; no production frontend exercised; no external provider requests/mailbox mutations |
| Controlled Greenhouse-shaped 27-record benchmark | **PASS**; 27 discovered/inserted, 0 rejected/failed/skipped, 8.8022s; 113 SELECTs; zero checked-out connections afterward |
| Changed-file Ruff (`--isolated --select E9,F,I`) | **PASS** |
| Changed-service Bandit | **PASS**, no findings |
| Secret scan on new/modified backend files using existing baseline | **PASS**, no baseline changes |
| Backend OpenAPI export, type generation/format, comparison to AGY types | **PASS**, byte-identical types |
| Full combined backend regression | **NOT RUN**; baseline gate closed |
| Extension units/DOM/React/MV3-native rerun | **NOT RUN**; no integrated candidate exists |
| Full frontend Vitest/typecheck/format/production build | **NOT RUN** on a combined candidate |
| Combined production frontend + FastAPI/PostgreSQL/Chromium E2E A–F | **NOT RUN** |
| Full combined security/secret/dependency scans | **NOT RUN**; only scoped preparation scans above ran |

Failure history is retained, not replaced by passing totals:

1. New import regression before the fix: **2 failed**, each proving HTTP 200 with zero persisted jobs. After the fix: **2 passed**, subsequently included in the 83 total.
2. First focused preparation invocation: **82 passed, 1 failed**. The restart test rejected the deliberately new container name/random port before any restart because it permits only enumerated disposable targets. The task's own container was removed. The final run created the permitted `automated-apply-p35-postgres:55435` fixture under the lock and passed all 83 without weakening that safeguard.
3. First running-API probe stopped at an incorrect probe expectation: profile stale revision returned the implemented 409 while the probe expected 412. Corrected the private probe; final 30 assertions passed. No application code was changed to satisfy the mistaken expectation.
4. Initial private readiness probe had a duplicate `timeout` keyword and stopped before connecting. Corrected that invocation; the read-only inventory then succeeded.

Original branch reports remain separate: Codex reported 2,544 backend, 49 extension units, 25 DOM-race cases, four React cases and 23 native scenarios; AGY reported 183 frontend tests and build checks. None is counted as a fresh integrated pass.

## Gmail live migration readiness and exact approval plan

Fresh restricted-role, read-only online inventory observed **PostgreSQL 17.11 over TLS**, schema `public`, a passing exact baseline/security catalog preflight and an **absent** Gmail overlay. One legacy connection exists; new read-sync and body-review flags remain false. No live DDL, token refresh, OAuth consent, mailbox read or mutation occurred during this preparation. Catalog agreement establishes current state, not migration execution history.

Scope: add only `public.gmail_read_accounts` and `public.gmail_read_oauth_states`, their reviewed indexes/constraints and forced RLS policies. Nonlogin `job_agent_owner` owns them; `job_agent_runtime` gets SELECT/INSERT/UPDATE. No DELETE/DDL/runtime ownership, memberships, schema/default privilege expansion, or access for PUBLIC/anon/authenticated/service_role is allowed. Existing legacy account/token/OAuth rows remain separate. The runtime is single-owner; the backend authenticates the owner and isolates account IDs, rather than treating permissive backend RLS as a multi-tenant identity boundary.

Reviewed templates:

| Artifact | Exact rendered `public` SHA-256 |
| --- | --- |
| `backend/scripts/migrations/phase3_gmail_readonly.review.sql` via `render_review_sql("public")` | `e61d2e23fb27991715e2689cda14273d11abf4aac04e71babaf8ef4f5c434ebd` |
| `backend/scripts/migrations/phase35_gmail_readonly_rollback.review.sql` via `render_rollback_sql("public")` | `679d2ebfc0128d5f6a09832ecb675dd86fc9624e5861a6794e07a1def9dbd24a` |

The source template uses `job_agent` for disposable testing. Never apply that unrendered template to the online database. Private rendered files and the exact target identity hash are retained with the inventory, outside Git.

Disposable PostgreSQL 17 tests freshly passed: exact replay, injected-DDL failure atomicity, unchanged baseline, owner/runtime grants and forced RLS, extra-column/policy/index/grant/partial-install drift rejection, independent account storage, forbidden write scopes, session durability, empty-install rollback and populated/RLS-hidden rollback refusal. `IF NOT EXISTS` is not a substitute for the preflight. Both forward/recovery scripts use a transaction, common advisory maintenance lock, 5s lock timeout and 30s statement timeout. Rollback uses table locks and `DROP RESTRICT`, never cascade.

Exact staged owner plan:

1. **Database target and backup approval:** privately confirm the target identity from `readiness.private.json`, `public` schema, maintenance window and maintenance identity. Establish a recoverable backup with a restore rehearsal, preserving encrypted tokens and the corresponding encryption keys. Current preparation does not establish backup recovery. Stop connect/sync writers and capture the pre-change catalog. Keep read-sync/body flags disabled.
2. **Migration-only approval:** owner explicitly authorizes the rendered forward SQL with SHA-256 above against that exact target and schema. Approval covers only those two additive tables and their objects/grants. It does not authorize changing runtime, connecting Gmail, reading messages or sending mail. An approved maintenance operator rechecks identity, stopped writers, lock availability and exact catalog preflight in the maintenance context; on drift or errors, abort without broadening permissions. The runtime role must never be elevated to execute DDL.
3. **Execution and verification after approval:** execute that pinned transaction once; retain its receipt. Verify pinned overlay under the restricted runtime, ownership, forced RLS, grants, indexes/constraints, absence of baseline drift and healthy existing legacy OAuth. Verify read accounts remain empty and disabled. Do not claim activation from a committed migration alone.
4. **Recovery decision:** before any new account/state/evidence exists, the separately approved pinned empty-install rollback may run with the reviewed maintenance identity. It refuses populated tables and any `gmail_sync:`/`gmail_msg:` evidence. After consent or evidence exists, disable workers/flags and use a reviewed forward repair or explicitly approved verified backup restore. Do not truncate, cascade, discard tokens or assume schema rollback restores data.
5. **Separate runtime approval:** after #39 merge, final integration review and all combined checks, approve replacement of the exact deployed runtime/extension build with a retained rollback target. Then verify readiness and OAuth callback/token encryption compatibility. Existing compose/send permission grants no read-account consent.
6. **Separate account and retention approval:** complete applicable restricted-scope verification/security assessment or documented exemption; owner consents each exact intended account and read scope. Start with one account, one curated custom job-alert label, metadata only, one page/at most 25 message IDs, seven-day backfill and 14-day evidence retention. Confirm sender restrictions before the first sync. Gmail metadata scope cannot use `q`. Body access requires its own purpose, compliance review and account consent. [Google scope requirements](https://developers.google.com/workspace/gmail/api/auth/scopes).
7. **Retention readiness before activation:** configured backfill is bounded to 1–30 days and evidence retention to 1–90 days. Current purge scrubs expired evidence on evidence reads/sync and clears it on disconnect; it is not an independent scheduled deletion guarantee. Unconsumed expired OAuth state rows have no demonstrated periodic cleanup. Approve and verify an idle-account cleanup schedule, OAuth-state/verifier retention, key/backup retention and imported-job retention before claiming compliance with a time-based deletion policy. Imported job records are separate from mailbox evidence. The runtime has no DELETE grant; cleanup design must preserve that boundary or undergo separate reviewed migration approval.
8. **First sync acceptance:** only after all prior gates, owner authorizes the bounded selection. Verify actual account attribution/scopes, deduplication, retained evidence, error/retry behavior, expiry cleanup and zero mailbox mutations. Repeat independently for the second account. Approval for account one is not consent for account two. No send/draft/reply/modify/archive/delete/mark-read call is in scope.

## Actual provider acceptance

Fresh official Apify reads authenticated the existing configured credential, fetched account limits/usage and retrieved all three investigated Actor schemas/pricing. No configured Apify/Apollo/Gmail connector tools were available in this session; checks used the existing official API adapter. No Actor execution, datasets, personal LinkedIn credential/session, account rotation or paid endpoint was used.

Apify's public [Free plan](https://apify.com/pricing) advertises $5 usage. Account-specific limits/usage were observed privately; a usage-ceiling subtraction is not a verified spendable balance. Local reservation values are never presented as provider credit. Latest effective FREE event metadata observed: company search $0.002 short/$0.004 full plus memory-dependent $0.001 start; company detail $0.004/result plus memory-dependent $0.00005 start; employees $0.003 basic/$0.008 full/$0.012 email-search plus $0.02 start, with $0.05 minimum max-charge setting. Pricing is observation-time metadata, not a run quote or authorization. Sources: [search](https://api.apify.com/v2/actors/harvestapi~linkedin-company-search), [company](https://api.apify.com/v2/actors/harvestapi~linkedin-company), [employees](https://api.apify.com/v2/actors/harvestapi~linkedin-company-employees). Collection remains disabled until source rights, actual allowance, exact bounded inputs and zero-spend permission are established. No money was spent by this preparation.

**Apollo setup blocker:** `APOLLO_API_KEY` is absent in the existing provider configuration. Owner must supply an eligible credential in private configuration, then establish exact free/work-email eligibility, endpoint access and reviewed credit pool/remaining allowance. No premium endpoint or upgrade was attempted. Actual contact lookup acceptance remains blocked. [Apollo authentication](https://docs.apollo.io/reference/authentication).

**Gmail live acceptance:** blocked by the absent overlay, disabled sync, new account consent/security/selection gates and retention readiness. Legacy compose authority was not reused. No real message evidence was acquired.

## Chrome and discovery findings

The Codex extension/browser fixes remain present unchanged in the preparation history. Their original evidence covers worker/native reconnect, stale inspections, React controls, one-shot batching, duplicate actions, consent/sensitive fields, file handling, human revision provenance, missing questions, cancellation and submission uncertainty. This task did **not** rerun those suites or deploy the extension. A passing native-preview suite is not evidence of genuine applicant form filling. Workflow F and real approved-destination/physical-gesture acceptance remain pending.

Discovery instrumentation was inspected and a fresh controlled local load was run: one-connection pool, 27 Greenhouse-shaped records, 30ms simulated SQL latency, 100ms simulated network latency. Result: 8.8022s, all 27 committed, 113 SELECTs, pool checked out zero. Recorded stages: claim 0.048752s, profile 0.040580s, provider 0.113347s, ingestion 8.463264s, matching 0.052108s, finalization 0.039342s; commit acknowledgments retained separately. Existing overall deadline is 90s, with bounded pool checkout and phase diagnostics. The redundant post-insert SELECT fix is retained. Focused tests also passed actual disposable server restart, transaction rollback, lost commit acknowledgment, deadlines and idempotent retry.

The historical 27-listing live failure remains approximately 95.06s with no original stage diagnostics. This local result cannot establish its bottleneck or resolution. No new live discovery run was authorized or performed. If the owner later approves a specific bounded source run, retain fresh stages, upstream timings, pool contention, commit acknowledgment and exact runtime SHA before judging that incident resolved.

## Post-merge integration and publication gates

When the owner has approved and merged #39, recheck GitHub, fetch actual main and record the real merge SHA. Inspect changed ancestry and all worktree statuses again. Create one linked integration worktree from that baseline on `integration/phase35-final-20261028`. Preserve complete histories with non-destructive merge commits for Codex, AGY and the preparation-fix branch; do not squash or overwrite agent branches. If main was squash/rebase merged, reconcile contents and ancestry explicitly. Coordinate frontend fixes/conflicts with AGY, who retains frontend ownership.

Before publishing, acquire the same existing lock atomically and run sequentially:

1. Full backend/PostgreSQL regression with explicit disposable PostgreSQL 17 and an allowed owned restart fixture; retain JUnit totals and failures.
2. All extension units/build, DOM-race, actual React, popup/unanswered and MV3/native journeys, accounting for the MV3 harness's own lock acquisition to avoid nested-lock deadlock.
3. Full AGY-integrated frontend Vitest, typecheck, formatting, generated types and production build using pnpm.
4. Actual production-built frontend/FastAPI/disposable PostgreSQL/Chromium E2E A–F. Include truthful drafts/approval/history/reuse, fact-change staleness, independently scoped accounts/isolation/duplicate import/error recovery, 11–50 India evidence/contact distinctions, Apify policy/cost denials, and real extension field mapping/preview/cancellation/reload/unknown-submission handling on fictional employer pages. Zero employer submissions and mailbox mutations.
5. Full security, unchanged-baseline secret/private-artifact scan, pinned dependency audits and running API/generated-type comparison. Record final implementation commit and backend/frontend/extension tree objects before testing; rerun affected checks after any change.

Publish one reviewable final integration PR only after the baseline gate, AGY findings and all combined engineering checks pass. Preserve manual-only workflow triggers; publishing must not dispatch/rerun hosted jobs. Never merge the final PR automatically.

Pending external actions each require their own explicit scope: owner merge of #39; exact Gmail target/SQL/maintenance approval; verified backup/recovery authority; runtime/extension replacement; each Gmail account/scope/security/selection and bounded sync; Apify rights/current allowance/zero-spend execution permission; Apollo private credential/eligibility followed by a separately approved lookup; specific real employer destination plus physical fill gesture. Employer submission, deployment, paid services and hosted CI remain unauthorized by this preparation.
