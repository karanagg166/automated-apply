# Architectural Decision Records (ADRs)

---

## ADR 001: Schema Isolation (`job_agent`) vs Separate Supabase Project

- **Status:** Accepted (Option B)
- **Context:** The user already runs an existing production application on Supabase with 12 tables in the `public` schema. Creating a second project incurs additional infrastructure overhead or quota exhaustion, whereas sharing a PostgreSQL instance without isolation risks table name collisions or accidental drops.
- **Decision:** Use PostgreSQL schema isolation with a dedicated schema named `job_agent`. All tables, indexes, and constraints belong to `job_agent.*`. The search path for the backend engine is explicitly configured to `job_agent,public`.
- **Consequences:**
  - Complete operational segregation: zero impact on existing application tables in `public`.
  - Single database connection pool footprint.
  - Requires explicit schema qualification or `search_path` configuration.

---

## ADR 002: Direct PostgreSQL (asyncpg/SQLAlchemy) vs Supabase PostgREST Client

- **Status:** Accepted (Direct Async PostgreSQL)
- **Context:** Supabase offers both a PostgREST Data API (via `supabase-py`) and a direct PostgreSQL connection string (via port 5432 or PgBouncer/Supavisor pooler on 6543).
- **Decision:** Use direct asynchronous PostgreSQL with `asyncpg` and `SQLAlchemy 2.0`.
- **Rationale:**
  1. **Security:** Exposing `job_agent` to PostgREST requires publishing the schema to the web API (`anon` and `service_role`). Internal tables like `api_keys_pool` and candidate emails should not be exposed to HTTP Data APIs unless explicitly required.
  2. **ACID Transactions:** Direct SQL allows row-level locking (`SELECT ... FOR UPDATE`), atomic credit decrements, and transactional rollback guarantees across multiple operations.
  3. **Testing Agility:** SQLAlchemy enables 100% in-memory testing with SQLite (`aiosqlite`), executing the complete test suite in <0.5 seconds without network calls.

---

## ADR 003: FastMCP 4.x Mounted Sub-application vs Stdio Subprocess

- **Status:** Accepted (Mounted SSE Sub-app)
- **Context:** FastMCP supports running tools via `stdio` (local subprocess) or `sse` / `http` (HTTP ASGI server).
- **Decision:** Mount FastMCP inside the FastAPI web application using `app.mount("/mcp", mcp.http_app(transport="sse"))`.
- **Rationale:**
  - Allows the same backend process to serve REST endpoints (e.g. `/health`, `/ready`, `/api/v1/*`) and SSE MCP tools for AI agents on a single port.
  - Preserves dependency injection, shared database connection pools, and structured logging.

---

## ADR 004: Inferred Candidate Distinction vs Verified Address Labeling

- **Status:** Accepted
- **Context:** Mathematically generated email candidates (e.g. `first.last@company.com`) may look plausible but are unverified guesses. Sending outreach to unverified guesses damages domain reputation and causes high bounce rates.
- **Decision:**
  - All inferred emails are strictly assigned `email_status="candidate"`.
  - The `EmailCandidate` schema includes an explicit mandatory `disclaimer`: `"This is an inferred candidate pattern, NOT a verified mailbox."`
  - Only provider-confirmed or SMTP-verified addresses may transition to `verified`.

---

## ADR 005: Concurrency-Safe API Credit Budget Management & Negative Caching

- **Status:** Accepted
- **Context:** External enrichment APIs (Hunter, Apollo, Serper) charge per request or have strict monthly credit caps. Concurrent background discovery workers could race and exceed monthly budgets.
- **Decision:**
  1. Implement atomic credit checking in `CreditManager` before issuing external requests.
  2. Implement a 24-hour negative lookup cache for failed or 404 queries to prevent repeatedly burning credits on nonexistent contacts.
  3. Automatically apply a cooldown window on HTTP 429 rate limits and deactivate keys on HTTP 401/403 authentication failures.
