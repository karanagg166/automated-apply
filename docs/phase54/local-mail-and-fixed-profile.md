# Local mail and fixed Chrome profile

This additive phase uses the merged Phase 5.3 implementation. It changes no schema,
dependency lock, employer submission capability or hosted workflow.

The owner's latest scope supersedes the earlier two-mailbox activation request:
one selected Chrome profile and one explicitly approved mailbox. Private account
addresses, browser paths/UUIDs, test receipts and installation records stay outside Git.

## Fixed Chrome identity

`chr_fixed_profile` in the protected owner store maps the owner-visible label and
the exact directory displayed at `chrome://version` to the existing authenticated
extension UUID. The UUID remains the routing authority. Selecting another UUID is
refused, and native work and command admission check the pin. Disconnect/Stop and
late receipt preservation remain available. A deliberate owner-requested replacement
must first Stop/fence work, revoke the prior profile, verify the new directory and
UUID, then replace the pin under the existing owner lock. Preserve the old mapping.

The optional launcher defaults off. Both its deployment flag and the mapping's
`automatic_launch_enabled` must be true. Only a running authorized scheduler can
attempt startup, only a verified normal Chrome directory is accepted, and an
existing Chrome process prevents a background launch. Startup uses LaunchServices
with the exact `--profile-directory`; there is no alternate user-data root,
debugging port, Playwright fallback or adoption of the most recently opened profile.
Attempts are persisted and spaced five minutes apart. Stop serializes with the
bounded process launch. A successful launch still returns `PROFILE_OFFLINE` until
the authenticated binding supplies a fresh heartbeat. Existing command/session
fences protect actual work; a heartbeat is not DOM evidence.

The selected profile must load the reviewed immutable `extension/dist`, stable ID
and native host through Chrome's normal UI. Protected extension loading is never
automated through a privileged Chrome API. AppleScript setup checks require Chrome's
normal **View → Developer → Allow JavaScript from Apple Events** setting in that
profile. Extension/native command routing does not require that setting.

## Gmail API connection

Use the existing official OAuth client, PKCE, browser-bound one-time state and
context-bound encryption keyring. Each local account requests exactly OpenID,
verified email, Gmail readonly and compose. Compose itself includes sending; these
accounts expose only bounded GETs and draft creation, and are never supplied to the
legacy sending service. `GMAIL_SENDING_ENABLED` remains false.

`GMAIL_LOCAL_ALLOWED_EMAILS` must explicitly list approved identities (maximum two).
A one-address deployment displays one account slot. OAuth rejects any other
verified identity; access and legacy read/draft token paths also enforce this list.
Each slot has its own browser cookie, generation, encrypted tokens, refresh lease
and failure state. No existing credential is automatically reused or migrated.
Refresh cannot change identity or scope. Disconnect invalidates outstanding work,
scrubs local tokens and attempts Google revocation without a mailbox operation.

On-demand searches inspect up to five messages in Inbox, with no historical loop.
Body reading requires its deployment review flag and a recent account-bound message
selection. Bodies are parsed transiently; attachments and links are never fetched.
The read response contains headers and safe parsing evidence, not a persisted body.
Sender-domain matching is explicitly not authenticated-origin proof.

Reviewed general drafts require the exact content hash, current account generation
and a stable request UUID. Only `users.drafts.create` is used for writing. A durable
fence commits before dispatch. Retrying an uncertain dispatch only reconciles by a
server-generated RFC Message-ID; it never repeats the POST. Once Google's stable
draft resource ID is recorded, retries read that exact draft directly. The live
test showed Google replacing the submitted RFC Message-ID, so verification checks
the stable draft ID, exact sender, sole recipient, subject, body and DRAFT status,
rejecting extra recipients and duplicate critical headers. The one-time self-test
draft additionally searches Sent for both the submitted and returned Message-IDs.
An ambiguous dispatch without a recorded draft ID remains blocked if the original
marker cannot be reconciled; it never creates a replacement draft.
Deleting/sending/editing a draft remains a
separate human Gmail operation; the application provides no such operation.

Google's official Gmail MCP currently requires Developer Preview membership and
separate Cloud/API/OAuth setup. Account eligibility has not been established.
The existing API is retained: it provides the necessary operations without a new
host, subscription or preview dependency. Standard Gmail API use is currently free
within Google's published thresholds; these small bounded operations require no
quota increase or paid provider. Sources:
[MCP setup](https://developers.google.com/workspace/gmail/api/guides/configure-mcp-server),
[scope definitions](https://developers.google.com/workspace/gmail/api/auth/scopes),
[usage and pricing](https://developers.google.com/workspace/gmail/api/reference/quota).

No Gmail polling is enabled. The separate alert-candidate helper requires explicit
intake authorization, rejects non-Naukri sender domains and unsafe/non-posting URLs,
deduplicates by requisition across approved sources, and retains account/message
references. Origin authenticity and missing job facts remain unresolved. It cannot
mark a vacancy verified, prepare invented facts, confirm a submission or open a
tracking link. A specific monitoring policy and genuine alert evidence are still
required before connecting it to recurring discovery.

## Optional Apple Mail

`APPLE_MAIL_ENABLED=false` by default. Its account policy is keyed by Mail's stable
account ID, with one exact address, explicit Inbox/Drafts mailbox names, separate
read/draft flags, exact sender allowlists and a recent 1–30-day window. The app lists
only approved accounts. Search reads bounded selected-folder metadata; a body read
requires a recent policy-bound selection. Exact sender checks reject lookalikes.

The adapter uses the scripting dictionary shipped inside Mail.app. It never reads
Mail databases or passwords/tokens. The fixed JXA script receives JSON arguments;
it has no send, delete, forward or account-configuration action. Draft creation uses
`make`/`save`, then checks the selected account's Drafts mailbox independently. A
stable request fence prevents repeat creation after an ambiguous outcome. No raw
message body is stored. Normal macOS Automation permission to control Mail may
require an owner click for the actual invoking process; permission from an editor
session does not establish LaunchAgent permission.

Operator entry point (private output files are created mode 0600):

```sh
python backend/scripts/local_mail.py discover --env-file /PRIVATE/settings.env --output /PRIVATE/accounts.json
python backend/scripts/local_mail.py search --env-file /PRIVATE/settings.env --account-id APPROVED_ID --output /PRIVATE/selected.json
python backend/scripts/local_mail.py read --env-file /PRIVATE/settings.env --account-id APPROVED_ID --message-id SELECTED_ID --output /PRIVATE/read.json
python backend/scripts/local_mail.py draft --env-file /PRIVATE/settings.env --account-id APPROVED_ID --draft-file /PRIVATE/reviewed-draft.json --output /PRIVATE/draft-receipt.json
```

`discover` is an explicit account-name discovery action, never an automatic scan.
The optional adapter is not a replacement for Gmail OAuth background connectivity.

## Actual acceptance and remaining evidence

Private live receipts record a genuine Mail read of one owner-authorized alternate
newsletter and one self-addressed test draft independently found in Drafts. No
Naukri message was available in that test, so it establishes no genuine job-alert
intake. No sending operation was invoked. Fictional tests separately cover account
isolation, consent, token contexts, idempotency, uncertain dispatch and deduplication.

The actual Mac's privacy log attributed the prior Chrome metadata denial to VS Code,
the responsible app for its Codex/Python child. A later read and TCC result confirm
that Full Disk Access is now allowed. Chrome identity routing uses the extension
UUID and needs no ongoing profile-file read. No security database was changed.

The installed Phase 5.3 monitor produced genuine worker/browser/database samples
but reported UNKNOWN screen state on this macOS version. The compatibility fix
accepts `IOConsoleLocked` only when the sole active console belongs to the exact
current user. Conflicting, missing or ambiguous telemetry remains UNKNOWN. New
locked-session, genuine DOM and Telegram evidence must be recorded separately;
the earlier heartbeat samples are not a locked-session DOM PASS.

Naukri submission remains unsupported. Genuine matching/preparation requires a
selected current job, verified candidate facts and bounded preparation policy.
No short acceptance interval proves continuous uptime.
