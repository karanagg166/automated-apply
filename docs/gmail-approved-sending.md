# Approved Gmail sending (Phase 4B)

Sending is disabled by default. Draft creation, editing, approval, MCP requests and background
work never send email. Only the authenticated owner REST flow below can initiate one message.
This implementation is tested with injected clients and HTTP mocks; no live send is implied.

## Authorization and account identity

Keep the existing Google Cloud Web OAuth client, redirect URI, secondary Gmail account and
versioned encrypted token store described in [Gmail connection](gmail-oauth-connection.md).
First connect in the default `metadata` mode. For sending, the owner separately requests:

```http
POST /api/v1/integrations/gmail/connect/start
Authorization: Bearer <owner-api-token>
Content-Type: application/json

{"expected_email":"secondary@example.com","authorization_mode":"send"}
```

Use the same browser/cookie context for this request and the OAuth callback. Open the returned
URL and review Google's consent screen. The request uses offline access, explicit consent,
PKCE S256 and the existing durable, browser-bound, single-use state. It requests exactly:

| Mode | Scopes |
| --- | --- |
| metadata | `openid`, `https://www.googleapis.com/auth/userinfo.email`, `https://www.googleapis.com/auth/gmail.metadata` |
| send upgrade | All metadata scopes plus `https://www.googleapis.com/auth/gmail.send` |

The backend checks the actual token-response scopes, verified UserInfo email, immutable Google
subject and Gmail profile address. Both email and subject must match the connected account.
Extra scopes, missing send permission, a different Google account or missing new refresh token
reject the upgrade. Credentials are replaced only after all checks succeed under the connection
lock. A failed upgrade leaves the prior connection/credentials intact. Concurrent intents are
superseded by the newest connection generation. Disconnect cancels pending intents.

The combined scope request has `include_granted_scopes=false` to avoid importing unrelated
previous permissions; the resulting exact set is checked. Ordinary refresh does not request
scopes and may neither expand nor downgrade the saved set. Missing refresh-response scope uses
the existing grant, as in the existing OAuth lifecycle. Revoked/reduced grants require consent
again. The existing account ID remains stable; successful reauthorization changes its connection
binding and invalidates old send previews. Refresh alone does not invalidate previews.

If Google omits a new refresh token, repeat explicit consent. If necessary, intentionally
**disconnect**, revoke this dedicated app's grant in Google Account settings, reconnect the
same secondary account in metadata mode, then upgrade. Revocation can affect the app's combined
grant. Switching accounts requires deliberate disconnect and a new expected address; never
silently overwrite the sender. No legacy environment refresh token is imported.

`GET /api/v1/integrations/gmail/status` separates `oauth_configured`, `sending_enabled`,
`authorization_state` and `send_capability`. States include `not_connected`, `metadata_connected`,
`send_authorization_required`, `send_authorized`, `reauthorization_required`, and `disconnected`.
The lifecycle `status` remains compatible with Phase 4A. Saved `live_verified` means an identity
check was recorded, not that a future send will succeed. Configuration is not live authorization.

Google documents `gmail.send` as sensitive and the retained `gmail.metadata` scope as restricted.
External public distribution generally requires applicable OAuth verification, with restricted
scope/security-assessment requirements where applicable. Personal-use, test-user and internal
organization exceptions have conditions; review the actual audience and data handling before
publication. Test-mode grants can expire and Workspace policy may block authorization. Keep
OAuth client secrets server-side, set an accurate consent screen/privacy policy and register
only exact approved redirect URIs. This phase does not establish Google verification approval.
See Google's [scope classification](https://developers.google.com/workspace/gmail/api/auth/scopes),
[sensitive verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification),
[restricted verification](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification),
and [web-server OAuth flow](https://developers.google.com/identity/protocols/oauth2/web-server).

## Exact owner workflow

1. Create a grounded local draft, inspect/edit it and approve its exact revision through the
   existing [draft API](outreach-drafting.md). Approval has no Gmail side effects.
2. Explicitly request `POST /api/v1/outreach/drafts/{draft_id}/send-preview` with the owner bearer.
   This performs no Google request. It returns the exact `sender`, `recipient`, `subject`, `body`,
   `sender_account_id`, `draft_revision`, `approval_hash`, `confirmation_token`, expiry, and flags
   `approval_current`, `eligible_to_send`, `send_confirmation_required`.
3. The owner's client must display all four message fields before asking the human to confirm.
   Keep the one-time token private; do not expose the owner bearer or confirmation to an AI agent,
   MCP client, task runner or shared browser storage. No frontend is introduced in this phase;
   the REST preview is the review surface for a trusted owner client.
4. After that separate human decision, submit the exact preview context:

```http
POST /api/v1/outreach/drafts/{draft_id}/send
Authorization: Bearer <owner-api-token>
Content-Type: application/json

{
  "expected_revision": 4,
  "approval_hash": "<64-lowercase-hex-digest-from-preview>",
  "confirmation_token": "<43-character-one-time-token-from-preview>",
  "sender_account_id": "<UUID-from-preview>",
  "idempotency_key": "owner-request-unique-123"
}
```

Values above are placeholders, not executable credentials. A boolean is insufficient. Unknown
fields (including caller-supplied From/CC/BCC/provider IDs) are rejected. Keep the same request
and idempotency key when checking a lost HTTP response; do not obtain a new key to resend.

A cryptographically random challenge is stored only as a SHA-256 hash. Its immutable record
binds draft ID/revision, approval hash, sender ID/email/Google subject/authorization time,
recipient, subject/body digest, evidence digest, owner actor and expiry (default five minutes).
Consumption and reservation commit in one transaction. Replays, mismatches, expiration or
changed draft/evidence/sender authorization fail closed. Validation also reruns immediately
before the external call. Contact suppression, identity conflicts, employer mismatch, stale
contact evidence, changed candidate facts, speculative email or provider-reported email alone
block sending. Fresh supported mailbox-verification evidence and reviewed contact status are
required. Blocked eligibility is HTTP 409 with `detail.code=send_blocked` and a `blockers` list.

The authentication boundary is the existing single-owner REST bearer, separate from the MCP
bearer. It identifies `owner`; it is not multi-user/session authentication or proof of a physical
button click. Trusted owner clients are responsible for human interaction. Do not distribute
that bearer to agents. There is no admin override, send MCP tool, worker, schedule or campaign.

## Reservation, concurrency and crashes

`GmailSendingService` reuses `OutreachDraftingService`, `ConnectionService`, encrypted tokens,
contact verification and database sessions. Sending never generates or rewrites message text.
It commits a `prepared` attempt before Gmail, then commits `attempting` before transmission.
The attempt stores immutable approved subject/body, evidence/content digests, sender/recipient,
revision, request digest, idempotency key and deterministic RFC Message-ID. There is one permanent
attempt per outreach draft across every revision, even after a definite failure. This conservative
phase does not expose a retry/resend operation. Editing/review actions reject reserved drafts.

PostgreSQL is required outside tests. Shared transaction advisory locks serialize connection
lifecycle and reservation/cap checks across processes. Row locks hold draft, employer, contact,
profile and evidence stable while calling Gmail. Edits/suppression/disconnection serialize with
the in-flight send; an already accepted email cannot be recalled by subsequent suppression.
Unique indexes enforce one draft reservation, one consent consumption and unique request keys.
A repeated identical key/request returns the existing attempt without another Google request.
Different keys or changed request context cannot bypass the reservation.

| State | Meaning / legal next state |
| --- | --- |
| `prepared` | Committed claim, no transmission initiated; `attempting` or `failed_before_send` |
| `attempting` | Durable external-call intent; `accepted_by_gmail`, `failed_before_send`, or `outcome_unknown` |
| `accepted_by_gmail` | Valid success response and Gmail message ID recorded; terminal |
| `failed_before_send` | No known accepted send: local preflight/connection failure or explicit Gmail rejection; audited reconciliation only |
| `outcome_unknown` | Transmission/response/persistence interrupted; audited reconciliation only |
| `manually_reconciled` | Owner recorded evidence/disposition; terminal, never enables retry |

Connect/pool failures known to precede transmission and explicit 400/401/403/404/429 responses
record a fixed failure category. Gmail 401/403 also marks the connection for reauthorization.
Write/read timeouts, cancellation, server errors, redirects and malformed success responses
are uncertain. No send is retried automatically, including 429/5xx. An unexpected process
exception leaves durable `attempting`; failure persisting the provider response rolls back to
that state and reports reconciliation required. The Gmail response is never guessed.

Status/history checks classify abandoned `prepared`/`attempting` records after twice the send
timeout plus 60 seconds: prepared becomes a definite interrupted failure; attempting becomes
unknown. These checks never dispatch mail. They acquire row locks so they cannot overwrite a
live locked result. A restart must not resume prepared/attempting sends. If the database is
unavailable, restore it and query status before any further action.

There is no atomic transaction spanning PostgreSQL and Gmail. A lost response after Gmail
acceptance can leave no provider ID in the database. The deterministic Message-ID is a manual
correlation aid, **not Gmail deduplication**. Gmail's send method has no application idempotency
key. This design prevents automatic duplicate invocations for a draft; it does not promise
exactly-once external delivery. See [messages.send](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/send).

## MIME and outcome semantics

The narrow adapter sends only `POST https://gmail.googleapis.com/gmail/v1/users/me/messages/send`
with JSON `{"raw":"<base64url RFC MIME>"}`. Python's email library emits UTF-8 plain text, encoded
subjects, CRLF serialization, a server-owned Date and deterministic Message-ID. Sender comes only
from the bound account. Bare validated addresses, header-control rejection and fixed header
construction prevent header injection. One To only; no arbitrary headers, aliases, attachments,
CC, BCC, HTML, pixels or tracking. See Google's [MIME sending guide](https://developers.google.com/workspace/gmail/api/guides/sending).

Gmail acceptance records a provider message ID, optional thread ID and acceptance timestamp in
the attempt. The existing OutreachLog Gmail IDs and `sent_at` mirror that acceptance without
changing its approved revision; `sent_at` means Gmail acceptance only. Approval remains review
history, and `delivery_status` identifies the attempt state. Never equate this with delivery or
reading. Bounces, filtering and final recipient delivery remain unknown. `gmail.send` does not
grant inbox reading; metadata does not grant message-body/search-based reconciliation. Bounce
monitoring or automated reconciliation is future separately authorized permission/workflow work.

`GET /api/v1/outreach/send-attempts/{attempt_id}` reports state, draft/revision, sender/account,
recipient, IDs/times, fixed error category and reconciliation flag. `GET /api/v1/outreach/history?limit=20&offset=0`
returns a bounded timeline of attempts and local/legacy records, without duplicates. Legacy sent
records are `legacy_sent_unverified`, with the recorded historic time and no invented acceptance.
Historical attempts remain readable after suppression/disconnect. API responses are no-store.

## Limits and operations

```dotenv
GMAIL_SENDING_ENABLED=false
GMAIL_SEND_MAX_PER_DAY=10
GMAIL_SEND_MAX_PER_HOUR=3
GMAIL_SEND_MAX_RECIPIENTS=1
GMAIL_SEND_TIMEOUT_SECONDS=20
GMAIL_REQUIRE_EXPLICIT_CONFIRMATION=true
GMAIL_CONFIRMATION_TTL_SECONDS=300
```

Caps use rolling 24-hour/one-hour UTC reservation windows across all sender lifecycles/processes.
All reservations count, including failed, prepared and unknown attempts, conservatively. Zero
stops new sends. Preview checks current limits; reservation checks again atomically. Switching
an account never resets usage. There are no batches, follow-ups, provider rotation or queues.
Recipient count and confirmation cannot be relaxed by configuration. Sending stays disabled
until the owner authorizes the secondary account and intentionally enables it.

For an unknown outcome, inspect the dedicated sender's Gmail UI manually using the RFC
Message-ID, recipient, subject and attempt time. A matching sent item establishes a sender-side
record, not recipient delivery. Do not assume absence proves no transmission. Retain the
reservation. Under separate authorized operational access, a backend database transaction can
close an unknown/failed attempt with `status='manually_reconciled'`, `reconciled_by='owner'`,
`reconciled_at`, a substantive `reconciliation_note`, and `reconciliation_required=false`.
Include the operator's evidence reference/disposition without secrets. Only record real Gmail
IDs and an acceptance time when the evidence supports them. The trigger requires an audit
record and forbids reopening; do not delete attempts, manufacture IDs or resend during
reconciliation. There is deliberately no public reconciliation/resend endpoint.

Disconnection clears local credentials and attempts revocation; it never deletes history. A
fresh consent is required for revoked/insufficient credentials. Disable sending globally during
incident review. Restrict database/keyring backups, enforce TLS, protect the owner bearer and
redact bodies, authorization headers, callback queries and confirmation tokens in proxy/APM
logs. The backend never logs raw messages, token values or provider response bodies.

## Migration and offline verification

Apply `007_gmail_sending.sql` **after 001–006** in a separately authorized environment. It adds
`outreach_send_confirmations`, `outreach_send_attempts` and OAuth intent mode/subject columns.
It replaces the 006 guard function in place while preserving approval invalidation, revisions
and old records. New delivery metadata requires a matching accepted attempt. Immutable attempt
identities and legal-transition triggers protect history. RLS has no client policies; PUBLIC,
anon and authenticated have no grants. Only trusted backend roles have SELECT/INSERT/UPDATE;
DELETE is withheld and triggers prevent audit deletion. Public schema and migrations 001–006
are unchanged. The application never applies DDL on startup. Database administrators remain
trusted; constraints cannot independently verify that an HTTP response actually came from Google.

```bash
PROFILE_TEST_DATABASE_URL=postgresql://<test-user>:<test-password>@127.0.0.1:5432/candidate_profile_test \
  backend/venv/bin/pytest backend/tests -q
```

The PostgreSQL tests create/drop disposable child databases and verify 001–007, replay, legacy
preservation, grants/RLS, rollback, multiple independent workers, caps, confirmation replay and
triggers. HTTP transports deny real external traffic. Without the local URL PostgreSQL tests
skip; this is insufficient for release verification. CI provides a disposable PostgreSQL service.

## Production rollout checklist

- [ ] Review the final code/CI and back up data/keyring; authorize migration/deployment separately.
- [ ] Apply 001–007 in order with the proper backend role; verify client grants remain revoked.
- [ ] Configure TLS, redirect URI, dedicated secondary account, owner bearer, OAuth client and keyring.
- [ ] Confirm Google consent-screen audience, verification/policy requirements and Workspace restrictions.
- [ ] Connect metadata and explicitly upgrade send permission; independently verify the expected identity.
- [ ] Keep sending disabled until trusted owner-client preview/confirmation handling has been reviewed.
- [ ] Set conservative caps/timeouts, protect private logs and establish unknown-outcome review procedures.
- [ ] Any first real send requires the owner's separate preview and explicit confirmation.

No real account connection, send authorization, production migration, deployment or email send
is performed by implementation, tests or CI. Phase 5 remains separate work.
