# Phase 7 deployment preparation

**No staging database or deployment was approved or deployed.** No production migration, deployment secret, OAuth token, real owner record, paid operation, Gmail send or application submission was changed by this work.

## Operator prerequisites

1. Identify an explicitly approved isolated staging PostgreSQL/Supabase target. Verify its fingerprint using the existing Phase 6B process. Never choose a project from its name.
2. Review backups, role grants and migrations 001–010. Apply only through an authorized migration process. Migration 010 adds encrypted private resumes, owner notifications, channel outbox history and preferences. Run read-only catalog preflight afterward. An existing 001–009 installation will correctly report missing Phase 7 objects until authorized migration.
3. Configure backend secrets privately: database, owner bearer, SECRET_KEY, stable RESUME_ENCRYPTION_KEY and, when individually authorized, provider keys/OAuth encryption key ring.
4. Configure frontend **server** variables from backend/.env or the approved host’s secret store: FRONTEND_PASSWORD_HASH, FRONTEND_SESSION_SECRET, JOB_AGENT_API_TOKEN, exact FRONTEND_ORIGIN and BACKEND_ORIGIN. `frontend/.env.local` contains only appropriate non-secret origins. No NEXT_PUBLIC bearer or service-role values.
5. Terminate HTTPS at a trusted ingress, preserve exact Host/Origin, set request-size/time/rate limits and forward only trusted proxy headers. Route the existing Gmail OAuth callback to FastAPI on the same public hostname. Register exactly that callback URI with Google. Cross-host OAuth requires further routing work and is not assumed operational.
6. Run one frontend Node instance until shared login rate limiting and revocable sessions are configured. The documented single-owner boundary is not multi-user tenancy.
7. Keep sending, paid providers and external notification delivery disabled until separately consented and live-verified. Configure per-operation and monthly budgets. No background worker is started by the frontend.

## Build and start

```sh
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend run typecheck
pnpm --dir frontend test
pnpm --dir frontend run build
pnpm --dir frontend run start
```

The existing Dockerfile remains the non-root FastAPI image. It includes pypdf and the local parser worker. The frontend uses its own Node process in the **same repository**, not a second backend/microservice. Container builds exclude the frontend/node_modules and all private environment/PDF/runtime artifacts. Use the platform’s reviewed Node startup configuration for Next.js; no host was provisioned.

## Isolated demonstration

Build the frontend, install Playwright Chromium, then run `PYTHON=/path/to/venv/bin/python pnpm --dir frontend run e2e`. Playwright creates a disposable SQLite file under a temporary directory, sets `ENVIRONMENT=testing`, loads Settings with `_env_file=None`, blocks outbound provider HTTP and uses fictional fixtures. Its explicit banner distinguishes this from a live pilot. The actual FastAPI routers and persistence execute; browser routes are mocked only for a separately labeled provider-error test. The fixture process does not use or mutate backend/.env.

Screenshots and traces are test artifacts. Use `docs/phase7-frontend.md` for the exact journey. A real-data pilot requires separate target authorization, actual owner onboarding and provider consent. Opening the application link is a handoff, never a submission.

## Current blockers

- Approved staging hosting, HTTPS origins and target database identity.
- Operator installation of reviewed migration 010.
- Owner passphrase/session configuration and a stable private-resume encryption key.
- Actual resume upload, owner review of identity/history/projects/preferences, GFG conflict resolution and any optional projects.
- Original resume alias destination, currently unresolved.
- Separate secondary Gmail OAuth account/scopes and optional send consent.
- Individually configured/authorized/live-verified paid providers, account costs and budgets.
- Future notification delivery adapters and separately scoped authorized portal execution.
