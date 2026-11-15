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

- **Status:** Superseded by ADR 006 (historical SSE design)
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

---

## ADR 006: Stateless Streamable HTTP MCP

- **Status:** Accepted; documents the current implementation.
- **Decision:** The legacy API mounts `mcp.http_app(path="/", transport="http",
  stateless_http=True, json_response=True)` at `/mcp`, with host/origin protection and
  the separate `MCPBoundary`. It is not the historical SSE transport from ADR 003.
  The Rust project tool bridge currently uses bounded stdio and the authenticated
  local owner API. A configured remote provider MCP is a separate transport.
- **Consequences:** Keep REST owner authorization separate from MCP grants. No MCP
  tool or model output can authorize applications, account changes or arbitrary sends.

## ADR 007: Whole Writer-Family Rust Cutover

- **Status:** Accepted source boundary; production installation remains unaccepted.
- **Decision:** Keep one production writer family. Python processes share the target's
  kernel writer lease; the replacement Rust host takes it exclusively before connecting.
  Preserve service leases, database CAS, durable budgets, history and unknown-action fences.
  Do not route a subset of production mutations to Rust while legacy writers remain active.
- **Consequences:** Local process coordination is not a distributed ACL. Old installed
  releases and standalone writers must be stopped or upgraded before cutover. The complete
  Rust host needs at most four database connections, including optional Telegram and one
  shared transient generation/document request. Hosted role/pooler headroom needs actual
  verification. See [the ownership matrix and budget](architecture/runtime-ownership.md).

## ADR 008: Declarative HTTP Security Policy

- **Status:** Accepted.
- **Decision:** `contracts/http-security.json` owns the closed gateway route list,
  private path classification, body-size classes and exact owner-signature patterns.
  `uv run --no-project python scripts/sync_http_security.py` generates package-local
  copies for independently built backend and frontend images; `--check` rejects drift.
  Next.js consumes the route and signature rules; FastAPI consumes the boundary rules.
- **Consequences:** The separate HMAC key, exact method/path/body binding, short expiry,
  durable nonce replay protection, bearer auth, session and CSRF checks remain mandatory.
  Local tests compare generated copies and actual owner-approval route dependencies.
  Existing backend endpoint dependencies remain the authority; metadata alone grants none.
