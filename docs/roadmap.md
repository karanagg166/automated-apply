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

## Phase 2A — resources, knowledge base and answer drafts

Implemented:

- [x] Resume variants, original public LinkedIn, GitHub, portfolio and coding-profile URLs.
- [x] Deterministic resolver with explicit provenance, ambiguity handling and upload distinction.
- [x] Non-overwriting environment defaults and explicit dry-run/apply import command.
- [x] Confirmed evidence and richer attributable project facts; deterministic retrieval.
- [x] Deterministic exact facts and missing-information results without model calls.
- [x] Provider abstraction and supported Gemini SDK with bounded structured generation.
- [x] Durable atomic monthly request accounting, reported token usage and per-worker concurrency.
- [x] Server-side evidence/claim/length validation; narratives always require review.
- [x] Protected APIs, explicit draft persistence, review states and profile-version staleness.
- [x] Additive migration 003 and offline SQLite/PostgreSQL migration/concurrency tests.
- [x] Read-only extension architecture inspection and stable typed integration contract.
- [ ] Apply migration 003 to production after separate approval.
- [ ] Configure and assess live Gemini output with the user's own approved account/data.
- [ ] Extend staleness to revisions of individual evidence/resource dependencies.

## Phase 2B — job and startup discovery (next)

Use the persisted profile, resources, evidence and reviewable answer contract when expanding
permitted job/startup discovery. Enrich job metadata before changing matching weights or
hybrid/onsite handling. Keep account credentials isolated and implement authenticated extension
integration separately. Phase 2A adds no platform submissions, messaging, resume downloads,
Drive OAuth, dashboard or deployment. GitHub checks and merge status are the release evidence.
