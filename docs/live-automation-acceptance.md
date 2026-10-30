# Live preparation and Gmail discovery recovery

The installed acceptance failure occurs after native command admission. A
generic native `backend_not_ready` response previously hid transaction failures.
Repeated packet freshness reads held the global owner lock over many remote SQL
round trips, competing with worker claims and browser heartbeats. Each readiness
probe also repeated the full database catalog audit on the small runtime pool.

The changes on this branch:

- Keep the full schema, grants, runtime identity and TLS audit at startup. Each
  readiness request makes a bounded live database/role/TLS/core-grants read instead of
  repeating the catalog audit. Dependency failures still return 503.
- Keep read-only task checkpoints out of the global execution lock. The complete
  context is still checked, and all mutators reacquire the owner lock. Interrupted
  fill checks retain owner-before-packet lock ordering.
- Reuse the packet returned by plan freshness validation during attachment.
- Identify explicit PostgreSQL transaction aborts after rollback. Only native
  database operations may retry these responses, with the same request ID and
  payload, at most three attempts inside a bounded deadline. Authentication
  failures, connection loss, timeout and unknown outcomes are never replayed.
  Fill authorization and receipts are excluded from retries.
- Preserve the original 90-second lease and 120-second command expiration. The
  extension uses the earlier deadline and passes command fencing into backend
  task/inspection calls. Long inspections recheck the lease before publishing.
- Save a read-only `NEEDS_INPUT` inspection when a Naukri posting has no verified
  application form. Search controls remain excluded; Apply is never clicked.
- Record API, independent database, liveness and readiness observations
  separately, with durations, errors, observation gaps and lock state before and
  after each bounded monitor sample. A monitor timeout is not a worker failure.

## Approved local Gmail alert intake

The existing local OAuth account store supplies tokens; no second OAuth flow or
new scope is needed. Per-account consent is configured with
`PUT /api/v1/integrations/gmail/local/accounts/{slot}/job-alerts`; a bounded cycle
is requested with `POST .../{slot}/job-alerts/sync`. The connected-account UI
exposes both controls. The execution worker performs due reads while automation
is RUNNING. PAUSE, STOP, policy version and account generation fence reads and
publication. Monitoring remains opt-in and sending remains disabled.

The source is the Inbox sender `naukrialerts@naukri.com`, which Naukri identifies
in its [official alert guidance](https://w10.naukri.com/mailers/revamp_3aug10/index_oct10.html).
The initial window is 30 days, at most five messages per cycle. Gmail receiving
headers must report unambiguous aligned DMARC and DKIM success before a body is
read. No attachments, message bodies or tracking URLs are retained or opened.

A fixed date window, pagination token, overlapping high-water mark and durable
message receipts support incremental sync and safe recovery. Requisition identity
deduplicates repeated alerts, existing jobs and applied jobs. Partial page failure
retains committed receipts and the previous watermark. Expired pagination starts
again from that watermark; repeated messages cannot create duplicate packets.
Multi-job messages use batched identity/history reads and writes so the owner
lock is not held across a separate remote query for every extracted link.

Direct Naukri links enter the existing dashboard candidate-review pipeline.
New candidates queue a deduplicated dashboard notice and the existing Telegram
outbox. Neither an authenticated email nor a URL establishes an active vacancy,
employer facts, experience requirements or application permission. These remain
explicit review blockers. The preparation policy and its saved profile/resume
versions are unchanged. There is no automatic creation of unverifiable facts.

## Supported platform boundaries

Naukri submission remains disabled: no permitted applicant submission contract,
provider-specific owner policy or independent receipt integration has been
established. Signed-in Chrome and MCP availability do not change this boundary.
The current terms page could not be retrieved during this investigation, so no
claim of newly verified terms permission is made.

The [Greenhouse Job Board API](https://docs.greenhouse.io/job-board) supports free
public GET operations, while application POST requires an employer API key.
The [Lever Postings API](https://github.com/lever/postings-api) documents public
job reads and a keyed application endpoint for employer career sites. Access to
public jobs does not supply those employer credentials or submission permission.
No such credentials or provider-specific submission policy were granted here.

Existing [Remotive](https://github.com/remotive-com/remote-jobs-api) and
[Arbeitnow](https://www.arbeitnow.com/blog/job-board-api) adapters provide free
read-only alternatives. Preserve attribution, source freshness limitations and
explicit eligibility uncertainty. Do not introduce paid routes as a fallback.

## Exact-SHA upgrade and remaining acceptance

No installed release, LaunchAgent or native-host wrapper was changed. No database
migration or connection-budget increase is required. Extension version 1.3.2
retains the existing public key and stable extension ID.

1. Review the branch diff and local validation. Record its full commit SHA in the
   private upgrade receipt. Obtain owner approval for that exact SHA before any
   production replacement or restart.
2. Stage an immutable release from the approved commit. Build the extension and
   frontend; retain separate release dependencies and environment references.
   Preserve all installed releases, data, account tokens, binding UUID, component
   LaunchAgent definitions and native wrapper as rollback material.
3. Upgrade API, execution worker, native host and frontend to the same approved
   source. The owner reloads the extension from that release through Chrome's
   protected UI. Preserve the persistent binding and existing local storage.
   Do not reconnect another profile/account or reopen unknown-outcome commands.
4. Verify startup audit, readiness recovery, exact Profile 8 routing and account
   identity. Explicitly resume only the acceptance task. Run three new bounded
   Open → Prepare cycles, including an awake locked-Mac window. A posting without
   a form must produce an accurately labeled read-only terminal result.
5. Reconcile original command IDs, tab/window/session authority, URL/revisions,
   plan records, dashboard and database; prove zero employer writes, duplicate
   commands/packets and fill grants. Repeat after an approved service restart and
   check concurrent PAUSE/STOP fences without resuming older tasks.
6. Run repeated bounded monitoring windows and preserve failures. Verify recurring
   Gmail intake and its cursor after restart. If the selected sender has no
   messages, report that source-data blocker; do not widen personal-email scope.
7. A genuine fill still needs exact field values and sources approved by the
   owner. Submission requires a separately approved supported provider policy,
   idempotency, stop controls and independent receipt verification.

Local tests use fictional unsafe-edge fixtures. Real monitoring and provider
receipts belong in the private acceptance directory, never in Git. A successful
development API probe does not establish native end-to-end installed acceptance.
