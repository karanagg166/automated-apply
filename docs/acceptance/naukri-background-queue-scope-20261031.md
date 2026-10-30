# Naukri background queue: owner scope update and implementation checklist

This is the current working scope, not production acceptance.

The owner explicitly removed the previous requirement to obtain platform approval
before building recurring ordinary browser UI automation. No provider outreach is
requested or planned. This does not establish Naukri permission or a legal finding.
CAPTCHA, rate limits and access controls remain hard boundaries. Exact-SHA owner
review before replacing production, existing database role limit five and privacy
rules remain in force.

The target is background discovery -> durable message queue -> application worker,
controlled by the dashboard. Use the existing PostgreSQL/private preference store
for a transactional queue/outbox with unique identities, leases and acknowledgments;
no Kafka daemon, paid cloud broker, extra pool or new repository. Naukri is first;
shared policy/ledger fields support future adapters, which are not implemented now.

Owner settings: global daily cap80, per-platform custom up to100 initially;
initial genuine validation uses a smaller supervised cap. Default maximum posting
age2days, configurable. Global/custom applicant threshold (10,000 example: skip
at or above threshold), with an explicit unknown-count policy. Global confirmed
profile job preferences or platform-specific matching overrides. Personal/CTC facts
remain in confirmed profile records and must never be inferred from filter ranges.
Dashboard Start/Pause/Stop, preferences/factual questions and filterable
queued/processing/needs-input/submitted/skipped/failed/unknown history are required.

Strict background behavior: inactive owned tabs only, no window focus, no owner-tab
typing, no file chooser, no macOS permission or sleep-setting changes. Owner use of
an automation tab pauses that operation. Mac must be awake, logged in, connected,
with Profile8 authenticated. Polling intervals are visible/configurable; discovery
is not guaranteed instantaneous. Existing approved Gmail sender/body/account scope
is unchanged.

## Current implementation work

- Implemented in development: queue policy/contracts, owner API, durable unique
  messages/claims/admission budgets, lease-expiry unknown fencing, historical
  receipt indexing without provenance changes, dashboard limits/overrides/filters.
- Canonical PDF preflight is integrated into the preparation worker (8df57ce).
- An isolated chooser-free browser probe passed26 cases (d7223c9); it is not a live
  upload adapter and is excluded from the extension build.
- Implemented in development: authenticated native read mailbox, inactive owned-tab
  extension consumer, normal search/job DOM observation, bounded approved-source
  producers/cursors, actual matching/eligibility and packet/PDF preparation.
- Submission/answer/upload UI mutations, provider-saved CV verification, persistent
  new receipt/notification loop and installed/locked acceptance remain pending.
  The native consumer explicitly refuses Apply/answer/upload operations even if a
  dashboard policy has AUTOMATIC selected.
- No new genuine application, production replacement or runtime permissions change
  has occurred. The preserved QTrino receipt must never be replayed.

## Next implementation sequence

1. Completed for read-only work: native queue operations and extension consumer sharing the existing
   authenticated fixed-profile transport. Native frames remain bounded; PDF transfer
   must be chunked if needed (existing limit262144bytes). All page work must retain
   profile/window/tab/session/document binding and cancellation fencing.
2. Implemented candidate: read-only normal UI search/job extraction. Preserve actual hiring company
   separately from posting recruiter; no slug-derived requirements or invented
   posting dates/applicant counts. Apply age/applicant/preferences/verified-profile
   matching, persist source evidence, prepare packet and current canonical PDF.
3. Before Direct Apply, verify the Naukri-saved resume against the canonical bytes:
   Apply can submit immediately. Use the profile's ordinary UI-provided download
   link; never synthesize a private upload POST. If it cannot be verified or safely
   updated without a chooser, leave the job waiting for owner input. Each potentially
   submitting Apply/answer/upload requires a committed unique admission and fresh
   provider-status check. Never automatically repeat an uncertain action.
4. Map actual questionnaires to current verified facts/approved answers. Unknown
   facts create correlated dashboard questions and pause only that application.
   Updates require fresh packet/UI inspection; a prior Apply must not be repeated.
5. Reconcile using exact persistent Naukri Application Status after normal reload,
   record recurring-worker versus supervised-UI provenance distinctly, update job
   history and transactional notifications. Generic success/HTTP200 is not a receipt.
6. Build/test one consolidated candidate, prepare exact-SHA release/rollback review,
   then obtain installation approval. Standard Profile8 Load unpacked/Reload and
   Naukri-origin permission may need one-time owner interaction. No protected Chrome
   preferences, debugger workaround or foreground automation fallback.
7. Run bounded genuine validation, awake/locked evidence, then extended observation.
   Multiple distinct installed-worker submissions are required for full acceptance.

Earlier read-only inspection confirmed that the existing selected native window maps to
Chrome's AppleScript window and currently contains the normal Naukri history page
`/myapply/historypage`. No active tab changed and no job action occurred. Ordinary
AppleScript tab creation has not been established as a background-safe substitute
for this session. Use the extension's explicit
`chrome.tabs.create({active:false})` path for owned worker tabs.
