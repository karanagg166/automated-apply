# Phase 3.5 activation and reliability — Codex

Controlled live activation remains **PARTIAL**. The restricted online database, approved candidate context, existing native host and Telegram identity were checked successfully. New Gmail read consent/schema, provider collection authorization, runtime replacement and genuine applicant autofill remain owner-gated. A prepared migration and authenticated metadata inspection are not live activation.

## Branch, ownership and evidence

Worktree: `/Users/karanagg/Desktop/Projects/automated-apply-codex-p35`; branch: `feat/phase35-codex-activation`. Its exact baseline is PR #39 head `e57178b22e453119f4ba449dae28f36c01b6edc5`. No primary-checkout changes, other-agent branch integration, PR merge, push, deployment or hosted workflow dispatch/rerun was performed.

Implementation/test SHA: `f2613ce86d098b2bcf3c39b61ffbce539a623b57`. Backend tree: `028100a853a6067bc93e900030ad19aa57b9cdd3`; extension tree: `ca50b760762170d7e5b288cf6dd49dfd601e77d4`. The final report commit changes only this document; its exact SHA is recorded in the private final manifest and delivery response. Resolve the local delivery ref with `git rev-parse feat/phase35-codex-activation`.

Private, owner-readable evidence is outside Git at `~/Library/Application Support/Automated Apply/phase35-codex-evidence/`. It includes the migration checklist, rendered public SQL and rollback with exact hashes, provider metadata appendix, runtime receipts, benchmark logs, interrupted/failed diagnostics and final validation logs. No tokens, mailbox address, candidate facts, private PDF bytes or private reports are committed.

Changed files (17 total):

- `backend/app/browser/driver.mjs`
- `backend/app/integrations/gmail/schema.py` and `schema_checksum.py`
- `backend/app/repositories/job.py`
- `backend/app/services/job_discovery_service.py`
- `backend/scripts/benchmark_discovery.py`
- `backend/scripts/migrations/phase3_gmail_readonly.review.sql` and `phase35_gmail_readonly_rollback.review.sql`
- `backend/scripts/phase35_runtime_audit.py`
- `backend/scripts/verify_phase3_integrations_postgres.py`
- `backend/tests/test_discovery_phase_timings.py` and `test_public_ats_postgres.py`
- `extension/form-dom.js`
- `extension/tests/fill-races.browser.mjs`, `form-bridge.test.mjs` and `react-forms.browser.mjs`
- `docs/phase3/activation-codex.md`

## Fresh runtime matrix

`READY` means the named check passed; it does not authorize another action. Observations were made on 2026-10-28 with existing approved private configuration.

| Area | Status | Evidence and exact remaining gate |
| --- | --- | --- |
| Supabase connection and runtime identity | READY | PostgreSQL 17 over TLS; complete existing `public` catalog and restricted `job_agent_runtime` boundary verified, including ownership, forced RLS, effective grants and pinned follow-up constraints. |
| Migration history and drift | PARTIAL | Existing catalog matches the approved bundle. No Supabase migration ledger is present; catalog state cannot prove historical migration execution. Recheck in the approved maintenance transaction. |
| Gmail read-only schema | BLOCKED | Both new tables are absent. Reviewed SQL and disposable migration/recovery tests are prepared; explicit owner approval, backup readiness and live execution are pending. |
| Gmail read accounts and scopes | BLOCKED | The existing legacy compose identity passed a fresh bounded verification; zero independently consented Phase 3 read accounts. Compose includes send authority in the legacy connection, never read consent or write permission in this workflow. New account consent, compliance review and curated mailbox selection are pending. |
| Gmail actual synchronization | BLOCKED | Live sync/body flags remain disabled. Zero live message reads, body reads or syncs. Activate schema/runtime, consent one selected account and approve its bounded job-alert policy first. |
| Apify API | PARTIAL | Existing credential authenticates against limits/usage endpoints; all three investigated Actor input schemas are available. Pricing and account limits are observed privately. Collection rights, current spendable allowance and bounded execution approval are not established. |
| Apify MCP | PARTIAL | No Apify MCP server is configured in the current Codex configuration. Existing official API metadata access works; no route/account rotation or new server installation was attempted. |
| LinkedIn-derived company/contact collection | BLOCKED | Zero Actor executions/results in this phase. No verified source/data-use rights or bounded execution approval. No personal LinkedIn credential, cookie or session was accessed. |
| Apollo | BLOCKED | Local API credential absent. Eligibility, endpoint permissions and remaining credits cannot be verified. Safe disabled state retained; zero lookups/enrichments/outreach. |
| Candidate and approved resume | READY | Current saved profile version is owner-approved; four current approved project contexts and one confirmed primary private-PDF resource link exist. The Drive active-version pointer is unset; the approved manual PDF is a separate working source. No candidate facts were edited. |
| Missing-input storage and approval | READY | Existing protected storage is present. Fictional tests verify durable unknown → edit → separate factual approval → exact-context reuse, revisions and staleness. Zero genuine saved question requests currently exist; no live owner answer was fabricated for testing. |
| Chrome/native host | PARTIAL | Installed manifest/origin/executable match configuration; genuine framed native `health` succeeds with matching request ID. Local Phase 3.5 fixes are not deployed. Genuine applicant autofill still needs a specific approved destination and physical browser gesture. |
| Telegram owner-only status | READY | Bot identity and absence of a webhook verified; configured owner private chat passes, other users/groups fail authorization checks. No updates were consumed and no Telegram messages were sent by this phase. |
| Deployment | BLOCKED | Owner review/merge of #39, post-merge reconciliation, publication review and separate runtime approval remain pending. |

## Gmail migration and recovery review

The additive scope is exactly `public.gmail_read_accounts` and `public.gmail_read_oauth_states`, their constraints/indexes, forced RLS and the existing single-owner backend policy. The nonlogin owner owns the tables; the restricted runtime gets only SELECT/INSERT/UPDATE. PUBLIC, anon, authenticated and service_role have no access. There are no new memberships, schema/default grants, legacy token rewrites or baseline table/function changes.

The migration now bounds lock/statement waits and takes a common transaction-scoped maintenance lock. The preflight rejects partial installations, altered columns/constraints/policies/indexes and excess permissions. `IF NOT EXISTS` alone is not treated as drift validation. The exact SQL checksum is updated; baseline migration files and the original public bundle remain unchanged.

Disposable PostgreSQL 17 verification covers both `job_agent` and translated `public`: complete migration, exact replay, injected failed-DDL rollback, unchanged baseline catalog, empty-install schema rollback, populated rollback refusal, RLS-hidden owner refusal, excess grants and drift rejection, forbidden write scopes, per-account isolation and durable commit/rollback across sessions. The rollback uses explicit locks and `DROP RESTRICT`; it never cascades or deletes existing OAuth/evidence rows. Once consent/evidence exists, it refuses deletion and requires a reviewed forward repair or verified backup restoration.

The private checklist `gmail-migration-checklist.private.md` contains rendered SQL hashes, maintenance identity/target checks, stopped-writer requirements, backup/key preservation, restore verification, post-commit catalog checks and separate runtime/account consent gates. A recoverable live backup has not been established by this task. No live DDL was executed.

Each mailbox needs its own PKCE/browser-bound read grant, account identity, encrypted tokens, generation fence, lease, cursor and evidence namespace. Minimum metadata consent does not imply body consent. Both Gmail metadata and readonly scopes are restricted; applicable verification/security-assessment requirements or a documented exemption must be reviewed before activation. [Google scope requirements](https://developers.google.com/workspace/gmail/api/auth/scopes).

After all gates, the proposed first live check is one selected mailbox, one curated custom job-alert label, metadata only, at most one page/25 selected IDs and bounded age/retention. Metadata scope cannot use Gmail `q`; sender/subject/date checks minimize retained evidence. Body access additionally needs a documented purpose, compliance review and separate account consent. This first live check has **not** occurred. This workflow has no send, draft, reply, modify, delete, archive or mark-read operation.

## Apify and Apollo

The existing adapter was retained. Fresh official API inspection retrieved schemas and pricing records for `harvestapi/linkedin-company-search`, `harvestapi/linkedin-company` and `harvestapi/linkedin-company-employees`. These are third-party Actors. Their metadata does not grant LinkedIn collection rights or authorize a run.

The latest effective free-tier event metadata observed here reports company search at $0.002 short/$0.004 full plus a memory-dependent $0.001 start event; company detail at $0.004/result plus a memory-dependent $0.00005 start event; employees at $0.003 basic/$0.008 full/$0.012 email-search plus $0.02 start, with a $0.05 minimum max-charge setting. These are inspection-time event records, not an exact execution quote or permission to spend. Future/historical entries are not added together. [Search metadata](https://api.apify.com/v2/actors/harvestapi~linkedin-company-search), [company metadata](https://api.apify.com/v2/actors/harvestapi~linkedin-company), [employee metadata](https://api.apify.com/v2/actors/harvestapi~linkedin-company-employees).

The private appendix records actual reported account-wide limits and current usage. The arithmetic difference between a monthly usage ceiling and usage is not verified spendable credit. Local reservations remain separate from provider accounting. No account-wide limit was raised; no paid overage or Actor run occurred. Any future run needs current tier/pricing, verified allowance, source/data-use rights, bounded inputs and explicit execution approval under one common budget. [Apify account limits](https://docs.apify.com/account/limits).

The company-search schema exposes reported size bands (`1-10`, `11-50`, `51-200`, etc.); the employee schema exposes headcount bands and title filters. Bands and returned profile counts are not exact headcount. Existing tests cover bounded size filtering, normalization, provenance and duplicate detection; founder/CEO/CTO claims need explicit role evidence. No genuine company/contact results are claimed. Authorized official websites remain the available alternative after a company/source scope is selected.

To connect Apollo, the owner can create an eligible account/API key and place `APOLLO_API_KEY` in approved private configuration. Keep enrichment disabled until free-account/work-email eligibility, the exact reviewed endpoints, credit pool, timestamp and evidence URL are recorded through the existing `APOLLO_*` settings and introspection succeeds. Unknown permissions/credit schemas block dispatch. Search supplies limited prospect evidence; enrichment is a separate capability. Current plans and free eligibility must be checked against the actual account. [Apollo access](https://docs.apollo.io/reference/apollo-api), [search results](https://docs.apollo.io/docs/find-people-using-filters), [credit pricing](https://docs.apollo.io/docs/api-pricing).

The existing adapter disables personal-email/phone reveal and waterfall enrichment, keeps business-email evidence distinct from provider verification claims, and respects suppression, staleness and configured retention. No email is synthesized, no other account is used to bypass credits and no outreach is sent.

## Extension and missing-answer reliability

- Each inspection receives a fresh identifier, invalidating an older popup/plan even in the same document. A consumed fill cannot replay after native authorization/receipt loss.
- Select review binds option identity, value, disabled/hidden state and text. Changes stop before a write.
- Mid-batch page handlers cannot overwrite a newly selected radio/checkbox peer. Existing answers, file selections, sensitive/consent controls and unsupported fields retain their safety boundaries.
- Final and delayed verification compare actual values with the approved action; optional fields reverted by framework handlers report failure/needs-input. Worker receipts reflect delayed failures.
- Actual React in a CDP isolated world reproduced a checkbox reporting DOM success while React state stayed false. Event-enabled worker choices now use checkbox/radio activation events so React receives the change, without duplicating input/change delivery. Manual extension filling still emits no page events. Structural React re-renders conservatively stop the remaining batch for fresh review.

No DOM undo is promised after page events or navigation: cancellation/freshness fences prevent later actions, and uncertain state hands control back to the owner. Replaying mutations or restoring stale values could overwrite subsequent owner/framework changes. Resume upload remains manual in the extension; the separate worker retains canonical-PDF/digest checks and never replaces a selected file.

Unknown answers remain `NEEDS_INPUT` with the exact protected question/context. The existing dashboard contract exposes the saved request; factual human edit and separate exact-revision approval are required before reuse. Drafts, stale context/profile/project revisions and edited approved answers are rejected. Current-context owner-answer provenance remains distinct from profile/project evidence. No frontend changes were made.

## Discovery timeout diagnosis

The genuine historical audit remains `upstream_error`: 27 discovered, zero committed, approximately 95.06 seconds elapsed and no phase diagnostics. This establishes a failed bounded run, not its precise bottleneck. No live provider requests were expanded to reproduce it.

Current diagnostics separate claim and connection checkout, profile checkout, concurrency/pacing, provider network/JSON/normalization, filtering, ingestion, matching and finalization. Commit acknowledgement and total audit persistence are logged only after durability; persisting a transaction's own acknowledgement in that same transaction is impossible. Logs contain run IDs and timings, not job/candidate bodies.

A reproducible redundant query was removed: inserting a Job now returns its mapped row directly rather than selecting it again. In fresh, one-connection PostgreSQL fixtures with 27 Greenhouse-shaped listings, 30ms simulated SQL latency and 100ms simulated HTTP latency, SELECTs fell from 140 to 113; one observed run fell from 10.3045s to 8.6508s. Final fixtures at the pinned SHA completed 3/27/100 records in 1.3703/8.9108/31.8793 seconds with 30ms SQL latency, and 27 records in 26.6454 seconds with 100ms SQL latency. Every batch committed its full result and returned the pool to zero checked-out connections. These are local sensitivity measurements, not live latency or proof that the historical timeout is fixed. The benchmark now supports the historical source shape, explicit simulated network latency, SQL timings and commit acknowledgements. Regression checks bound round trips, preserve all 27 observations and verify idempotent replay.

## Local validation and genuine evidence boundary

Final verification below used implementation SHA `f2613ce86d098b2bcf3c39b61ffbce539a623b57`. Heavy work uses the same inode at `/tmp/automated-apply-heavy-tests.lock` with atomic `flock`, released on success, error and cancellation; the MV3 harness acquires that lock itself. Suites ran sequentially. Databases, identities and employer pages used by tests are fictional and disposable.

| Check | Result |
| --- | --- |
| Full backend with PostgreSQL 17 and explicit Docker restart target | 2,544 passed; zero failed/errors/skipped; 711.18s; two existing PDF-fixture deprecation warnings |
| Gmail migration, drift, empty/populated recovery and two schemas | Passed within full suite and standalone final PostgreSQL verifier |
| Gmail selected sync, rate-limit recovery, pool restart and two-account isolation | Passed; full suite includes 17 Gmail read-only cases and 16 public-ATS/PostgreSQL cases, including the new recovery test |
| Provider budget/rate/rights guards, Apollo gates, missing-answer approval/staleness | Passed; 22 Phase 3 provider-guard cases and 10 missing-input cases are included in the full total |
| Extension units and MV3 build | 49 passed; build passed |
| DOM-race suite | 25 passed; zero external requests/submissions |
| Actual React isolated-world cases | 4 passed; zero form POSTs/submissions |
| Popup and unanswered-field journeys | Both passed |
| Actual MV3/native/FastAPI/PostgreSQL journeys | 23 passed; Chrome 156.0.8078.4; zero form submit events/POSTs; all 22 retained history rows `submitted:false` |
| Ruff and full-app Bandit | Passed; no findings; one existing unused `nosec` annotation notice |
| Secret/private-artifact scans | Passed with the existing baseline; no baseline widening |
| API-contract consistency | Generated TypeScript byte-identical; frontend sources unchanged |

The standalone DOM/React commands are `node extension/tests/fill-races.browser.mjs` and `node extension/tests/react-forms.browser.mjs`; extension units/build/native journeys use the documented pnpm scripts. The full backend used the explicit disposable `PROFILE_TEST_DATABASE_URL`, `P22_TEST_POSTGRES_CONTAINER=automated-apply-p35-postgres`, `pytest backend/tests -q --durations=15` and a retained JUnit report under the private lock wrapper. Test totals above are not added together where focused cases already belong to the full suite.

An initial backend run was deliberately interrupted before completion to add actual React regression coverage; it is not a passing full-suite result. The React diagnostic first exposed conservative re-render handoff, then a real controlled-checkbox state mismatch. That failure and corrected four-case evidence are retained privately. A preliminary extension unit invocation lacked the Python dependency-environment selection; it was rerun successfully with explicit `PYTHON`. An early benchmark fixture used integer IDs in string rewriting; its failed run is retained, and comparisons use fresh corrected 27-listing fixtures. The existing Gmail identity probe initially misinterpreted the successful verifier's return shape; the corrected bounded identity receipt is retained.

Genuine evidence in this phase is restricted-role live database/catalog reads, approved candidate/resume linkage checks, existing legacy Gmail OAuth identity verification/refresh, installed native health, Telegram identity/webhook inspection and Apify metadata. The identity probe allowed only the OAuth token refresh and GET-only userinfo/Gmail profile endpoints; it did not read messages or request new scopes. Test read-only OAuth/mailbox transports, applicant pages, owner answers and employer POSTs are fictional. The MV3/native suite exercises preview/session/transport reliability and explicitly records no form fields read or filled; DOM/worker filling is covered separately by fictional browser tests. Dashboard sources were unchanged; backend approval/persistence, response contracts and popup missing-question links were reverified, while PR #39's production dashboard browser journeys were not rerun in this backend/extension worktree. No live mail message read/write, Actor execution, Apollo enrichment, real employer autofill/submission, runtime deployment or new OAuth scope is claimed.

## Remaining owner approvals and publication

1. Review and merge PR #39 manually. At the final GitHub check it remains open, unmerged and at the exact specified head. This branch must then fetch actual `main`, reconcile the real merge ancestry and rerun affected checks before its final PR is published. A private PR draft is prepared; no final PR is published while this gate remains closed.
2. Approve the exact rendered Gmail migration and maintenance scope after backup/recovery review. Separately approve runtime replacement. Passing disposable tests does not approve either action.
3. Complete applicable Gmail restricted-scope review/exemption, consent each intended read account and explicitly select the first mailbox/custom job-alert label. Only then authorize one bounded metadata sync. Body access needs separate purpose/compliance/account consent.
4. For Apify collection, verify rights, current exact price, real remaining allowance, account-wide limits and bounded execution approval. For Apollo, connect an eligible credential and verify endpoints/credits before separately approving any lookup. No spending/overage is authorized here.
5. For real applicant autofill, identify the exact permitted destination and provide a physical browser gesture. Stop before submission. No employer submission is authorized by this phase.

Deployment readiness is **PARTIAL / owner-gated**. Local engineering verification and live activation are reported separately; the historical timeout is not declared resolved.
