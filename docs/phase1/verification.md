# Phase 1 verification and remaining acceptance

Status: implementation reviewable; owner acceptance pending. No merge to main, remote DDL, real application submission, email send, authenticated-platform scraping or enrichment request was performed. Two separately authorized fictional AGY invocations produced no usable response/attempt usage (latest: timeout). Paid overage was not authorized; neither attempt was automatically retried. After owner sign-in, CLI-handled authentication/quota metadata succeeded with zero model turns. No further generation is authorized.

## Executed commands and evidence

Use `.venv/bin/python` from this worktree. All database passwords below are disposable fictional fixtures, never production credentials.

| Command | Result / evidence |
|---|---|
| `PROFILE_TEST_DATABASE_URL=postgresql://postgres:phase1_disposable_only@127.0.0.1:55440/candidate_profile_test .venv/bin/python -m pytest backend/tests -q` | Full backend regression with disposable PostgreSQL 17. 1,390 passed, no skips (152.32s) |
| `.venv/bin/python -m pytest backend/tests/test_phase1_local_agent.py backend/tests/test_telegram_pairing.py -q` | 142 foundation/pairing/security cases passed (6.85s), including billing/workspace trust guards, zero-turn metadata parsing, backlog/empty polls, fresh challenge identity and HTTP 409 conflict handling |
| `npm run typecheck --prefix frontend` | Passed |
| `npm test --prefix frontend` | 39 tests passed |
| `npm run format:check --prefix frontend` | Passed |
| `npm run build --prefix frontend` | Production build passed |
| `PYTHON=/private/tmp/automated-apply-phase1/.venv/bin/python npm run e2e --prefix frontend` | 8 actual Next.js/BFF/FastAPI browser journeys passed (45.1s), including policy/filter persistence and CSRF; fictional SQLite fixture only |
| `node extension/build.mjs` | MV3 build and permission manifest assertions passed |
| `node --test extension/tests/*.test.mjs` | 7 extension event tests passed; Chrome APIs are simulated |
| `PHASE1_DISPOSABLE_DATABASE_URL=postgresql://postgres:phase1_disposable_only@127.0.0.1:55441/candidate_profile_test .venv/bin/python backend/scripts/phase1/verify_public.py --bootstrap` | Fresh bundle applied on a separate disposable PG17 container, 47 tables, forced RLS/restricted-role checks passed |
| `PHASE1_DISPOSABLE_DATABASE_URL=postgresql://postgres:phase1_disposable_only@127.0.0.1:55441/candidate_profile_test .venv/bin/python backend/scripts/phase1/prepare_disposable.py` | Private fictional runtime login/config generated only on owned disposable cluster |
| `.venv/bin/python backend/scripts/phase1/lifecycle_smoke.py --env-file reports/phase1/disposable.private.env --with-chromium-extension` | Actual native framing with open stdin → loopback HTTP → restricted PostgreSQL; actual isolated Chromium MV3 native APIs and popup; simulated context-menu events/Telegram transport; persisted previews/preferences recovered after actual API restart; one-slot pool /status and duplicate-worker lock tested |
| `.venv/bin/python backend/scripts/phase1/verify_mcp.py` | Actual Codex OAuth tool discovery and four harmless read calls; exact project URL, zero public tables, zero migrations. No AI turn |
| `claude mcp list` | New project-scoped server reports pending owner approval |
| `agy mcp list` | Prior enabled supabase retained; new named server registered disabled |
| `agy --version`, `agy --help`, `agy models`, `agy agents` | 1.4.6; headless/schema/sandbox/high effort available; model list fetched; installed global tool-free primary profile discovered |
| `.venv/bin/python backend/scripts/phase1/agy_smoke.py --model gemini-3.8-flash-high --owner-authorized-one-fictional-request` | One initial fictional CLI invocation interrupted after workspace-profile discovery failed. No valid response or usage report, no retry. A global restricted profile was subsequently installed and discovered using metadata only |
| `.venv/bin/python backend/scripts/phase1/agy_smoke.py --model gemini-3.8-flash-high --attempt-id owner-approved-followup --owner-authorized-one-fictional-request` | Exactly one additional owner-authorized fictional attempt after adapter tests; model gemini-3.8-flash-high, high effort, 90-second timeout, no validated output/attempt usage. No retry. Billing guard checked disabled G1-credit overage and excluded API/Cloud billing |
| `.venv/bin/python backend/scripts/phase1/agy_check.py` | Actual authenticated CLI-handled /usage metadata, SUCCESS, zero model turns and all token counters zero. Gemini quota reported 59% weekly / 97% five-hour remaining at 2026-10-24T22:22:36Z; this does not determine usage of failed generation attempts |
| `.venv/bin/ruff check --isolated --select E9,F,I backend/app/local_agent backend/app/ai/providers/agy.py backend/scripts/phase1 backend/tests/test_phase1_local_agent.py` | Passed |
| `.venv/bin/bandit -q -r backend/app` | Passed; existing harmless nosec bookkeeping warning only |
| `.venv/bin/python -m compileall -q backend/app backend/scripts/phase1` | Passed |
| `git diff --check` | Passed |
| `npm audit --audit-level=high --prefix frontend` | Zero vulnerabilities |
| `.venv/bin/python backend/scripts/export_openapi.py` then `npm run api:types --prefix frontend` and `git diff --exit-code -- frontend/src/types/api.d.ts` | Generated API contract matches committed file |
| `.venv/bin/detect-secrets-hook --baseline .secrets.baseline --no-verify <all changed and new source files>` | Passed; no new secret candidates; no verification requests to providers |

A separate standalone UI smoke logged into the real production Next.js build on 127.0.0.1:18083 with fictional owner credentials and the actual restricted PostgreSQL-backed API on 127.0.0.1:18081. It verified Supabase remained degraded/test-only while Codex MCP showed verified read-only metadata, Chrome showed the owner result correlated with audit, and AGY showed authenticated metadata with generation still degraded. [Screenshot](screenshots/connections-disposable-postgres.png). The full-page browser-fixture screenshot is retained locally in reports/phase1-connections.png. Neither is evidence of a live Supabase SQL connection or real Chrome extension gesture.

## Security outcomes

New tests reject wrong project/admin runtime credentials, missing/unsafe configuration, TLS certificate failures, malformed/oversized native frames, unauthorized extension identity, arbitrary commands, invalid/unsafe URLs, hostile title instructions, disabled-platform invocation, replayed request IDs, request-ID conflicts, wrong Telegram users/chats, shell-command messages, webhook conflicts, malformed AI JSON, missing tool-free profile, unapproved generation, timeout and nonzero CLI exits. They verify redaction and policy overrides cannot enable submission, Gmail sending or paid calls. Existing OAuth callback/state/PKCE, MCP authentication/permissions, encrypted tokens/resumes, application safety and provider budget suites remain intact.

The installed native executable additionally rejected wrong origins (`native_origin_denied`), oversized frames (`native_message_size`) and malformed JSON (`native_invalid_message`) in actual subprocess checks.

Actual disposable SQL tests rejected five forbidden runtime statements and seven injected faults: anonymous grant, disabled RLS, privileged runtime role, broadened policy, extra DELETE, unsafe default grants, and cross-schema access. Non-TLS and administrator runtime connections were rejected, and replay of the fresh-only bundle was refused atomically. No destructive test used remote Supabase.

Secret baseline changes are limited to reviewed fictional test credentials, DDL field names and migration/catalog SHA-256 values. No production secret, bot token, OAuth token, personal resume or DB URI is committed. Original worktree changes and historical migration checksums are preserved.

## Live acceptance still pending

- Supabase CLI/management owning account, rotated restricted/admin credentials, full catalog/role/grant inventory, reviewed bundle approval, genuine TLS SQL, runtime FastAPI health, isolated persistence/cleanup and restart test. MCP verified project access independently; CLI's current account did not list the new project. Region/status/server version remain unverified through management/direct SQL. The owner explicitly deferred credential rotation; it remains pending. The separate automated-apply CLI profile preserves the old account.
- Chrome Google Form and owner extension/backend restart acceptance remain pending. The owner reported the real extension popup returning a saved preview for https://search-sphere-rose.vercel.app/search, with HTTPS menu registration, following the menu repair instructions. This matches backend actor chrome:hmkhgcgjjnjncamgdlabocdbgpleebgk and correlation 38d559b3-2426-45d5-a7aa-246249743c99 at 2026-10-24T22:10:24.325565Z. This is owner-reported browser evidence correlated with actual SQL, not an independently observed right-click gesture. The separate Chromium test uses actual MV3/native APIs but simulates menu events.
- Telegram: owner reports successful token verification, but the original one-shot setup returned an empty candidate list. Repaired setup now uses bounded long polling, backlog pagination, a fresh private challenge, strict observed numeric identity approval, and distinct HTTP 409 poller/webhook errors. No Automated Apply worker or matching launchd job was found locally during diagnosis; this does not rule out an external poller. Owner retry succeeded: private numeric identity is saved, and an actual getMe/getWebhookInfo verification succeeded at 2026-10-24T22:39:02Z with no webhook. Real polling acknowledgments remain pending. Webhook changes require separate approval.
- Explicit launchd installation from a stable checkout, worker failure recovery and actual awake-but-screen-locked phone /ping. No power settings changed.
- AGY structured response remains unverified after two separately authorized failed attempts. Owner authentication/trust is now verified through a non-generation metadata check. No further generation is authorized. Existing owner hooks are preserved. See live-evidence.json and agy-models.json for actual model discovery, statuses and quotas.
- Claude project MCP owner approval/OAuth/read call; AGY per-tool MCP restrictions/OAuth; old global server's live read operation (configuration preservation is verified).
- Gmail identity/compose consent and verified granted scopes; no actual draft without separate consent. Provider entitlements remain unverified.

The native host currently points at a disposable fictional backend, not live Supabase. Its temporary worktree path must be replaced with a stable owner-reviewed checkout before persistent launchd use/reboot. Test PostgreSQL containers are named automated-apply-phase1-pg, automated-apply-phase1-regression-pg and automated-apply-phase1-fresh-pg; no existing unrelated container was changed.

## Proposed Phase 2 (not started)

After Phase 1 owner acceptance: reuse reviewed PR 17 packet/answer/resume/browser pieces selectively; add permission-reviewed DOM inspection and grounded question mapping on owner-controlled forms; enforce durable approval before any fill/upload/submission; bind verified receipts and application deduplication. Add owner-consented Gmail draft creation with sending permanently manual, and source-by-source permitted discovery activation. Automatic platform preferences remain subordinate to actual authorized capabilities.
