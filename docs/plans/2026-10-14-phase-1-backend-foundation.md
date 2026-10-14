# Phase 1: Repository, Backend Foundation, and Database Implementation Plan

> **Goal:** Establish the foundational backend architecture for Job Pulse Agent: modular directory structure, Python 3.11 environment, isolated PostgreSQL schema (`job_agent`), configuration management, atomic credit budgeting service, FastAPI REST endpoints, FastMCP tool layer, and full test suite.

**Architecture:** A modular Python backend using FastAPI for HTTP endpoints, FastMCP for AI tool integration, and direct asynchronous PostgreSQL connectivity (via asyncpg/SQLAlchemy) targeted exclusively at a dedicated `job_agent` schema within Supabase. External API keys are abstracted via encrypted references/environment variables, with strict concurrency-safe credit accounting and zero leakage to client or logs.

**Tech Stack:** Python 3.11, FastAPI, FastMCP, Pydantic v2, Pydantic Settings, asyncpg / SQLAlchemy, pytest, Supabase PostgreSQL (`job_agent` schema).

---

## Task Breakdown

### Task 1.1: Project Initialization & Git Configuration
- Initialize git repository in `/Users/karanagg/Desktop/Projects/automated-apply`.
- Create `.gitignore` protecting `.env`, virtualenvs, credentials, python cache, test artifacts.
- Create root `README.md` and `.env.example`.
- Verify GitHub authentication via `gh`.

### Task 1.2: Monorepo Structure & Python 3.11 Virtual Environment
- Create modular folder layout:
  ```text
  job-pulse-agent/
  ├── backend/
  │   ├── app/
  │   │   ├── api/
  │   │   ├── core/ (config, logging, security)
  │   │   ├── db/ (engine, session)
  │   │   ├── models/ (database models)
  │   │   ├── repositories/ (database access layer)
  │   │   ├── schemas/ (pydantic request/response/MCP schemas)
  │   │   ├── services/ (credit manager, email generator)
  │   │   ├── mcp_server.py
  │   │   └── main.py
  │   ├── tests/
  │   │   ├── conftest.py
  │   │   ├── test_config.py
  │   │   ├── test_credit_manager.py
  │   │   ├── test_email_candidate_generator.py
  │   │   ├── test_repositories.py
  │   │   └── test_mcp_tools.py
  │   ├── requirements.txt
  │   └── .env.example
  ├── docs/
  │   ├── architecture.md
  │   ├── decisions.md
  │   ├── roadmap.md
  │   └── plans/
  └── supabase/
      └── migrations/
          └── 001_initial_schema.sql
  ```
- Initialize virtual environment with Python 3.11: `/opt/homebrew/bin/python3.11 -m venv backend/venv`.
- Prepare `requirements.txt` with pinned compatible versions.

### Task 1.3: Type-Safe Configuration Layer (`app/core/config.py`)
- Define `Settings` using `pydantic-settings`.
- Enforce strict typing for:
  - Database URL & pool settings
  - Schema name (`job_agent`)
  - App environment (`development`, `staging`, `production`)
  - Log level
  - Provider budget defaults & safety limits
  - Secret encryption key / token references
- Validate that no default passwords or sensitive values are hardcoded.

### Task 1.4: Database Schema Migration (`supabase/migrations/001_initial_schema.sql`)
- Write idempotent migration creating `CREATE SCHEMA IF NOT EXISTS job_agent;`.
- Define tables strictly within `job_agent`:
  1. `job_agent.companies`: Domain, name, email patterns, catch-all flags, metadata.
  2. `job_agent.jobs`: Title, URL, company reference, location, remote status, match score, status.
  3. `job_agent.contacts`: Company reference, name, role, email, email verification state, source, confidence.
  4. `job_agent.api_keys_pool`: Provider, account label, secret reference, credits remaining, monthly limit, reset date, active flag.
  5. `job_agent.provider_usage_logs`: Audit trail of every credit consumption or failed lookup.
  6. `job_agent.outreach_logs`: Job & contact references, draft ID, message ID, approval state machine (`pending_approval`, `draft_created`, `approved`, `sent`, `rejected`).
- Add foreign keys with cascading protections, unique constraints, and check constraints (e.g. verification state enum checks).
- Provide verification script to prove that `public` schema tables are untouched.

### Task 1.5: Database Client & Repository Layer
- Implement asynchronous database session manager in `app/db/session.py`.
- Implement clean repository pattern separating SQL/ORM from business logic:
  - `CompanyRepository`: Lookup by domain or name, upsert company, retrieve pattern.
  - `JobRepository`: Save job, deduplicate by canonical URL or company+title, update status.
  - `ContactRepository`: Lookup cached contacts by company, save enriched contact with provenance.
- Support transactional sessions with explicit rollbacks.

### Task 1.6: API Credit & Budget Manager (`app/services/credit_manager.py`)
- Implement `CreditBudgetManager`:
  - `get_active_key(provider)`: Selects active credential with available quota.
  - `reserve_or_check_credits(provider, estimated_cost)`: Atomic check against budget.
  - `record_provider_usage(provider, cost, status_code, success, endpoint)`: Logs usage and decrements remaining credits.
  - `mark_provider_unavailable(provider, reason, retry_after_seconds)`: Handles 429/401/403 with exponential backoff or backoff timeout.
  - `get_credit_status()`: Summary of remaining credits and resets across all configured providers.
- Negative result caching: Cache failed lookups to prevent credit burn on repeatedly querying nonexistent contacts.

### Task 1.7: FastAPI Application (`app/main.py`)
- Structured application factory with lifespan context manager (handling DB connection pool startup/shutdown).
- Endpoints:
  - `GET /health`: Liveness probe.
  - `GET /ready`: Readiness probe verifying database connectivity and schema readiness.
  - `GET /api/v1/credits/status`: Secure endpoint reporting provider quotas and health.
- Structured JSON logging with request IDs and request timing.
- Global exception handlers for validation errors, database errors, and budget exhaustion.

### Task 1.8: FastMCP Tool Server (`app/mcp_server.py`)
- Implement foundational FastMCP tools:
  1. `lookup_or_create_company`: Resolves domain, checks cache, returns metadata.
  2. `get_cached_company_contacts`: Queries local database for previously discovered recruiters/engineers.
  3. `generate_company_email_candidates`: Generates potential corporate email addresses based on patterns (`first.last@domain.com`, etc.), explicitly labeling state as `candidate` (never `verified`).
  4. `save_discovered_job`: Stores job posting with deduplication.
  5. `check_api_credits_status`: Returns current quota and provider availability.
- Mount FastMCP server or configure SSE endpoint alongside FastAPI.

### Task 1.9: Comprehensive Testing Suite
- Setup `pytest`, `pytest-asyncio`, and `httpx`.
- Unit tests:
  - Settings validation and environment overrides.
  - Email pattern candidate generation (handling special characters, accents, hyphenated names).
  - Credit manager logic (budget enforcement, negative caching, 429 backoff handling).
  - MCP tool input schemas and structured responses.
- Integration/Mock tests:
  - Repository CRUD operations with in-memory SQLite or mock async session.
  - FastAPI `/health` and `/ready` endpoints.
- Require all tests to pass before phase completion.

### Task 1.10: Documentation & Decisions
- Author `docs/architecture.md`: Complete system architecture, data flow, security model, and schema isolation.
- Author `docs/decisions.md`: Architectural Decision Records (ADRs) covering direct Postgres vs PostgREST, FastMCP integration pattern, and credit management strategy.
- Author `docs/roadmap.md`: Full multi-phase tracker with Phase 1 verification report.
