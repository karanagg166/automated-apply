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
- FastMCP tools accepting explicit candidate inputs; LinkedIn submissions remain manual.

Paid platform actors require reviewed configuration and explicit budgets; no actor or account is pre-verified. See [the discovery pipeline](docs/job-discovery-pipeline.md) for source status, API examples, migration 004 and test instructions.

Account integrations, automated submissions, outreach sending, background scheduling and a dashboard are future work. The diagrams below describe the target architecture, not deployed components.

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
2. **Strict HITL:** The system prepares drafts and normalizes data autonomously. Emails are sent **only** after explicit human confirmation.
3. **Cost-First Budgeting:** Cached data is reused first, free tiers are prioritized, and external API calls fail safe when budgets are reached.
4. **Database Isolation:** All application tables reside in the `job_agent` schema, completely segregated from other projects and existing public tables.


## Phase 1: candidate profile foundation

Set `JOB_AGENT_API_TOKEN` to a strong random value in the server environment. Empty/unset
configuration returns **503**; missing or invalid bearer credentials return **401**.
Tokens use constant-time comparison and are never stored in the candidate record or logged
by the API. Use HTTPS outside localhost and keep database SQL echo disabled for private data.
This is single-user server authentication, not multi-user login. The existing MCP endpoint
cannot read the saved profile; protect existing tools separately before exposing them publicly.

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
are optional for deterministic features and independent of Codex/Chrome extension credentials.
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
