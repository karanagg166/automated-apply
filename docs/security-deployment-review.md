# Security deployment review

The trust model remains one owner. Shared static REST and separate MCP bearer tokens are not
multi-user sessions, tenant isolation or role-based user authentication. Deploy behind private
networking/trusted access controls until proper user/session authentication is engineered.
There is no extension dependency, browser microservice or external job submission route added.

Phase 6B changes:

- Startup in staging/production rejects unsafe secrets, debug/SQL echo, schema/target settings,
  REST transport settings and unsafe MCP configuration. Database initialization now performs an
  actual bounded dependency probe instead of claiming a connection from engine construction.
  Live runtime reads check expected table presence and SELECT privileges; startup errors fail closed.
- REST Host/Origin/TLS controls complement existing independent MCP controls. Loopback health
  probes bypass TLS only for /health and /ready. Ingress forwarding trust must be explicitly set;
  arbitrary X-Forwarded-* headers do not confer HTTPS authority.
- Credits status now requires the same owner authentication as saved jobs. Profile/packet/discovery
  boundaries retain their authentication and size limits. Private validation errors no longer echo
  submitted profile values; readiness and generic ValueError responses do not return database text.
  Request execution and private-body streaming have bounded timeouts.
- Application logger redacts configured DSNs/passwords, provider keys/tokens, client secrets and
  OAuth keyring material. Existing OAuth callback access-log query stripping stays installed.
  This is defense in depth: never log raw exception response bodies, prompts, resumes or emails.
- Staging operator commands require an explicitly supplied environment, pinned database target
  and confirmation; production connections are refused before an engine is created. Profile import
  defaults to validation/dry-run and uses existing API version semantics on explicit owner apply.
- No SQL executes on import, configuration inspection, image startup migration hook or dry-run.
  Migration inspection uses PostgreSQL READ ONLY; no reset/rotation/deployment is automatic.
- Paid sources remain opt-in with existing rights/pricing/account gates and durable reservations.
  Operational public scripts enforce a fixed host allowlist at HTTP transport level and cannot
  contact Gmail, paid enrichment or arbitrary supplied URLs. Private profile facts require consent.
- Public packet support validates stored URLs locally and requires explicit owner review; it never
  fetches the URL. Existing public-HTTPS validation rejects credentials/private/reserved literal IPs.
  Since arbitrary URLs are not fetched, DNS rebinding is not introduced as a server fetch path.
- Gmail sending stays false by default; staging startup refuses true. Scopes are never upgraded
  by diagnostics. Existing fresh send confirmation and durable attempts remain separate controls.

## Database limits that require operator review

001–009 do not have a migration ledger. Catalog parity detects structural drift; it is not proof
of past execution or of future runtime authorization. Supabase-compatible roles must exist before
conditional grants are applied; reference verification tests their intended state. New/private
candidate, evidence, discovery, contact, OAuth, send and packet tables have their existing RLS and
grant restrictions. The original companies/jobs/api_keys_pool/provider_usage_logs tables do **not**
all have RLS enabled by these migrations. The preflight reference records that actual baseline;
it does not quietly claim every table has RLS or enable broad policies to make startup pass.

Do not expose job_agent through PostgREST/public client credentials. Preflight rejects effective
anon/authenticated/PUBLIC table privileges, including inherited privileges. Select a dedicated
trusted runtime role with the required table access/RLS policy or controlled BYPASSRLS; assess
whether a separate reviewed hardening migration should enable RLS on the remaining legacy tables.
Do not grant blanket client access or use a browser anon token. Existing append-only event/evidence
and protected send/packet transitions still need their restricted privileges. Full schema owner or
service-role compromise can bypass row controls; secrets/network isolation are essential.
The runtime role's DML paths must be verified separately from admin catalog inspection before
production. Do not publish multi-user security claims based on these single-owner protections.

## Remaining release gates

Actual HTTPS ingress/network/Host tests on the selected host, database role DML verification,
backup restore rehearsal, owner profile confirmation, real permitted provider evidence, factual
answer review and any production SQL/deployment approval are external operational work. An image
build and green CI do not satisfy those gates. Monitor provider failures and stale evidence without
making optional integrations a readiness dependency. Keep private report/backup retention bounded.
