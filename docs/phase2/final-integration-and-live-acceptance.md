# Phase 2 final integration and live acceptance — 2026-10-27

Engineering disposition: **PASS**. Live acceptance: **PARTIAL**. Genuine discovery, online persistence, idempotency, matching, read-only Chrome inspection/native preview and the single Telegram test succeeded. No sampled listing established suitability for a new real packet and applicant autofill journey. This report supersedes earlier candidate reports that described acceptance as blocked before the owner's expanded authorization. It is agent verification, not independent human approval.

## Candidate and histories

Integration branch: `integration/phase2-final-20261027`, in the linked worktree `/private/tmp/automated-apply-phase2-final-integration-20261027`, sharing the original repository. Source selected for final full-backend validation: `946bd8606f8329a0dcac72012af93be9b221bc58`. The final backend and extension runtime sources remain identical to that validated candidate. Later AGY frontend refinements receive separate complete frontend revalidation; the PR and delivery response identify the publication SHA. No application code may differ from the validated source without affected revalidation.

The originally specified histories were merged locally without conflicts or rebasing either agent:

| Dependency | Included ancestor |
| --- | --- |
| Current main / merged #34 | `1ad14a4d37cbef59548df2b6ec75c9495719b61f` |
| PR #35 | `02bfb83a89f5e13f72a533aed87410b7e0a47d21` |
| PR #36 | `0c274a372e50f94743cf6334a09588253e5bb473` |
| Final Codex engine | `3411df2af354e8d9123f5e6d6c6c5d4401ddae77` |
| Initially specified final AGY UI | `08f795994ef4bec662395d42b9115c3bbfb8a3df` |
| Additional AGY refinements found during final preservation audit | `32592dbd6578debe78949800eb5c88167146a7ab` |

Initial merge commits are `1362258` and `f606666`. The final preservation audit discovered AGY's additional `410dc4d` and `32592db` commits; merge `6502ee3` preserves that history too. Three frontend conflicts were resolved by retaining the combined actual-options editor and save/review guards, adopting AGY's precise counters, experience templates, recovery guidance and added regression, and retaining accurate canonical-PDF/preservation wording. Only frontend/documentation files changed in this follow-up; the passing full backend result remains applicable. PRs #35/#36 remained open, mergeable and without inline review threads when checked. The final integration PR contains their histories and is the single proposed merge vehicle. Do not also merge #35/#36 separately; after an owner-approved integration merge, close them as superseded. Neither PR was merged, closed or retargeted by this work.

The original checkout and both agent worktrees were preserved. Agents had exclusive file ownership. Final heavy checks used `/tmp/automated-apply-heavy-tests.lock` sequentially; the extension's existing native harness acquired that same lock internally. The frontend agent completed the choice-editor correction and initial verification; the primary agent completed the remaining UI and acceptance work in the integration worktree.

## Corrections established by integration

- Packet revision archives exceeded the existing PostgreSQL `owner_preferences.key VARCHAR(50)` column. Real PostgreSQL/browser tests reproduced failure during packet mutation. Keys now use `prv:{compact UUID}:{revision}`, leaving room for the full positive INTEGER revision range; archived payload, digest, identity and transactional preservation remain. A PostgreSQL regression checks persistence and the actual column bound. No migration or online DDL was needed.
- The final UI exposed choice-question types without collecting the actual options required by the existing API. Three user-flow regressions failed before correction. A bounded options editor now supplies those options; the actual FastAPI dashboard journey adds, persists, answers and reviews a choice question.
- Supplied word limits now gate answer save/review, and technical-experience questions expose the existing configured-generation action. Browser copy accurately distinguishes approved canonical-PDF attachment in the dedicated browser from manual extension attachments, and describes preservation without promising an overwrite capability. Unknown submission outcomes require reconciliation of the existing attempt.
- Older browser tests expected review to overwrite or clear existing multi-selections. The final safety policy preserves occupied values. Positive fill/validation/dynamic/next-step tests now use explicitly empty fixtures, with added after-review preservation assertions for populated controls. Neither browser preservation policy nor consent/submission boundaries were weakened. The PostgreSQL verifier checks the actual exact selected set after filling an empty form.
- Browser test assertions now recognize manual sensitive self-identification and continued incomplete status while a website validation error persists. Dashboard selectors and phase-specific failure assertions match the final UI and durable backend result. A cancellation test waits for actual asset-request startup, with a bounded wait and immediate propagation of task failure.

## Local verification

All local test jobs, profiles, packets, PDFs, provider bodies and employer pages were fictional. The backend HTTP-denial fixture and explicit mock transports prevented live provider calls from tests. PostgreSQL was isolated version 17.11 on loopback; tests created/dropped dedicated child databases. Restart/disconnect tests targeted only the dedicated disposable fixture. Application receipts and submissions in local browser journeys were fictional loopback operations.

| Check | Final evidence |
| --- | --- |
| Full backend, including PostgreSQL integration/security/packet/grounding/recovery | **2,475 passed, zero failures/errors/skips; 1,298.17 s**, `946bd86`; supervisor exit 0; two existing pypdf fixture deprecations |
| Targeted PostgreSQL/archive/browser corrections | 24 passed, zero failures; 73.06 s, corrected source subsequently committed as `e54290f` |
| Frontend unit | **119 passed / 17 files, zero failures; 12.84 s**, `1a4bfe4`; earlier 118-test receipts retained |
| Dashboard E2E through actual FastAPI/BFF | 12 passed, zero failures; 47.8 s, `1a4bfe4` |
| PostgreSQL/FastAPI/browser combined E2E | 12 passed, zero failures; 1.8 min (106.14 s outer wall), `1a4bfe4` |
| Extension unit/native-protocol tests | 44 passed, zero failures/cancellations/skips |
| Extension popup and unanswered-field Chromium checks | Both scripts passed after assertion corrections |
| Extension DOM race/upload/self-identification matrix | 16 passed; zero external requests/submissions, `946bd86` |
| Actual isolated MV3/native/FastAPI/PostgreSQL Chromium harness | 23 scenarios passed, zero failed; 46.77 s, `946bd86` |
| TypeScript, full frontend Prettier, Next.js production build, extension build | Passed |
| OpenAPI and generated API types | Regenerated; no tracked contract/type difference. Canonical schema SHA-256 `026df66cd01740f9deb2c890583bd8e6c3769c3330e9a12067b1fb2a9f9b06d9` |
| Ruff E9/F/I on changed Python (excluding inherited conftest import ordering), full-app Bandit, compilation, diff checks | Passed |
| Native detect-secrets hook, unchanged baseline/policy, tracked private-artifact guard | Passed with unchanged baseline and detector policy |
| Hosted Actions | Not run; all workflow files remain identical to main's manual-only policy |

The first combined frontend implementation was committed as `420d21e`; `194db9e` added browser-test assertions and actual-API coverage. The later AGY merge and precise word-limit assertion are committed through `1a4bfe4` and passed complete frontend unit/type/format/build checks and both complete E2E reruns. The final engine source hashes and per-invocation SHAs are retained privately. The security-fixture clarification is committed as `8811e3e` and passed the final unit/type/format checks; it changes no runtime source. Counts in overlapping focused invocations are not added to the full-suite total.

Failures and incomplete runs are retained:

- First provisional full attempt: 369 passed, seven failed before an intentional diagnostic interrupt. Five failures were the operator fixture URL omitting a password, correctly rejected by the database safety guard; the other two were test wording/startup synchronization. Correcting the fixture exposed the genuine archive-width defect above.
- Initial corrected selection: four passed, three PostgreSQL/browser failures due to archive-width overflow. The archive fix and new regression then passed all 24 selected checks.
- Completed full run at `e54290f`: 2,453 passed, 16 failed, zero errors/skips; 935.80 s. All 16 were the obsolete multi-selection expectations. The corrected affected run passed 30 cases before its 480-second supervisor limit interrupted the final missing-schema case; it is not counted as a passing suite. An earlier 240-second focused attempt was also incomplete.
- After integrating AGY's more precise counter wording, one combined regression still expected the character-limit message for a word-limit violation: 118 passed, one failed. The assertion was corrected to require the word-limit diagnostic; production guards were unchanged.
- Dashboard before assertion alignment: five passed, two failed, five did not run. Final rerun passed all 12.
- The new word-limit test initially used a locator that omitted the required-field marker: 117 passed, one failed; the corrected test passed in the 118-test run.
- A publication scan flagged a fictional URL-userinfo test string. The same rejection case now constructs its fixture URL explicitly and documents the noncredential test value locally; no secret baseline or detector policy changed. A final read-back harness also initially used a different JSON digest encoding; matching the baseline encoding verified unchanged stored state, without any data write.
- Extension browser checks initially failed the old Date-of-Birth classification and then the old complete-form expectation despite a persistent page validation error. Both assertions now verify conservative behavior and both scripts pass.

Detailed receipts, private journals and source hashes remain outside Git in `/tmp/automated-apply-phase2-integrated-acceptance-20261027`; earlier frontend reproduction receipts also remain in `/tmp/automated-apply-phase2-final-evidence/frontend`.

Fictional combined UI screenshot: [packet and choice review](../screenshots/phase2-final/fictional-packet-choice-review.png). It contains no real candidate or employer application data.

The detailed [Phase 2.2 backend readiness review](codex-p22-readiness-review.md) records the independent adapter examination, PR scope/ancestry and focused PostgreSQL security/recovery checks. Its former pending-approval section is historical; the authorization and genuine execution below supersede those prerequisites. Fixed official hosts, board allowlisting, redirect denial, owner authentication, free-provider boundaries, normalized identities, atomic audit/ingestion commit, lost-acknowledgement reconciliation and application-state preservation remain covered by the final full backend suite. No new provider security defect was found during final integration.

## Genuine ATS and Supabase acceptance

The existing private configuration was rechecked rather than treating previous missing-approval wording as a blocker. The approved Supabase project passed read-only TLS/catalog checks on PostgreSQL 17.11, schema `public`, as `job_agent_runtime`, without superuser, bypass-RLS, role-creation or database-creation authority. The current owner-approved profile version 1 and unique confirmed canonical resume were available. The baseline contained eight jobs and two packets.

Temporary process-local allowlists contained exactly:

- Lever global board `spotify`, employer Spotify. The employer's [official careers guidance](https://www.lifeatspotify.com/start-your-journey) explicitly identifies `jobs.lever.co/spotify`. [Lever's public Postings API documentation](https://github.com/lever/postings-api) describes published postings and third-party reading. Access was limited to personal candidate research, with no redistribution or submission.
- Ashby board `atlan`, employer Atlan. Its [official careers page](https://atlan.com/careers/) publishes an anonymous careers component that directly reads the same public `posting-api/job-board/atlan` endpoint and links the hosted board. [Ashby's documented public API](https://developers.ashbyhq.com/docs/public-job-posting-api) defines that read interface. The exact component, source evidence and scope were retained privately.

Each source used page 1 and at most three selected records, no paid permission, one initial run and one fresh-key repeat after durable pacing. The normal bounded transport, byte/record limits, fixed hosts and disabled redirects remained active. An operator egress guard also rejected unapproved paths/methods/credentials and stopped at the total attempt cap. A full board response is downloaded even though only three records are selected.

**Four genuine feed GETs, zero transport retries:** three Lever and three Ashby listings were normalized, matched and saved. Fresh-key repeats inserted zero new jobs and returned the same identities; same-key replays made zero further HTTP calls. Selection identity was pinned between first/repeat runs so a changing page could not silently expand scope. Final counts were 14 jobs, two packets and 12 total source observations. Fresh database sessions/connections verified all four completed audits, saved evidence and profile-version rankings, and re-computed matching agreed with the saved results. Original job status/title/score/explanation and packet revisions/lifecycle/tracking/snapshot were preserved.

### Live timings

Seconds from single observations, not a throughput guarantee:

| Execution | Outer wall | Fetch/JSON transport | Normalization | Ingestion | Matching | Final commit acknowledgement |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Lever initial, three jobs | 21.715 | 3.403 | 0.014 | 11.490 | 1.355 | 0.657 |
| Ashby initial, three jobs | 12.795 | 0.819 | 0.111 | 6.806 | 0.373 | 0.334 |
| Lever repeat, zero inserts | 13.031 | 4.192 | 0.043 | 4.615 | 0.325 | 0.318 |
| Ashby repeat, zero inserts | 8.412 | 0.084 | 0.002 | 4.461 | 0.334 | 0.317 |

The operator harness separately recorded durable claim, pacing commit, final commit acknowledgement and outer wall. Saved diagnostics begin after the durable claim and precede final commit. HTTP/JSON/normalization/adapter measurements are nested inside provider handling and must not be added as independent phases. Claim times were 0.947–1.268 s. No timing is inferred from `finished_at - started_at` as proof of commit latency. Local fictional browser checks were also active during these live measurements; machine load can affect the observed times.

## Matching, factual answers and packet suitability

Matching genuinely ran against approved profile version 1 for all six saved jobs, exposing unknown skills/experience/company evidence rather than inventing it. The Lever sample comprised three commercial sales roles outside the saved role/geography preferences. The Ashby sample comprised a business-development role, a principal engineering role requiring 14+ years, and an AI-native builder role. The latter required production agent/evaluation experience not established by the approved facts. Technical keyword relevance, including a 63-point principal-role score, is not eligibility evidence. No sample established genuine suitability, and no extra board/page/job was fetched to manufacture a successful packet journey.

**Zero new real packets** were created; the two existing packets remained unchanged. Genuine suitable-job → new packet → applicant autofill remains outstanding. Canonical resume availability was verified, but no real resume was attached to an employer page.

Separately, deterministic generation against the actual approved profile/context produced review-required project and personally attributable API drafts with evidence references. The hardest-bug-and-solution question returned `needs_input` because supporting challenge/solution facts were absent. No drafts were saved in this read-only probe, no facts were invented, and zero external AI/model requests were made. Fictional integration tests cover canonical-resume packet creation, review/revision history, handoff, persistence, concurrency and recovery.

## Chrome and Telegram

One exact genuine Lever application URL from the saved sample was opened in an isolated candidate Chrome profile. **One employer GET** returned HTTP 200; candidate DOM inspection found 14 fields and correctly returned `manual_required`. Sixteen unapproved asset/background requests were blocked by the one-request egress policy. The actual MV3 extension/native host called the candidate loopback API, which successfully saved a URL-preview audit. No job or packet was manufactured by browser preparation.

The native URL preview is programmatic. A physical owner toolbar gesture, `activeTab` grant and genuine applicant autofill are not claimed. No candidate values were inserted, no resume was uploaded, no employer write or submission occurred. The existing installed wrapper/release, global host registration and owner Chrome profile were preserved. macOS denied read access to protected owner Chrome preference files; the isolated candidate profile avoided needing that access. Ashby and Lever EU remain manual-handoff destinations for the extension rather than verified fill adapters.

The bounded ATS acceptance sequence used **four feed GETs plus one selected application-page GET (five of eight permitted attempts)**. No additional ATS feed or employer-page request was made. Documentation and employer-permission research were separate read-only lookups; no other ATS board was activated.

The configured Telegram private owner/chat binding was verified against its existing live-poll state, matching bot identity and the official Bot API. A private intent journal prevented replay. **One `sendMessage` attempt** received Bot API success with a matching private chat/message identifier. No `getUpdates`, webhook change, poll-offset/outbox mutation or duplicate notification was performed. This is API-confirmed sending, not a human read receipt. The message contained a bounded acceptance status, no profile facts or resume.

## Historical timeout and remaining limits

The old ordinary Greenhouse run discovered 27 listings, exceeded the historical 90-second deadline and rolled back with zero committed inserts/updates. It retained no provider/normalization/ingestion/matching/commit trace. The older one-slot discovery pool deadlock, the later answer-rewrite deadlock and the archive-width defect reproduced here are separate verified defects; none establishes the cause of that historical failure.

The new three-job online measurements show ingestion as the largest initial phase. They support further investigation of persistence costs, but do not identify a specific historical bottleneck or prove that 27 online listings now fit the deadline. No live request was added to reproduce that incident, and no pool budget, ingestion concurrency or application deadline was increased. Fictional benchmark results remain fictional.

No required credential or general access grant was missing. All executed acceptance used already-approved integrations. The remaining live limitation is a suitable supported vacancy within the bounded sample, followed by exact packet/destination/value review for a genuine fill journey. New search scope or an employer submission is a separate owner decision.

No deployment, installed-service replacement, migration, paid request, recruiter email, LinkedIn message, unapproved cloud AI call, hosted Actions dispatch/rerun or real employer submission occurred. ₹0 policy is intact. The owner should review the final integration PR and its partial live acceptance before deciding whether to merge; this candidate does not merge itself.
