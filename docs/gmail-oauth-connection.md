# Secondary Gmail OAuth connection (Phase 4A)

This is a single-owner backend connection, mock-tested against Google's documented HTTPS
endpoints. No real Google credentials/account connection is implied by passing tests.
No Gmail draft, send, label, attachment, message-body, deletion or mailbox-download API is
implemented in this flow. The existing alert parser remains manual-import-only in discovery.

## Google Cloud setup

1. Create/select an owner-controlled Google Cloud project and enable Gmail API.
2. Configure the OAuth consent screen, audience and test users. For external Testing apps,
   add the intended secondary account as a test user. Publish/verify only after reviewing
   Google's applicable policies. Testing refresh tokens for restricted scopes can expire
   after seven days; revoked/expired credentials require reconnection.
3. Create a **Web application** OAuth client. Configure the exact redirect URI, for example
   `https://your-backend.example/api/v1/integrations/gmail/oauth/callback`. A loopback
   `http://localhost:<port>/api/v1/integrations/gmail/oauth/callback` is allowed for development.
4. Set server-only `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REDIRECT_URI`, and preferably
   `GMAIL_EXPECTED_EMAIL` to the intended secondary address. Arbitrary request redirects,
   callback query/fragment configuration and non-loopback HTTP redirect URIs are rejected.
5. Configure the separate encryption keyring below. Keep credentials out of browser storage,
   candidate profiles, source files, MCP clients and logs.

Default metadata-connection scopes are exactly:

- `openid`: stable Google subject identity.
- `https://www.googleapis.com/auth/userinfo.email`: verified email identity (Google's `email` alias is normalized).
- `https://www.googleapis.com/auth/gmail.metadata`: Gmail account-profile verification through `users.getProfile`.

`gmail.metadata` is **restricted**, despite not allowing bodies. The application uses it only
to verify that the authorized Gmail mailbox matches Google's verified account email. It does
not read message headers or labels. Phase 4B adds only `gmail.send` through a separate explicit
consent upgrade with the same secondary identity. The default connection does not request it.
`gmail.compose`, `gmail.modify`, `gmail.readonly`, and `https://mail.google.com/` remain rejected.
Each mode validates its exact granted set; refresh cannot expand or reduce the saved set. Do not add compose just for local drafts: it also permits sending.

Google's restricted-scope verification applies to external distribution unless an applicable
exception covers the use. Server-side storage/transmission of restricted-scope data may also
require a security assessment. Review the actual project's audience/use with Google's current
requirements before publication; a personal test setup is not proof of verification.
See [scope definitions](https://developers.google.com/workspace/gmail/api/auth/scopes),
[restricted scope verification](https://support.google.com/cloud/answer/13464325),
[OAuth policies](https://developers.google.com/identity/protocols/oauth2/policies),
[web-server flow](https://developers.google.com/identity/protocols/oauth2/web-server), and
[OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect).

## Owner connection flow and endpoints

All routes use `JOB_AGENT_API_TOKEN`, except the callback which Google cannot authenticate
with that bearer. Use a same-browser client which retains the returned HttpOnly cookie.

| Route | Behavior |
| --- | --- |
| `GET /api/v1/integrations` | Capability registry and redacted saved connection state |
| `POST /api/v1/integrations/gmail/connect/start` | Body `{ "expected_email": "secondary@example.com" }`; returns authorization URL and TTL, sets browser-binding cookie |
| `GET /api/v1/integrations/gmail/oauth/callback` | Validates exact URI, browser binding and durable one-time state; consumes state before exchange; returns no tokens |
| `GET /api/v1/integrations/gmail/status` | Saved subject, email, granted scopes, verification times and state; no network call |
| `POST /api/v1/integrations/gmail/verify` | Refreshes if needed and verifies identity against Google; no mailbox messages accessed |
| `POST /api/v1/integrations/gmail/disconnect` | Attempts remote revocation, clears local secrets and cancels pending connection intents |

Open the returned authorization URL and explicitly select the secondary account. The expected
email is required either in configuration or the authenticated start request. A configured
email cannot be overridden. Google `login_hint` is only UI guidance: the backend independently
checks the verified UserInfo email, immutable `sub`, and Gmail profile address. It does not
trust an unverified decoded ID token. A different account is rejected. An active connection
cannot be overwritten; disconnect first, then intentionally authorize a new expected address.

State is random (256 bits), only its SHA-256 digest is stored, expires in ten minutes by
default, and is atomically consumed once. A separate random HttpOnly SameSite=Lax cookie binds
the browser; it is Secure for HTTPS callbacks and never acts as ordinary API login. The PKCE
S256 verifier is encrypted in the durable state row. The callback supplies it in the code
exchange with client authentication. Denied consent and failed exchanges consume the intent;
start again rather than replay. Duplicate callback parameters are rejected.

Provider transaction locks, row locks and an intent generation prevent concurrent callbacks,
refreshes or a callback already exchanging a code from overwriting a newer connection or
undoing a disconnect. Access tokens are cached encrypted until shortly before expiry.
Refresh verifies the stable subject and email again. Revocation/invalid credentials or scope
changes mark `reauthorization_required`; no silent account switch occurs.

Disconnect always removes local tokens, even if Google revocation cannot be confirmed. In
that case the response instructs revocation through Google Account → Security → Third-party
connections. Google revocation can revoke the project's grant across its clients; use a
dedicated project/client for this workflow. Existing legacy environment tokens are not read,
overwritten, automatically migrated or revoked by this connection service.

## Storage, migration and key rotation

Apply **006 after 001–005** only to a separately authorized environment. The application never
runs migrations at startup. `connected_accounts` has one owner connection slot for Gmail;
`oauth_states` stores expiring single-use intents. `outreach_logs` is extended, not replaced.
RLS is enabled with no public/client policies; PUBLIC, anon and authenticated grants are
revoked. Only the backend owner/BYPASSRLS service role accesses tokens. Do not expose these
models through Supabase client APIs. SQL parameter echo remains disabled.

Generate a random Fernet key with `cryptography.fernet.Fernet.generate_key()` in a secure
operator environment. Set `OAUTH_ENCRYPTION_KEYS` to a JSON mapping of immutable key IDs to
keys and `OAUTH_ACTIVE_KEY_ID` to the current ID. An empty/invalid keyring fails closed.
OAuth encryption never derives from the repository's permissive legacy `SECRET_KEY` default.
Fernet authenticates ciphertext; envelopes bind secrets to the account ID/token purpose or
OAuth state digest and include a key fingerprint. Replacing a key under the same ID or
copying ciphertext to another account/purpose causes explicit decryption failure.

Back up encrypted database data and keyring separately with restricted access. To rotate,
add a new ID/key while retaining old keys and switch the active ID. Successful refreshes
re-encrypt the refresh/access tokens with the active key. Pending intents may still use old
keys until they expire. Reconnect or explicitly re-encrypt all remaining envelopes in an
authorized maintenance transaction before retiring an old key. Check stored envelope key IDs
without printing ciphertext or keys. Lost keys require account reconnection, not plaintext
fallback. Expired/consumed OAuth intent rows can be purged by authorized maintenance after a
retention period; deleting them cannot make expired/replayed states valid again.

Uvicorn's access logger redacts OAuth callback query strings. Configure ingress/APM/access
logs likewise; do not record request/response bodies or headers for these private endpoints.
Responses have `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.

The old `backend/scripts/setup_gmail_oauth.py` command is retired: its loopback flow lacked
state/PKCE/identity binding and wrote refresh tokens directly to `.env`. It now exits with
connection-endpoint instructions and never reads CLI credentials, opens a browser or changes
existing configuration. The legacy parser library remains compatible with previously configured
credentials, but is not used as an alternative account-connection or discovery route.

## Phase 4B send authorization

Send `authorization_mode: "send"` to the existing authenticated connect/start endpoint after
connecting metadata. The durable PKCE state also binds the expected Google subject and mode.
Failed consent/identity/scope checks preserve the connection. Missing new refresh tokens fail
closed. See [approved sending](gmail-approved-sending.md) for capability states, controlled
reconnection, explicit preview/confirmation, idempotency, limits and migration 007. Approval
alone never sends. Google OAuth verification is an operational prerequisite where applicable.
