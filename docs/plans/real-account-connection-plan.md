# Real account connection plan

Verified repository/research date: **2026-10-21**. This run performs no account connection,
consent, private import, send or notification. See [provider evidence](free-platform-capability-matrix.md)
for official scopes, pricing, restrictions and unknown entitlements; this document specifies
owner actions and proof. Never put tokens, account archives, actual resumes or consent screenshots
containing credentials into Git or a PR.

## Establish trust before adding accounts

Finish Phase 9A recovery and separately authorized 9B activation first. Reuse
`integrations/connection_service.py`, `google_oauth.py`, `token_store.py`,
`models/connected_account.py`, protected integration routes and existing connection frontend.
The token store supports context-bound encrypted envelopes and a named keyring. Preserve old
key IDs until ciphertext migration/recovery is verified. The PDF key, OAuth keys, owner session
secret and backend API token are separate; do not derive one from another or rotate blindly.
Credentials stay backend-only. No service-role or database credential belongs in Next.js public
variables. For one Mac, user-owned 0600 ignored configuration is sufficient; no paid secret vault.

Connection states must preserve **unconfigured → configured → owner authorization pending →
identity/scopes verified → supported live operation verified**, plus expired/revoked/degraded.
Manual links and imported alerts are not account connections. A successful token refresh alone
does not establish mailbox identity or feature scope. Health evidence expires; last success and
last failed verification must both remain visible.

## Owner action checklist and activation proof

| Stage | Owner action / actual configuration | Engineer verification / what stays gated |
| --- | --- | --- |
| 9A | Official Connect/TLS/CA details and existing password via ignored helper; independent age identity retrieval; plan/backup entitlement and existing-app health/window | TLS hostname/chain + exact tenant mapping + read-only catalog, successful encrypted export/isolated full restore; no R2 |
| 9B | Separate approval for pinned schema/role SQL and private runtime credential provision | Restricted real PG access, existing-app preservation and authorized one-row/restart proof; 012 not implied |
| 10 | Review precise merged revision, migration 012 and role addendum separately; selected free sources/boards; later approve worker activation | Neither merge nor migration starts a worker; operational and saved schedule gates remain off until chosen |
| 11 | Set owner passphrase/session/API material; privately select real PDF or approved Drive source; authorize one import | Encrypted DB storage/retrieval/restart, anonymous denial; extraction remains proposals until owner review |
| 11 | Confirm education, roles, projects, individual links, preferences, notice, CTC/expected CTC where actually known | Unknown stays null; minimum preferred salary is not current/expected CTC; self assertions labeled owner-approved |
| 12 | Select verified employer board IDs and approve a bounded free read/save pilot | Actual HTTP status/time, observation/job IDs, source attribution and fresh destination; mocks cannot close this gate |
| Optional 12 | Secondary Gmail OAuth client/redirect/identity and read-only alert consent after code review | Existing metadata-only connection insufficient; actual granted scopes, identity and one bounded redacted alert-ingestion receipt |
| Optional 13 | Choose native local model; allow purposeful model download and owner-reviewed evidence use | Synthetic evaluation first; private prompts local only; no cloud model or paid key |
| 14 | Create official bot, initiate private chat, enter token locally; approve numeric recipient and opt in; separately authorize one test send | Verify challenge/chat type, bot identity, redaction and actual returned message ID; no first send merely from token presence |
| 15A | Review exact packet/resume/destination and manually complete official form | Save manual handoff without submission claim; only explicit actual submission report changes submitted state |
| Conditional 15B | Supply documented employer/platform permission and approve exact attempt/destination/packet revision | No private portal API, cookies, stealth or CAPTCHA/MFA automation. Credentials/form actions stay blocked if permission absent |
| 16 | Select public official company/contact evidence, review freshness/recipient and outreach draft | No enrichment subscription; guessed email unverified; message sending remains separate explicit approval |
| 17 | Choose operating hours, retention, backup destination, incident procedure and acceptable recovery window | Restore/health/quota/sleep/outage pilot passes; no invented 24×7 availability |

## Secondary Gmail: reuse supported OAuth, replace legacy intake

1. Owner opens Google Cloud/Google Auth Platform manually, selects a free project with **billing
   disabled**, enables Gmail API and configures an OAuth web client/consent screen. Add only the
   designated secondary account as a test user when using Testing; accept its documented token
   expiry. Do not activate a credit-card trial or request increased quotas.
2. Privately configure existing `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REDIRECT_URI`,
   `GMAIL_EXPECTED_EMAIL`, `OAUTH_ENCRYPTION_KEYS` and `OAUTH_ACTIVE_KEY_ID`. Never copy a raw
   refresh token into chat or use legacy `GMAIL_REFRESH_TOKEN` for new onboarding.
3. Reuse the existing browser-bound authorization-code/PKCE flow. Registered callback is exactly
   `/api/v1/integrations/gmail/oauth/callback`; route it to FastAPI on the frontend hostname.
   The OAuth browser-binding cookie must reach this callback. Separate ports/origins must be
   deliberately tested; don't assume an unrelated remote API hostname shares that cookie.
4. Main's identity/metadata scopes do not authorize alert-body ingestion. The local
   `feat/phase11-real-account-workflows` branch proposes read consent/intake and migration 013.
   Review its exact-account incremental authorization, token scoping, diagnostics, retention,
   BFF routes and PostgreSQL tests after reconciling Phase 10. Preserve existing consent/send
   safety. Adding 013 requires its own manifest/role/activation review; do not run it here.
5. Only after separate read consent, poll a narrow owner-selected alert label/sender set,
   bound message/page counts and MIME bytes, decode actual parts and verify per-job associations.
   Sender display text and “jobs” keywords are not authentication. Retain minimal derived
   observations; no inbox-wide LLM analysis or arbitrary link fetch from messages. Content
   rights review still applies. Strip tracking where safe while preserving actual destinations.
6. Mark invalid-grant/expiry/revocation as authorization required, stop polling, notify in-app;
   never retry indefinitely or silently consent to more scopes. Owner may disconnect/revoke.

Sending remains `GMAIL_SENDING_ENABLED=false` throughout discovery onboarding. If later selected,
use existing separate gmail.send authorization plus exact-content single-use confirmation and
limits in [approved sending](../gmail-approved-sending.md). Manual Gmail sending is a complete
free alternative. A Gmail API acceptance receipt proves acceptance, not delivery or a read.
Restricted-scope verification/personal-use eligibility is conditional; a mandatory paid assessment
would disqualify that deployment under ₹0 and require manual import instead.

## Resume, Drive and GitHub

**Default:** owner downloads their own real Drive PDF manually and uploads it through the existing
authenticated resume interface after permission. This avoids making a private resume public or
needing broad Drive consent. Existing `resume_sync/` only downloads an explicitly shared public
file; a Drive URL or setting is not an authenticated account connection. If the owner chooses
that workflow, set existing `CANDIDATE_RESUME_DRIVE_URL`/optional matching file ID privately,
sync once, then review diffs/facts and activate the resource. Preserve all prior encrypted
versions; keep `RESUME_DRIVE_SYNC_ENABLED=false` until periodic checks are explicitly selected.
Changing the public sharing setting is an owner action, not an automatic setup step.

Private Drive OAuth is optional future work: select-file Picker consent and `drive.file`, encrypted
token storage, explicit file grant, revoked-file tests and owner review on changes. Do not reuse
Gmail tokens as implicit Drive authorization or request Drive-wide access for one file.

For GitHub, start with owner-approved repository URLs and manually confirmed project claims,
which the existing resource/evidence model already stores. A later read-only API adapter may
fetch selected public README/metadata at pinned commits without a token. If limits/private repos
require a fine-grained token, owner creates it with selected-repository Contents read/Metadata
read and no write scopes. Token expiry is intentional and supported. Never reuse Codex's GitHub
connector/gh credentials as application runtime credentials. Repository ownership does not prove
individual contribution, employment, outcomes or every statement in a README.

## Telegram: official private recipient enrollment

Owner uses official BotFather `/newbot`, retains the token in private local configuration and
starts a private conversation. No existing Telegram app variables or endpoints exist in main;
Phase 14 must define them in a reviewed change, with secrets excluded from API responses.

Proposed enrollment: owner UI starts a short-lived random challenge; a backend-only `getUpdates`
poller accepts an exact challenge from a private chat, stores proposed numeric chat/user IDs,
and shows a masked recipient confirmation. Only the authenticated owner can bind it. A display
name/username, group chat or forwarded message is insufficient. `getMe` verifies bot identity;
receiver verification does not send a notification. Avoid webhooks initially: local outbound
polling needs no public ingress. No token-bearing URL in logs, exceptions, browser history or
process arguments. Do not interfere with an existing webhook/other consumer without owner action.

After explicit opt-in and authorization for one test, return actual Telegram message ID/time as
API acceptance proof and ask the owner to confirm receipt. Bot API acceptance is not proof read.
Only redacted titles and a non-secret workspace path are sent. A localhost link works only on
the Mac; mobile remote access is a separate approved ingress decision, not a broken-link promise.
No bot command can approve application submission or recruiter sending. Rotate a compromised bot
token through BotFather, pause delivery, verify the same intended recipient before resuming.

## Closed portals and optional contacts

LinkedIn account research automation remains unavailable by default; the secondary-account
proposal conflicts with the current one-account policy. Keep the primary account's messages and
connections manual. Do not collect portal passwords, cookies, MFA codes or browser profiles.
Naukri, Instahyre, Wellfound, Internshala, Foundit, Indeed and YC use manual official interfaces,
permitted alert references and employer ATS alternatives. There is no honest “connected” badge
for a saved website link.

Apollo/SignalHire are optional **disabled** code, not owner tasks on the critical path. Do not
ask the owner to buy a work domain, install a LinkedIn extension, add a payment method or use
trial credits to meet acceptance. Before any genuinely free optional call, verify exact endpoint
entitlement, recurring quota/expiry/overage controls, source/retention rights and owner consent.
Contact status must distinguish published, provider-reported, pattern-guessed and mailbox-verified;
none establishes consent to receive outreach. Retain suppressions and respect corrections.

## Final live connection evidence

For each activated feature retain an ignored private receipt with release SHA, intended target,
bot/account identity (redacted in shared summaries), scopes, consent time, exact supported
operation, sanitized response status/IDs, stored entity IDs, tested revoke/failure behavior,
quota/cost outcome and evidence expiry. Never retain OAuth codes/tokens, decrypted backups,
private PDF text or message bodies in general logs. Share only sanitized counts/statuses in PRs.
All unresolved items remain visibly “not connected / not verified.”
