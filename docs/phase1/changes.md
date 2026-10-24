# Phase 1 change inventory

Feature branch: feat/phase1-local-connections, based on origin/main dcd3d2d. The delivery commit is recorded in the PR/final handoff. Historical migrations and the original checkout are preserved.

## Database schema and runtime security

- `backend/app/db/safety.py`
- `backend/app/models/application_answer.py`
- `backend/app/models/base.py`
- `backend/app/models/candidate_profile.py`
- `backend/app/operations/configuration.py`
- `backend/app/operations/health.py`
- `backend/app/operations/migrations.py`
- `backend/app/operations/readiness.py`
- `backend/app/operations/runtime_security.py`
- `supabase/fresh_public/001_phase1_public.sql`
- `supabase/fresh_public/catalog.json`
- `supabase/fresh_public/manifest.json`

## Shared preview service, policies and Telegram

- `backend/app/core/config.py`
- `backend/app/core/logging.py`
- `backend/app/local_agent/__init__.py`
- `backend/app/local_agent/contracts.py`
- `backend/app/local_agent/models.py`
- `backend/app/local_agent/native_host.py`
- `backend/app/local_agent/policies.py`
- `backend/app/local_agent/preferences.py`
- `backend/app/local_agent/public_database.py`
- `backend/app/local_agent/registry.py`
- `backend/app/local_agent/router.py`
- `backend/app/local_agent/service.py`
- `backend/app/local_agent/telegram.py`
- `backend/app/main.py`

## AI provider and Gmail OAuth

- `backend/app/ai/provider_factory.py`
- `backend/app/ai/providers/agy.py`
- `backend/app/api/v1/integrations.py`
- `backend/app/integrations/connection_service.py`
- `backend/app/integrations/google_oauth.py`

## Chrome extension

- `extension/background.js`
- `extension/build.mjs`
- `extension/manifest.json`
- `extension/package.json`
- `extension/popup.html`
- `extension/popup.js`
- `extension/settings.html`
- `extension/settings.js`
- `extension/style.css`
- `extension/tests/bridge-e2e.mjs`
- `extension/tests/preview.test.mjs`

## Dashboard and UI validation

- `frontend/src/features/connections.tsx`
- `frontend/src/features/discover.tsx`
- `frontend/src/features/local-connections.tsx`
- `frontend/src/features/search-preferences.tsx`
- `frontend/src/lib/gateway.ts`
- `frontend/src/types/api.d.ts`
- `frontend/tests/e2e/phase1-connections.spec.ts`

## Operational scripts, tests and CI

- `.github/workflows/phase1-connections.yml`
- `backend/scripts/phase1/agy_smoke.py`
- `backend/scripts/phase1/build_public_bundle.py`
- `backend/scripts/phase1/configure_database.py`
- `backend/scripts/phase1/configure_telegram.py`
- `backend/scripts/phase1/install_local.py`
- `backend/scripts/phase1/lifecycle_smoke.py`
- `backend/scripts/phase1/local_service.py`
- `backend/scripts/phase1/prepare_disposable.py`
- `backend/scripts/phase1/verify_mcp.py`
- `backend/scripts/phase1/verify_public.py`
- `backend/scripts/phase7_ui_fixture.py`
- `backend/tests/conftest.py`
- `backend/tests/test_phase1_local_agent.py`

## MCP configuration, documentation and secret hygiene

- `.claude/settings.json`
- `.gitignore`
- `.mcp.json`
- `.secrets.baseline`
- `README.md`
- `backend/.env.phase1.example`
- `docs/phase1/agy-models.json`
- `docs/phase1/audit.md`
- `docs/phase1/changes.md`
- `docs/phase1/migration-review.md`
- `docs/phase1/platform-capabilities.md`
- `docs/phase1/readiness.json`
- `docs/phase1/screenshots/connections-disposable-postgres.png`
- `docs/phase1/setup.md`
- `docs/phase1/verification.md`
