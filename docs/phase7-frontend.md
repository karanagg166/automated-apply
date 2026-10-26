# Phase 7 frontend

The Next.js App Router application lives in `frontend/` and uses the existing FastAPI backend. It is a private, single-owner workspace. It never contains seeded production counts or provider credentials. The isolated browser demonstration uses fictional fixtures against the actual API and labels them explicitly.

## Run locally

Use Node 22+ and Python 3.11+. Install `backend/requirements.txt` into a virtual environment and run `pnpm -C frontend install --frozen-lockfile`. Keep the existing `backend/.env`; do not replace it with the example. Configure an explicitly selected local PostgreSQL database using the documented migration process. Migration 010 adds only owner dashboard tables; no production database was changed during implementation.

Generate owner-login material privately with `python backend/scripts/configure_frontend_owner.py`. This prompts for a passphrase and creates a new, ignored, mode-0600 `backend/frontend.private.env`. Review and add the entries to `backend/.env` using a local editor after backing it up. Preserve an existing resume encryption key. No values are printed and existing files are never replaced. Create `frontend/.env.local` from `frontend/.env.example` with origins only.

From the repository root:

```sh
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
pnpm -C frontend dev
```

Open `http://localhost:3000`. `frontend/run.mjs` loads `backend/.env` into the Next.js **server** process. Browser code only calls the same-origin BFF. The login requires the owner passphrase; there is no default password and no anonymous development bypass.

## Screens

| Route | Function |
| --- | --- |
| `/` | Actual database metrics, profile readiness and navigation |
| `/profile` | Private PDF import, editable career facts/projects, exact public-link proposals, GFG conflict review, preferences and final owner confirmation |
| `/discover` | Preview and explicitly run bounded free public-source discovery |
| `/startups` | Database searches, exact-size filters, location/technology/role/hiring/status filters, shortlist, saved presets, pagination and conservative reference export |
| `/startups/:id` | Source observations, hiring evidence, jobs, professional contacts and explicit research/enrichment plans |
| `/jobs` | Real status/skill/location/title filters, optional candidate matching, shortlisting and packet preparation |
| `/people` | Saved company contact evidence, mailbox status, suppression, optional authorized enrichment and local outreach drafts |
| `/applications` | Board/table over existing lifecycle and tracking states |
| `/applications/:id` | Answers, edits, provenance, revision-specific review/approval, manual handoff, submission reporting and timeline |
| `/outreach` and `/outreach/:id` | Persisted local drafts, edits, evidence eligibility, approval, exact send preview/confirmation and attempt history |
| `/connections` | Runtime configuration, authorization, live-verification distinctions, budgets, Gmail OAuth and manual portal capabilities |
| `/notifications` | Private deduplicated in-app updates and read state |
| `/settings` | Per-owner notification opt-in, pause, quiet hours and daily digest |

The visual system uses neutral surfaces, a restrained lime accent, a persistent workspace shell, accessible dialogs, consistent form controls, skeletons, explicit error/empty states and responsive navigation. `next-themes` supplies light/dark modes; reduced-motion preferences disable transitions. Tables use TanStack Table; forms use React Hook Form/Zod and queries use TanStack Query. No charts are shown without meaningful data.

## Data semantics

The exact **2–10** option requires a fresh, nonconflicting numeric employee count in that range. A 1–10 band does not prove 2–10. Location, stack, YC/stage and hiring attributes require the existing evidence service. Unknown evidence remains labeled. All filters query saved data and never execute paid providers.

“Not Applied” excludes actual submission states and legacy independently marked applied jobs. Prepared, approved and externally opened packets remain not applied. User-reported and provider-confirmed submissions stay distinct. Startup filtering considers matching jobs and preserves application history.

Exports include only company name/domain/source references whose retained sources are exclusively manual or Greenhouse. Contacts and restricted-provider records are excluded; exports do not imply broader redistribution rights.

## Tests and demonstration

```sh
python backend/scripts/export_openapi.py
pnpm -C frontend api:types
pnpm -C frontend typecheck
pnpm test --prefix frontend
pnpm -C frontend build
cd frontend
pnpm exec playwright install chromium
PYTHON=/absolute/path/to/venv/bin/python pnpm e2e
```

Playwright starts a temporary SQLite database and the actual FastAPI application, blocks outbound provider HTTP, uploads a synthetic PDF, reviews links, saves a fictional profile, searches India + numeric 2–10 + Python + Backend Engineer + Not Applied, opens hiring/contact evidence, prepares and approves a local outreach draft with Gmail sending disabled, prepares and edits a packet, approves it and records manual handoff/submission. Separate checks exercise auth/CSRF, unavailable-provider feedback, notification persistence, desktop/mobile layout, theme, accessibility and secret exposure. Screenshots go to ignored `reports/phase7-*.png`; CI uploads only isolated artifacts. These are not a live-data pilot.

API types are generated from the existing FastAPI OpenAPI contract into `frontend/src/types/api.d.ts`; CI detects drift. Provider execution has no mutation retries. An uncertain send must be reconciled, never automatically repeated.


## Captured isolated demonstration

All images below show the actual frontend and FastAPI with **fictional test fixtures**, never a live-data pilot:

- [Exact startup filters, desktop](screenshots/phase7/phase7-startups-desktop.png)
- [Dark theme](screenshots/phase7/phase7-startups-dark.png)
- [Mobile layout](screenshots/phase7/phase7-startups-mobile.png)
- [Owner link review](screenshots/phase7/phase7-onboarding.png)
- [Application review and manual handoff](screenshots/phase7/phase7-application-review.png)

Verified locally: 1,048 backend tests (zero failures/skips, including disposable PostgreSQL), 26 frontend unit/component/security tests, five Playwright journeys, zero axe violations in light/dark startup views, type checking, production build, Ruff, Bandit, npm audit, secret checks and non-root Docker build/import plus Linux PDF-worker verification. CI must additionally pass on the PR head.
