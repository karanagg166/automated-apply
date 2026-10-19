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

1. Phase 2B adds a discovery-specific preference overlay; the legacy assistant stays compatible.
   Industry preferences await reliably normalized company industry evidence.
2. Add supported provider/account integrations with credential isolation and replace the single
   shared token with proper user/session authentication before multi-user use.
3. Prepare supported applications within this standalone backend; keep LinkedIn connections,
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
- [x] Typed application answer contracts. Historical extension exploration is superseded by the standalone architecture decision below.
- [ ] Apply migration 003 to production after separate approval.
- [ ] Configure and assess live Gemini output with the user's own approved account/data.
- [x] Phase 5A packet staleness covers evidence/resource dependencies; historical standalone answer drafts keep profile-version staleness.

## Phase 2B — job and startup discovery

Implemented and covered by offline tests and disposable PostgreSQL verification:

- [x] Explicit source registry; Naukri/Instahyre/Wellfound/YC preserve platform identity.
- [x] Bounded direct feeds, structured outcomes, safe URLs and evidence-only normalization.
- [x] Opt-in reviewed Apify mappings with pinned builds, terminal runs and durable cost caps.
- [x] Additive migration 004; job observations, discovery runs and public people evidence.
- [x] Conservative ATS/content identities, possible duplicates, savepoints and preserved human state.
- [x] Saved-profile deterministic ranking, exclusions, unknown salary and explicit remote policy.
- [x] Protected REST discovery, planning-only preview, manual import and bounded job search.
- [x] Read-only professional URL discovery via permitted search index/manual evidence.
- [x] Startup metadata linked to companies/jobs when actually supplied by a source.
- [ ] Configure/review specific paid actors and verify permitted live platform connections.
- [ ] Configure and live-verify Serper with the user's authorized account.
- [ ] Verify a legitimate Internshala connector; currently manual import only.
- [ ] Apply migration 004 to production after separate explicit approval.
- [ ] Recover/reconcile crash-interrupted runs and final provider invoices if operationally needed.

See [job-discovery-pipeline.md](job-discovery-pipeline.md) for the honest platform matrix and limits.
No account passwords, LinkedIn outbound actions, applications, production migration or deployment.
GitHub PR and CI state are release evidence, not an indication that paid accounts were connected.

Phase 3 contact enrichment is implemented below. The next milestone is the separately scoped
Gmail outreach draft/review workflow.

## Phase 3 implementation status

Implemented: local-first professional contact enrichment; Phase 2B people bridge; mock-tested Apollo and SignalHire synchronous adapters; explicit cost/authorization gates; durable concurrency-safe reservations and lookup claims; contact identities and append-only evidence; suppression/human corrections; email verification guards; contextual recommendations; protected APIs; additive migration 005 and disposable PostgreSQL verification. See [contact enrichment](contact-enrichment.md).

Not live verified: provider credentials, account eligibility, authentication, provider enrichment or mailbox verification. No production migration, deployment or outbound communication was performed.

Phase 4A implements the separately scoped connection/local-draft foundation below. Sending remains Phase 4B.


## Phase 4A implementation status

Implemented: authenticated disabled-by-default MCP, centralized permissions and audit, saved-profile
read tools, connector capability status, secondary Gmail authorization-code/PKCE connection with
durable replay protection and encrypted tokens, and grounded local outreach drafts with revision,
recipient/evidence snapshots, editing, rejection and approval. Migration 006 has disposable
PostgreSQL verification. No provider email writes, sends or application submissions are included.
Live OAuth/Gemini/provider connectivity still requires owner-supplied credentials and explicit
account authorization. Production migration/deployment remain separately authorized work.

## Phase 4B — Approved Gmail Sending and Acceptance Tracking

Implemented: explicit identity-bound gmail.send upgrade using the existing PKCE/token store;
owner REST send preview and separate single-use exact-content confirmation; current approval,
mailbox evidence and suppression checks; safe one-recipient MIME; one committed reservation
per draft; cross-worker caps and idempotency; acceptance/unknown history and manual audited
reconciliation. Migration 007 preserves prior records and supersedes the 006 guard safely.
No Gmail send MCP tool, background scheduling, automated follow-ups or delivery/read claims.
See [approved sending](gmail-approved-sending.md). Live OAuth/send authorization and production
migration/deployment remain owner-operated work; implementation/CI send no real messages.

## Phase 5A — Naukri application preparation, review and tracking

The `apply-extension` repository is not a dependency of Automated Apply and is not part of the
approved project scope. This supersedes historical references to extension integration.
The existing FastAPI/PostgreSQL/FastMCP/Gemini modular backend remains the execution boundary;
there are no additional deployable services or browser dependencies.

Implemented: saved-job preview, confirmed profile/link mapping, explicit or unique confirmed primary
resume selection, user-entered screening schemas, reuse of grounded Gemini answers, missing-data
readiness, durable packet/field revisions, stale evidence detection, human review and exact approval,
manual Naukri/employer URL handoff, explicit self-reported completion and independent outcome
tracking. Five read-only MCP tools share the REST services. Migration 008 adds backend-only tables,
append-only history, submission guards and isolated PostgreSQL concurrency verification.

Not performed: production migrations/deployment, live Naukri login or endpoint calls, live Gemini
generation, actual browser actions, file uploads or application submissions. See
[application preparation](application-preparation.md) and [handoff](naukri-application-handoff.md).

## Next: Phase 5B — Supported Browser/Application Execution Without apply-extension

First independently verify a permitted integration method using authoritative provider documentation
or an explicit authorization agreement. Browser automation needs its own architectural and
provider-permission review. No execution architecture or implementation is pre-approved; private
portal endpoints, imported sessions, CAPTCHA/MFA bypass and automatic mass applications remain
outside scope. Phase 5B is not implemented automatically as part of Phase 5A.

## Phase 6A — startup discovery and professional intelligence

Implemented with focused mock tests and disposable PostgreSQL verification:

- Company-first permission-confirmed observations without jobs; job-led discovery composes existing services.
- Small-company bands, explicit unknown/conflict handling, historical evidence, conservative identities.
- Hiring signals, saved-profile relevance, reviewed shortlists, bounded deterministic search.
- Existing official/public professional research client with separate retention-rights and paid-call gates.
- Existing contact identity reconciliation, suppression and evidence; cached read-only startup MCP tools.
- Protected REST and durable, expiring provider diagnostics with atomic cross-worker source pacing.
- Additive migration 009, offline full-flow demonstration, actual bounded HN/Greenhouse/Remotive/Arbeitnow checks.

Not verified or enabled: automated YC directory access, a licensed Wellfound/YC actor, real Serper
professional research, account-specific paid pricing/permissions, production data ingestion or deployment.
Company-first automated collection honestly reports unsupported; permitted manual imports work.
Apply migration 009 and configure real profile/source rights only under separate environment authorization.
Historical actual smoke evidence is in [the source report](phase6a-live-verification.json); current
availability is determined by fresh checks in the operator's database.
