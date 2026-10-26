# Repository Guidelines

## Project Structure & Module Organization
- `backend/app/` contains FastAPI routes, services, repositories, models, AI providers, and local-agent integrations. Backend tests live in `backend/tests/`; operational tools live in `backend/scripts/`.
- `frontend/src/` contains Next.js routes, components, features, and API helpers. Unit tests live in `frontend/tests/`; browser journeys live in `frontend/tests/e2e/`.
- `extension/` contains the Chrome MV3 extension, assets, build script, and tests.
- `supabase/` holds SQL migrations; `candidate_context/templates/` holds profile templates; `docs/` holds setup guidance.

## Build, Test, and Development Commands
- Use Python 3.11+, Node.js 22+, and pip. Use pnpm exclusively for JavaScript dependencies and scripts; do not use npm, npx, or yarn. Run from repository root:

```sh
python3.11 -m venv backend/venv
source backend/venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.app.main:app --reload --port 8000
pnpm -C frontend install
pnpm -C frontend dev
pnpm -C frontend build
pnpm -C frontend typecheck
pnpm -C extension build
```

## Coding Style & Naming Conventions
- Use four-space Python indentation, snake_case modules/functions, and PascalCase classes. Keep HTTP handlers thin and business logic in services/repositories.
- Use Prettier, two-space TypeScript indentation, PascalCase React components, and kebab-case filenames.
- Check individual Python files with `ruff check --isolated --select E9,F,I path/to/file.py`; check frontend formatting with `pnpm -C frontend format:check`.
- Regenerate API types after contract changes: `python backend/scripts/export_openapi.py`, then `pnpm -C frontend api:types`.

## Testing Guidelines
- Backend: pytest with pytest-asyncio; name files `test_*.py`. Run `pytest backend/tests -v` or target one file.
- Frontend: Vitest/Testing Library (`pnpm -C frontend test`); name tests `*.test.ts` or `*.test.tsx`. Playwright uses `*.spec.ts`; build first, install Chromium, then run `pnpm -C frontend e2e`.
- Extension: `pnpm -C extension test` runs Node's test runner against `*.test.mjs`.
- Add regression tests for behavior changes. No coverage threshold is configured. PostgreSQL integration tests require a disposable `PROFILE_TEST_DATABASE_URL`; follow backend CI configuration.

## Commit & Pull Request Guidelines
- Follow observed scoped subjects such as `feat(ai): ...`, `fix(ai): ...`, and `security(extension): ...`.
- Describe the problem, behavior, and validation; link issues and include screenshots for UI changes. Explain migration and configuration changes.
- AI-authored commits must include a `Co-Authored-By:` trailer identifying the agent/model.

## Security & Configuration
- Start from `backend/.env.example` and `frontend/.env.example`. Keep credentials, candidate data, and private reports out of commits.
- Real data requires owner-approved online PostgreSQL; SQLite is for fictional fixtures/tests. See `docs/online-postgresql.md`.
- Preserve explicit owner approval for sending/application actions and opt-in provider budgets; tests must use isolated fixtures.
