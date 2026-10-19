# MCP security and tools (Phase 4A)

FastMCP **4.1.0 is pinned and tested**. There is one server instance in `app/mcp/registry.py`.
The FastAPI mount exposes **Streamable HTTP at `/mcp/`**, using stateless JSON responses.
There is no legacy SSE listener, unauthenticated public endpoint, background task API or
persistent MCP session to expire. Every HTTP request authenticates again. Existing sessions
from earlier SSE clients must be replaced. Restart after changing configuration.

## Authentication and connection

Remote HTTP defaults to `MCP_REMOTE_ENABLED=false` (404 for every method/path in the mount).
When enabled without a separate `MCP_API_TOKEN` of at least 32 characters, every request
fails closed (503). Reusing `JOB_AGENT_API_TOKEN` as the MCP token is rejected. Generate a
random token with a password manager or `python -c 'import secrets; print(secrets.token_urlsafe(48))'`.
Keep it out of shell history, URLs, committed MCP configuration and logs.

This is a **single-owner authenticated development connection**, not production multi-user
OAuth. Clients must support preconfigured bearer headers; OAuth discovery/login is not
implemented for MCP clients. Google account authorization is a separate flow.

Configure the MCP client's Streamable HTTP URL `https://<host>/mcp/` and its
`Authorization: Bearer <MCP_API_TOKEN>` header through the client's secret facility.
`MCP_ALLOWED_HOSTS` must contain the exact public host. `MCP_ALLOWED_ORIGINS` is an explicit
list of browser origins; foreign Origins fail. Native clients may omit Origin.
No wildcard trust lists are accepted. TLS is required by default. For loopback HTTP development
only, explicitly set `MCP_REQUIRE_TLS=false` and bind uvicorn to `127.0.0.1`.

Local stdio is also available: from the repository root run
`backend/venv/bin/python -m backend.app.mcp.registry`. The local process owner is the trust
boundary; read permissions and the draft opt-in still apply. Do not give untrusted processes
access to this command, its environment or database credentials.

Behind a proxy, terminate TLS at a trusted ingress, preserve Host, and configure uvicorn's
`--forwarded-allow-ips` to only that proxy's actual addresses. Never trust all forwarded IPs.
Do not expose the backend listener directly. The ASGI layer uses the resulting scheme;
untrusted forwarded headers do not establish HTTPS. Configure equivalent body, concurrency,
timeout and query-log redaction limits at ingress. Concurrency limits are per worker;
provider spending controls remain database-backed. No browser CORS policy grants credentials.

## Permission matrix

| Capability | Phase 4A policy | Tools |
| --- | --- | --- |
| `read_profile` | Authenticated owner | `get_verified_profile_summary`, `match_job_against_saved_profile` |
| `read_discovery` | Authenticated owner | `list_discovery_sources`, `search_saved_jobs`, `get_job_details`, `get_company_details` |
| `read_contacts` | Authenticated owner | `list_recommended_company_contacts`, `get_contact_evidence` |
| `read_integration_status` | Authenticated owner | `get_integration_status` |
| `prepare_draft` | Only with `MCP_ALLOW_DRAFT_CREATION=true` | `prepare_founder_outreach_draft`, `get_outreach_draft` |
| `mutate_job_state` | Unavailable | No registered tools |
| `execute_paid_provider` | Unavailable | No registered tools |
| `send_email` | Unavailable | No registered tools |
| `submit_application` | Unavailable | No registered tools |

FastMCP's native `TokenVerifier` and `AuthMiddleware` protect HTTP and filter tools/list.
Each registered function additionally checks its capability before running, including direct
invocations, so undiscovered calls cannot bypass authorization. Unknown capabilities deny.
Legacy company creation, job saving/status changes, credit status, arbitrary-profile matching,
application drafting, guessed-email generation and source execution functions remain importable
by trusted Python code for compatibility but **none are registered on MCP**. Guesses remain
`candidate`, never verified recipients. LinkedIn links support manual review only.

Services are shared with REST: `SavedDataService`, `CandidateProfileService`, contact read/ranking,
`ConnectionService`, and `OutreachDraftingService`. MCP matching loads the primary saved profile.
MCP draft creation is deterministic and non-billable: it uses an exact saved contribution and
shared local drafting/eligibility rules, labels `created_via=mcp`, and never calls Gemini,
Apollo, SignalHire, Apify, Google authorization or Gmail write APIs. Gemini composition is an
explicit authenticated REST operation with the existing shared budget manager.

## Protection and verification

An outer pure ASGI boundary covers `/mcp`, nested paths, every method and attempted WebSockets,
before redirects or session handling. Native Host/Origin guards cover both the outer boundary
and transport. Request body bytes (including chunked bodies), request lifetime and concurrent
requests are bounded. FastMCP strictly validates tool inputs and masks errors. Cancellation
releases admission. Stateless operation avoids persistent streaming/token-rotation sessions.

Verify without a token that initialize POST, tools/list, tools/call, GET streaming, DELETE and
old `/mcp/sse`/`messages` routes cannot reach MCP. With the token, initialize and list tools,
then call an undiscovered legacy mutation or disabled draft tool: it must fail without writes.
`GET /api/v1/integrations/mcp/status` uses the REST owner bearer and returns configured state,
not an assertion that a remote client was live verified.

The `job_pulse_agent.mcp.audit` structured log records UTC timestamp, tool name, generated
request/correlation UUID, actor, outcome, duration and a fixed error category. Arguments,
results, prompts, private messages, tokens and authorization headers are excluded. Route
authentication failures produce status responses before any tool executes. Protect/retain
logs appropriately; no sensitive tool-parameter audit table is created.

Official references consulted: [token verification](https://gofastmcp.com/servers/auth/token-verification),
[authorization](https://gofastmcp.com/servers/authorization), and
[HTTP deployment and Host/Origin protection](https://gofastmcp.com/deployment/http).

## Phase 4B boundary

Approved Gmail sending is available only through the owner REST preview/confirmation flow.
MCP retains its existing read/local-draft capabilities and separate bearer; `send_email` stays
unavailable even when Gmail is authorized. No send tool, hidden job, paid provider call or
application-submission tool was added. The owner API bearer and send confirmation must never
be supplied to MCP clients or agents. Status is readable through existing draft/integration
views; send history is a protected owner REST API. LinkedIn restrictions are unchanged.
See [approved sending](gmail-approved-sending.md).
