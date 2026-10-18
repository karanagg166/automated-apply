# Automated Apply roadmap

## Baseline

The existing repository contains FastAPI/FastMCP, async SQLAlchemy repositories, isolated
`job_agent` schema, credit management, discovery adapter code, matching and draft preparation.
The previous foundation roadmap is historical; adapter presence does not mean account integrations
are configured, authorized, deployed or production verified.

## Next roadmap: Phase 1 — persistent candidate foundation

Implemented and covered by automated tests:

- [x] Primary profile persistence with UUID, singleton uniqueness, timestamps and version checks.
- [x] Validated identity, career history, education, projects, certifications and search preferences.
- [x] PATCH omission/null semantics and full PUT replacement; idempotent equivalent writes.
- [x] Asynchronous repository and deterministic service; no repository commits.
- [x] Bearer-protected profile API and saved-profile job matching; fail closed without configuration.
- [x] Adapter to existing scorer and factual draft representation; unknown facts remain unknown.
- [x] Additive migration 002; isolated PostgreSQL migration/concurrency verification and SQLite coverage.
- [x] Backend CI workflow, compilation checks and offline HTTP test fixtures.
- [x] API, migration, authentication and testing documentation.
- [ ] Apply migration 002 to production after separate explicit approval.
- [ ] Enter the user's real verified profile; no fictional fixtures are seeded.

PR checks and merge are tracked in GitHub; file existence alone is not release evidence. CI runs
all backend tests including the PostgreSQL compatibility check. Local runs without the dedicated
PostgreSQL URL explicitly skip that check.

## Later phases — not implemented here

1. Extend discovery and filtering using saved preferences and permitted platform access.
   Salary, exclusions, employment types, industries and company stage are stored but do not yet
   influence the existing matching score. Hybrid/onsite distinction needs richer job data.
2. Add supported provider/account integrations with credential isolation and replace the single
   shared token with proper user/session authentication before multi-user use.
3. Integrate apply-extension and supported application workflows; keep LinkedIn connections,
   messages and submissions manual. LinkedIn discovery must use authorized/permitted methods.
4. Add contact enrichment and Gmail outreach with explicit review and sending approval.
5. Add scheduling, dashboard, resume extraction and deployment only in their approved phases.

No frontend, production infrastructure or deployment integration is added in Phase 1.
