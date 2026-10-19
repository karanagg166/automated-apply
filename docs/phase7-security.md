# Phase 7 security boundary

## Single-owner frontend

The frontend requires a salted scrypt passphrase hash and an independent session signing secret. Its only identity is the owner. Login returns an eight-hour signed, nonce-bearing session cookie with HttpOnly, SameSite=Strict and Secure on HTTPS. A separate session-bound CSRF token is required for every mutation. Exact configured origin and Host checks apply to the BFF, login and logout. There is no client-side bearer token, Supabase service-role variable or anonymous development bypass.

`FRONTEND_LOCAL_HTTP=true` permits HTTP only for explicit loopback origins. All non-loopback deployments require HTTPS. Use one Node instance: the built-in global ten-attempt/15-minute login throttle is process-local. Before horizontal scaling, add a shared rate limiter at trusted ingress and a server-side session revocation store. Logout removes browser cookies; an already stolen signed cookie is valid until expiry unless the signing secret is rotated. Changing the passphrase alone does not revoke existing cookies.

The server-side BFF uses a fixed method/path allowlist, validates request size, forwards only required Content-Type/If-Match headers, adds the backend bearer server-side, disables redirects/caching, bounds fetch duration and returns sanitized server failures. Browser origins never control the backend destination. Backend URLs require HTTPS except loopback. Configure infrastructure request header/body/time limits as a second boundary.

Security headers include no-store, no-referrer, nosniff, DENY framing, Permissions-Policy and CSP with same-origin connections and no objects/frames. Next.js hydration uses inline scripts; CSP currently permits inline scripts/styles and is not a strict nonce policy. Do not treat CSP as a substitute for React text escaping and the server boundary. External links accept credential-free HTTPS only and use noopener/noreferrer. No untrusted PDF text or evidence is rendered as HTML.

## Resume and database

Private PDFs are authenticated before validation, bounded, parsed in a disposable local process and encrypted before storage with a dedicated Fernet key. The worker does not inherit provider credentials. Linux uses an address-space ceiling; macOS uses parent RSS supervision. Downloads require authentication, use attachment disposition and no-store, and are never static assets. Confirmed private resources retain a storage reference separate from public resource URLs. Key rotation/retention must preserve decryptability and existing packet evidence.

Migration 010 enables RLS, revokes PUBLIC/anon/authenticated access and grants only the existing server role needed operations. PostgreSQL verification runs in randomly named disposable localhost databases, never the configured owner project. The catalog manifest was regenerated from disposable PostgreSQL after reviewing 001–010. There is no production schema application or Supabase project selection.

## Provider and execution limits

Existing Gmail hashes/revisions, confirmation challenges, account binding, idempotency and duplicate-send protection remain in the backend. Paid enrichment remains behind existing credentials, rights, account costs, budget and per-run consent. No MCP privilege expansion, LinkedIn login/scraping/cookie import or extension dependency was added. Portal actions remain manual. Outbound notification channels cannot be enabled by frontend preferences.

The fixed resume-alias checker validates DNS/IPs at every hop, uses TLS hostname validation with a pinned public IP, follows bounded HTTPS redirects and sends no credentials. Unavailable or unverified destinations remain unresolved.

## Verification and deployment limits

Tests cover signed-session tampering/expiry, origin/Host rejection, CSRF, restricted proxy routes, login throttling, anonymous private uploads/downloads, PDF limits/encryption/confirmation, and frontend bundle/HTML bearer exposure. Browser tests use the actual FastAPI with fictional temporary SQLite data and blocked provider HTTP. Existing PostgreSQL and backend security checks continue in CI. Single-owner login setup, approved staging origins/database, HTTPS ingress and real provider consents remain deployment prerequisites.
