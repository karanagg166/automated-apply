# Automated Apply

## Persistent database requirement

All genuine application data uses owner-approved online Supabase PostgreSQL in
`job_agent`. SQLite is restricted to automated tests and fictional fixtures.
Missing/unsafe database configuration or an unavailable database fails closed;
the API never falls back to SQLite. See the [online database setup and acceptance
procedure](docs/online-postgresql.md) and [current evidence/blockers](docs/database-correction-evidence.md).

## Phase 7 private dashboard

A premium Next.js frontend now lives in `frontend/`. It connects to the existing FastAPI APIs through an authenticated server-side proxy. It includes startup/job filters, source and contact evidence, private resume onboarding, application review/manual handoff, local outreach/Gmail approval screens, connection readiness and in-app notifications.

Start with [frontend setup](docs/phase7-frontend.md), [candidate onboarding](docs/phase7-profile-onboarding.md), [account connections](docs/phase7-account-connections.md), [notification boundaries](docs/phase7-notifications.md), [security](docs/phase7-security.md) and [deployment blockers](docs/phase7-deployment.md). Existing backend setup and workflows remain below. No staging environment, real profile or provider connection is implied by the UI.

```sh
npm ci --prefix frontend
npm run build --prefix frontend
npm run dev --prefix frontend
```

Configure the private owner login in `backend/.env` before signing in. No default login or client-side bearer token exists. For a reproducible demonstration against the actual backend with isolated fictional fixtures, see the Playwright commands in the frontend guide.

My Profile also supports [Google Drive resume sync](docs/google-drive-resume-sync.md): explicit secure PDF download, encrypted version history, deterministic evidence differences and owner-approved profile/resource activation. A separately invoked, opt-in worker can check the same file every 24 hours. No worker is started by configuration or API startup; the dashboard reports its actual heartbeat.

# Job Pulse Agent (`job-pulse-agent`)

An AI-powered job discovery, recruiter contact enrichment, and personalized cold outreach platform designed with strict Human-in-the-Loop (HITL) safety, zero-surprise cost management, and modular architecture.

---

## Current backend capabilities

- Persistent, user-supplied candidate facts and job search preferences.
- Authenticated profile management and deterministic saved-profile matching.
- Protected multi-source discovery runs, manual imports, observation history, conservative deduplication and profile ranking.
- Public professional URL discovery through configured search or manual evidence; LinkedIn outreach stays manual.
- Existing company/job/contact repositories, budget reservations and factual draft preparation.
- Protected founder/recruiter contact enrichment, provenance, suppression and contextual recommendations; paid providers default to disabled.
- Authenticated, opt-in Streamable HTTP MCP tools using saved candidate facts; LinkedIn actions remain manual.
- Reviewed Gmail sending with separate OAuth authorization, owner confirmation and durable audit history.
- Standalone Naukri application packets: saved-profile mapping, confirmed resume selection, grounded screening drafts, revision-specific approval, manual handoff and self-reported completion.

Paid platform actors require reviewed configuration and explicit budgets; no actor or account is pre-verified. See [the discovery pipeline](docs/job-discovery-pipeline.md) for source status, API examples, migration 004 and test instructions.

Automated submissions, background scheduling and a dashboard remain future work. The diagrams below describe the target architecture, not deployed components. Automated Apply is a modular backend; the `apply-extension` repository is not a dependency or part of its approved scope.

---

## 🏗️ Architecture Overview

```text
                    USER
                     │
                     ▼
             NEXT.JS FRONTEND (Phase 4)
            Dashboard + AI Chat
                     │
                     ▼
               BACKEND API
            FastAPI + FastMCP (Phase 1)
                     │
         ┌───────────┴───────────┐
         ▼                       ▼
   AI ORCHESTRATOR          TASK SCHEDULER
   (Tool Calling)         (Discovery Workers)
         │                       │
         └───────────┬───────────┘
                     ▼
              MCP TOOL LAYER
    ┌────────────────┬────────────────┐
    ▼                ▼                ▼
JOB DISCOVERY   ENRICHMENT       GMAIL AGENT
(Feeds/Alerts)  (Waterfall)      (Drafts/Auth)
    │                │                │
    └────────────────┼────────────────┘
                     ▼
               SERVICE LAYER
                     │
                     ▼
           SUPABASE POSTGRESQL
       (Isolated `job_agent` Schema)
```

---

## 🚀 Quickstart (Backend Development)

### Prerequisites

- Python 3.11+
- Git
- Access to Supabase PostgreSQL instance (dedicated `job_agent` schema)

### 1. Environment Setup

```bash
# Create virtual environment
python3.11 -m venv backend/venv

# Activate virtual environment
source backend/venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt
```

### 2. Configuration

Copy the example environment file and configure your credentials:

```bash
cp backend/.env.example backend/.env
```

### 3. Run Test Suite

```bash
pytest backend/tests -v
```

### 4. Start Development Server

```bash
uvicorn backend.app.main:app --reload --port 8000
```

---

## 📚 Project Documentation

- [Architecture & System Design](docs/architecture.md)
- [Architectural Decision Records (ADRs)](docs/decisions.md)
- [Implementation Roadmap & Progress](docs/roadmap.md)
- [Phase 3 Contact Enrichment](docs/contact-enrichment.md)
- [Phase 1 Implementation Plan](docs/plans/2026-10-14-phase-1-backend-foundation.md)

---

## 🛡️ Non-Negotiable Safety Principles

1. **Account Protection:** No browser automation on authenticated personal sessions, no session cookie harvesting.
2. **Strict HITL:** The system prepares drafts and normalizes data autonomously. Phase 4A records approval for local drafts; sending is reserved for Phase 4B.
3. **Cost-First Budgeting:** Cached data is reused first, free tiers are prioritized, and external API calls fail safe when budgets are reached.
4. **Database Isolation:** All application tables reside in the `job_agent` schema, completely segregated from other projects and existing public tables.


## Phase 1: candidate profile foundation

Set `JOB_AGENT_API_TOKEN` to a strong random value in the server environment. Empty/unset
configuration returns **503**; missing or invalid bearer credentials return **401**.
Tokens use constant-time comparison and are never stored in the candidate record or logged
by the API. Use HTTPS outside localhost and keep database SQL echo disabled for private data.
This is single-user server authentication, not multi-user login. Phase 4A adds a separately authenticated, disabled-by-default MCP endpoint; see
[MCP security and tools](docs/mcp-security-and-tools.md). The REST token does not grant MCP access.

| Endpoint | Behavior |
| --- | --- |
| `GET /api/v1/profile` | Saved profile plus ETag; 404 when absent |
| `PUT /api/v1/profile` | 201 on creation, 200 on full replacement or equivalent request |
| `PATCH /api/v1/profile` | 200; updates only supplied fields, recursively merges preferences |
| `POST /api/v1/jobs/{job_id}/match` | Uses saved profile and existing scorer; 404 for absent job/profile |

All four require `Authorization: Bearer <token>`. GET/PUT/PATCH return a quoted numeric
`ETag` such as `"1"`. Use that value in `If-Match` for PATCH and changed PUT requests.
Missing preconditions return **428**, stale versions **409**, invalid bodies/headers **422**,
and bodies over 64 KiB **413**. Equivalent PUTs without If-Match are harmless retries;
a supplied stale If-Match still conflicts. Concurrent creates may return 409; retrieve and retry.

PUT replaces all profile fields: omitted optional values become null or empty collections.
PATCH preserves omitted values; explicit null clears nullable fields. Required identity,
collections and the preferences object cannot be null. Arrays are replaced as a whole.
Within `preferences`, omitted properties are preserved. No profile is seeded automatically.

Fictional example (do not copy this into your actual personal profile):

```bash
curl -i http://localhost:8000/api/v1/profile \
  -H "Authorization: Bearer $JOB_AGENT_API_TOKEN" \
  -H 'Content-Type: application/json' -X PUT \
  -d '{"full_name":"Alex Example","email":"alex@example.com","verified_skills":["Python"],"preferences":{"target_titles":["Backend Engineer"],"remote_preference":"remote"}}'

curl http://localhost:8000/api/v1/profile \
  -H "Authorization: Bearer $JOB_AGENT_API_TOKEN"

curl http://localhost:8000/api/v1/profile -X PATCH \
  -H "Authorization: Bearer $JOB_AGENT_API_TOKEN" -H 'If-Match: "1"' \
  -H 'Content-Type: application/json' \
  -d '{"preferences":{"preferred_locations":["London"]},"phone":null}'

curl -X POST "http://localhost:8000/api/v1/jobs/$JOB_ID/match" \
  -H "Authorization: Bearer $JOB_AGENT_API_TOKEN"
```

Example response excerpt (the full response also includes UUID, timestamps, URL fields,
empty career collections and all preferences):

```json
{
  "singleton_key": "primary",
  "version": 1,
  "full_name": "Alex Example",
  "email": "alex@example.com",
  "verified_skills": ["Python"],
  "verified_experience_years": null
}
```

Preferences accept `remote`, `hybrid`, `onsite`, `any` or null; employment types are
`full_time`, `internship`, `contract`. Salary is an optional amount with an optional
three-letter uppercase currency code; no currency or pay period is inferred. Detailed
experience, education, projects and certifications are documented in `/docs` OpenAPI schemas.
Unknown experience, notice period and authorization stay null. Draft answers omit unknown facts.

### Migration

Apply `supabase/migrations/002_candidate_profile.sql` after migration 001 using an authorized
server-side database owner. It adds only `job_agent` objects and preserves existing records.
It enables RLS with no client policies, revokes client access and adds automatic version/timestamp
maintenance. The backend database role must own the table or have BYPASSRLS and appropriate grants.
Migration 001 remains unchanged. Do not run ORM `create_all` as a production migration.
**Applying this migration to the shared production Supabase database requires separate explicit approval.**

After that approval, a database administrator can run the migration against the approved target:

```bash
psql "$APPROVED_DATABASE_URL" -v ON_ERROR_STOP=1 -f supabase/migrations/002_candidate_profile.sql
```

The migration was exercised only in an isolated local PostgreSQL database during development.
No production profile or fictional sample record is installed by it.

### Validation

```bash
source backend/venv/bin/activate
python -m compileall -q backend/app
pytest backend/tests -v
```

Without `PROFILE_TEST_DATABASE_URL`, the PostgreSQL test is explicitly skipped; SQLite alone
does not verify migration compatibility. To include it, start an ephemeral PostgreSQL 16 server
with database `candidate_profile_test`, then run:

```bash
PROFILE_TEST_DATABASE_URL=postgresql://postgres:profile_test_only@127.0.0.1:55439/candidate_profile_test pytest backend/tests -v
```

The test requires a localhost URL and that exact base database name. It creates and drops its
own uniquely named database, checks real concurrent writes and confirms existing/public records
are preserved. CI provisions this server automatically. Tests block real HTTP transports and
use dummy/empty account credentials. No formatter/linter/type checker is currently configured.

Later phases can consume `CandidateProfileService` for verified facts, preferences and the
application-assistant adapter. Only titles, skills, location and known experience affect the
existing score. Additional stored preferences are available for future filtering/ranking;
they are not falsely represented as scoring factors today. Matching results are returned without
being saved to the publicly readable jobs endpoint. Deployment is not configured in this repository.

## Phase 2A: resources, candidate knowledge and application answers

The existing backend now supports authenticated profile/resource link resolution, confirmed
professional evidence, deterministic factual answers, optional server-side Gemini narrative drafts,
and explicitly saved answer drafts. Resume links are metadata; file-upload questions return
`file_upload_required`. No applications are submitted and no emails or messages are sent.

Read [the application answer engine guide](docs/ai-application-answer-engine.md) for all endpoints,
fictional API examples, provider configuration, evidence confirmation, limits and offline tests.
Migration 003 is additive and requires 001/002 first; production execution needs separate approval.
All new endpoints reuse `JOB_AGENT_API_TOKEN` and fail closed when it is unset. Gemini credentials
are optional for deterministic features and independent of Codex credentials.
Environment defaults are read fallbacks; import explicitly with:

```bash
python -m backend.scripts.import_candidate_resources --dry-run
python -m backend.scripts.import_candidate_resources --apply
```

Review dry-run output first. Saved profile fields are never silently overwritten. See the guide
for explicit standard-link confirmation and additional-resource confirmation semantics.

## Phase 2B discovery

Apply additive migrations 001–004 to an approved development database before using the current ORM.
Discovery REST endpoints and the legacy jobs list require `JOB_AGENT_API_TOKEN`. Preview makes no
provider calls. Source execution uses `/api/v1/discovery/runs`; the old source runner is no longer
exposed through unauthenticated MCP. Use `/api/v1/jobs/search` for saved-profile exclusions and ranking.

Greenhouse needs configured board tokens/company names. Remotive, Arbeitnow and HN use public feeds.
Naukri, Instahyre, Wellfound and YC preserve their platform identities but remain disabled until a
permitted actor/schema/pricing configuration is reviewed. Internshala supports validated manual import.
LinkedIn profile discovery uses permitted public search-index results or supplied evidence links;
no LinkedIn HTTP collection, account integration, applications, messages or connections are automated.

See [job-discovery-pipeline.md](docs/job-discovery-pipeline.md) for bounded Apify/Serper budgets,
provider failure outcomes, startup metadata, normalization, deduplication and isolated PostgreSQL tests.
No production migration or deployment is performed.

## Phase 3 contact research

Bearer-protected contact enrichment now reuses company contacts and Phase 2B people evidence, with optional Apollo and SignalHire adapters, durable credit reservations, safe identity reconciliation and explainable recommendations. Paid execution is disabled by default. Both adapters are mock-tested; no live provider authorization or enrichment has been verified. Migration 005 is additive and has only been verified in disposable PostgreSQL, with no production migration or deployment.

See [contact enrichment](docs/contact-enrichment.md) for configuration, provider documentation, API examples, verification semantics, retention, tests and the fictional demonstration. No messages are sent.


## Phase 4A: secure MCP, secondary Gmail connection and local outreach

Implemented: disabled-by-default authenticated Streamable HTTP at `/mcp/`, centralized read/draft
capabilities, structured audit logs, a connector capability registry, server-side Google OAuth
with one-time durable state/PKCE/browser binding, encrypted connection storage, and evidence-grounded
local outreach drafts with revision-specific human review. Legacy mutation tools are not registered.
No Gmail writes, emails sent, browser automation, application submission or deployment are included.

- [MCP client setup and tool permissions](docs/mcp-security-and-tools.md)
- [Google Cloud setup, scopes and secondary-account connection](docs/gmail-oauth-connection.md)
- [Draft generation, editing, eligibility and approval](docs/outreach-drafting.md)

Migration `006_mcp_gmail_outreach_foundation.sql` follows 001–005 and is never applied at startup.
Google/provider integrations remain mock-tested unless actual connection verification is recorded.
Do not infer live connectivity from code/configuration or CI. Production migration and deployment
need separate authorization.

Run the complete suite with a **disposable localhost** PostgreSQL database named `candidate_profile_test`:

```bash
PROFILE_TEST_DATABASE_URL=postgresql://postgres:<test-password>@127.0.0.1:<test-port>/candidate_profile_test \
  backend/venv/bin/pytest backend/tests -q
```

The PostgreSQL verifiers create/drop uniquely named child databases, preserve/check prior records,
and test RLS/grants, callback/refresh races, draft idempotency and revision guards. Without this
environment variable PostgreSQL tests skip; SQLite alone is not migration verification.

## Phase 4B: approved Gmail sending

Implemented: separate secondary-account `gmail.send` consent; exact approved-message preview;
short-lived single-use owner confirmation; durable one-attempt-per-draft reservation, worker
concurrency protection and rolling hourly/daily caps; truthful Gmail acceptance/unknown history.
Approval never sends. MCP cannot send. Timeouts and lost responses never trigger automatic retries.

Sending defaults to disabled. Apply additive migration **007 after 001–006** only with separate
environment authorization. No real account was connected or email sent during implementation;
tests use mocks and disposable PostgreSQL. No production migration/deployment was performed.
See [approved Gmail sending](docs/gmail-approved-sending.md) for OAuth, API examples, crash recovery,
manual reconciliation, limits, Google verification and rollout requirements.

## Phase 5A: standalone application preparation

Saved Naukri jobs can produce a read-only application preview and durable packet through protected
REST. The packet preserves the candidate version, confirmed resume resource snapshot, actual
application URL, profile links, questions, grounded answers, review state and audit history.
Explicit narrative generation reuses the Gemini answer engine; preview, creation and MCP reads
make no paid calls. Missing facts stay missing. All narratives require human review.

Approval enables a copy-ready `manual_handoff`; it does not open a browser or submit an application.
The owner opens the returned URL, uploads the actual resume, completes the form, and records an
explicit `user_reported_submitted` confirmation. Neither approval nor opening changes `Job.status`.
No provider-confirmed submission, portal authentication, browser worker or extension is implemented.
Naukri live access and destination availability remain unverified.

- [Application architecture, lifecycle, API and migration 008](docs/application-preparation.md)
- [Complete fictional API walkthrough and Naukri handoff](docs/naukri-application-handoff.md)

Migration **008 follows 001–007**, adds only `job_agent` application objects and preserves prior
records. No production migration or deployment is authorized. Run the full regression suite with
`PROFILE_TEST_DATABASE_URL` as described above to include all PostgreSQL checks, or run only:

```bash
PROFILE_TEST_DATABASE_URL=postgresql://postgres:<test-password>@127.0.0.1:5432/candidate_profile_test \
  backend/venv/bin/pytest backend/tests/test_phase5a_postgres.py -q
backend/venv/bin/python -m backend.scripts.demo_application_preparation
```

The demonstration uses fictional data, an injected fake Gemini response, and an in-memory database.
It performs no network calls, production writes, submissions or email sends. REST operates with
MCP disabled; five application read tools use the separate `read_applications` capability.

## Phase 6A: startup discovery and professional intelligence

Startup intelligence reuses the existing discovery, saved-profile matching, contacts and application
services. Companies can be imported independently of jobs with permission-bearing evidence;
job-led runs use existing HN, Greenhouse, Remotive and Arbeitnow adapters. Small-company filters
preserve unknown/conflicting counts, hiring signals retain provenance, and ranked shortlists show
reasons and missing information. Startup REST endpoints require owner bearer authentication;
five new MCP tools perform cached reads only.

Actual bounded public checks passed for all four public feeds on 2026-10-19. See the
[UTC-timestamped source evidence](docs/phase6a-live-verification.json). This is historical test evidence,
not deployment verification. YC automated directory discovery remains unsupported, and
Wellfound/YC actors and Serper require operator permission/configuration/cost review. No paid
calls or LinkedIn requests were performed. Founder end-to-end validation uses fictional fixtures.

- [Startup discovery, filters, ranking, API, MCP and demonstration](docs/live-startup-discovery.md)
- [Founder evidence, conservative identity and LinkedIn restrictions](docs/startup-founder-intelligence.md)
- [Provider permissions, account limits, diagnostics and troubleshooting](docs/discovery-provider-setup.md)

Migration **009 follows 001–008** and adds only `job_agent` objects; it has not been applied to
production. Run `python backend/scripts/startup_discovery_demo.py` for a full offline demonstration,
or explicitly select `--live --source hacker_news` for a bounded public connectivity check using a
temporary local database. No schedule, platform write, application submission or message send is added.

## Phase 6B — operation and staging preparation

Operational code, an environment's readiness and a verified real pilot are separate states.
No production deployment/migration, real Gmail send, paid request or job submission is authorized
by this phase. This remains a standalone single-owner backend; no apply-extension or browser
service is involved.

```sh
# Configuration only; no database or external provider connection.
backend/venv/bin/python backend/scripts/check_environment.py
# Offline migration plan; no DDL.
backend/venv/bin/python backend/scripts/migration_preflight.py
# Integrated fictional discovery → match → packet → fake grounded answer → reviewed handoff.
backend/venv/bin/python backend/scripts/smoke_test.py --mode local-offline
```

Use [Phase 6B operations](docs/phase6b-operations.md) for typed readiness, pinned staging targets,
profile dry-run/apply and sanitized metrics; [staging setup](docs/staging-setup.md) for the non-root
Docker image, constrained dependencies, ingress/TLS, migrations and restore rehearsal;
[provider validation](docs/real-provider-validation.md) and [pilot procedure](docs/end-to-end-pilot.md)
for bounded authorized real data. Review the [security findings](docs/security-deployment-review.md)
and [production checklist](docs/production-readiness-checklist.md) before any release.

`/health` is liveness; `/ready` checks essential database access with sanitized failure output.
Owner-only `/api/v1/operations/status` returns persisted configuration/provider evidence, not a
live provider test. `/api/v1/credits/status` now also requires the existing owner bearer.
Live environments reject unsafe configuration/startup failures, use certificate-verified database
TLS, and keep sending/submission disabled. Reports and owner input files are private, ignored
runtime artifacts. The Docker image does not include test dependencies or personal data.

## Phase 8 — private workspace staging readiness

See [workspace staging](docs/phase8-staging.md) for the standalone non-root frontend image,
cross-service configuration checks, exact OAuth ingress requirements, owner review and the
durable local public-source pilot. This extends the Phase 7 dashboard; it does not provision a
host or authorize a staging/production migration. Missing owner data or provider access remains
explicit. External sends, submissions, paid operations and notification delivery stay gated.
