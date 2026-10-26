# Phase 1 integrated answer service — 2026-10-26

The extension reliability and deterministic answer branches are integrated with history preserved on `feat/phase1-local-connections`. PR #18 stays draft and must not merge into main. This checkpoint does not claim that the complete automated application agent is production-ready.

## Integration and delivered behavior

- `5385204` merges PR #21 head `5127bcfd19eff2a77bb87efc84b87a0b6611b780`.
- `3611c5b` merges PR #20 head `bac0e84404fd09fbc6a6c1b2f1ed8553b734a0e6`.
- `bb7e114` connects `LocalAnswerEngine` to `ApplicationAnswerService` using `local-answer-integration.v1`. REST answer generation and application packet generation use approved evidence extraction by default. Provider construction, quota reservation and local inference do not occur on deterministic routes.
- Grounded output is `deterministic_extractive`, `used_llm=false`, no provider/model/usage, with genuine evidence references and mandatory narrative review. Missing facts become `needs_input` with no answer, citations, draft or model request. Terminal grounding/length failures expose no candidate answer. Profile/resume resolution remains in its original branches.
- Optional cloud writing requires an explicit `rewrite` request and cannot bypass missing-fact or terminal preparation failures. Ollama and AGY execution is rejected by this shared service. Existing explicitly selected outreach writing remains explicit; Gmail approval and sending boundaries are unchanged.
- Drafts retain candidate versions and stale-draft review rejection. Packets record deterministic provenance instead of falsely labelling extracted answers as Gemini output. No migration or live schema change was needed.
- `86035b1` adds the disabled Cohere V2 evaluation adapter. See [its contract and acceptance gates](../agent/cohere.md). `3ab78b6` adds preparatory command/plan contracts and tests; these are not a running agent/executor or a new Telegram workflow.

## Verification

All heavy local runs use `/tmp/automated-apply-heavy-tests.lock`. PostgreSQL is a newly created disposable local PostgreSQL 17 container; owner Supabase and candidate records are not test targets.

| Check | Local result |
| --- | --- |
| Full backend, including PostgreSQL migration/concurrency/recovery tests | 1,771 passed, zero failed/skipped; 156.45 seconds; two existing pypdf deprecation warnings |
| Frontend unit tests | 47 passed |
| Frontend type checking, formatting, generated OpenAPI contract, production build | Passed |
| Real frontend Playwright journeys | 9 passed against isolated fictional FastAPI/BFF fixtures |
| Extension build and tests | 27 passed; unchanged ID `gdjbmkffcpicbpiikcohlmokkmcpipgp` |
| Extension Chrome/native/PostgreSQL acceptance | 23/23 passed in real Chrome for Testing 156; 21 unique correlations and 22 audit rows; zero form reads/fills/POSTs |
| Non-root standalone frontend container | Build, login, anonymous/CSRF rejection, HttpOnly cookie and missing-backend fail-closed checks passed |
| Ruff, whole-backend Bandit, pip check | Passed; existing harmless Bandit nosec annotation warning remains |
| Pinned Python and pnpm dependency audits | No known vulnerabilities |
| Secret checks | Passed; only a clearly fictional test key is allowlisted inline. Existing baseline classifications/detectors are unchanged; one existing line offset was refreshed |
| GitHub Actions | Must be verified against the final pushed SHA, not historical successful checks |

The extraction tests cover service/API output, missing numeric facts even when rewriting is requested, no provider/quota use, unsupported facts, untrusted job context, packet provenance, saved drafts and stale review rejection. Cohere tests use realistic mocked V2 envelopes, not live model output. Preparatory command tests cover searches, startup/internship follow-ups, previous-result selections, project preference, status, cancel/stop, ambiguous commands and attempted authorization injection.

CI and container JavaScript commands use pinned pnpm and its frozen lockfile. The historical package-lock is preserved but is not used by these builds.

## Acceptance gates and remaining work

No key was configured for Cohere. Its model access, evaluation-key status and account quota are not live verified. Cohere activation, owner-text transfer and candidate-data transfer are separately disabled. Initial authorized evaluation must use fictional data; personal resumes and approved facts need separate consent before cloud transfer. Zero live Cohere requests were made.

Ollama authorization, AGY activation/quota and Telegram local AI are disabled. Extraction does not count as an accepted model generation. Existing resume encryption keys/history, Gmail credentials, Telegram pairing, extension identity, Supabase RLS and LinkedIn discovery-only restrictions are preserved.

The owner must review current profile facts, approved project context and the canonical PDF. A tested code branch is not a live redeployment: the installed local backend/frontend and worker were left intact. A rollout and genuine owner-approved end-to-end workflow remain acceptance work.

The existing Telegram knowledge adapter, dashboard, job discovery and preview-only native boundary remain available at their established scope. The preparatory planner is not wired to a permissioned executor, durable application campaigns, Chrome form inspection/autofill/submission, or a new Telegram command loop. Those later master-prompt phases remain unfinished; an uncommitted tool-registry draft is preserved locally without being shipped as a completed capability.

Naukri, Wellfound, Instahyre, YC and Internshala sign-in indicators are not application API authorizations. Unknown eligibility/company size/salary remains unknown. No real application, email, paid account, hosting deployment or live DDL was performed. Real portal execution needs separately accepted platform/campaign limits and authoritative confirmation.

An awake, locked Mac may continue its local worker; sleep/offline interrupts local Chrome availability. A cloud model does not make laptop browser work available when the Mac sleeps. No always-on cloud control plane was deployed, and no new locked-screen live claim is made by these fixture regressions.
