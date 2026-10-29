# Phase 5.3 recurring preparation — PARTIAL / live acceptance BLOCKED

**Owner scope decision (2026-10-30):** two Gmail accounts, Naukri alert detection
and multi-account deduplication are deferred to **Phase 5.4**. All Gmail intake
remains disabled in Phase 5.3. This supersedes the potential email activation
steps below, which describe dormant engineering only. Neither deployment flags
nor a previously saved email policy can activate this source in Phase 5.3.
See [the role-policy correction and release scope](role-policy-correction.md).

This continues Phase 5.3. It does **not** complete the owner's one-click Naukri
acceptance requirement. No genuine submission has been performed or confirmed.
The owner confirmed that no written Naukri integration permission or approved
recurring feed exists yet, and may separately authorize official job-alert emails.
No merge, installation, live channel activation, mailbox read or employer action
is included in this engineering work.

## PR #45 prerequisite

GitHub's PR metadata was checked at `2c0b84401251efb3bed948b4a8efdf81b52a451f`:
open, draft, unmerged, based on `8c16351…`. Its two findings are issue comments,
not inline review threads (the review/thread lists are empty):
[owner review](https://github.com/karanagg166/automated-apply/pull/45#issuecomment-6502652341)
and [recorded correction](https://github.com/karanagg166/automated-apply/pull/45#issuecomment-6503048056).
The [existing report](pr45-review-followup.md) individually classifies the 21
frontend failures and 11 exceptions. An exact-head rerun of just its seven affected
frontend files passed 69 checks; profile/task backend files passed 42 checks.

The same inherited extension routing remains in use: the selected authenticated
normal Chrome profile receives commands; there is no fallback to an isolated
browser. Remote Prepare uses the exact stored tab/window without focus changes.
Owner Pause/Stop, selection, session, permission, navigation and packet revisions
continue to fence commands. Disposable Chromium profiles test the implementation;
they do not prove that the owner's genuine profile is connected.

## What Start actually enables

`/naukri` now has START AUTOMATION, PAUSE AUTOMATION and STOP AUTOMATION.
The owner first saves a bounded preparation policy pinned to the confirmed
candidate profile version and unique confirmed primary resume resource/version.
Saving a changed policy stops/fences old work. Start persists RUNNING and makes a
scheduled check due; it requires the separately installed execution worker.
The dashboard reports a missing/stale worker rather than claiming execution.

The workflow checks at least 15 minutes apart, defaults to six hours, considers
at most 100 saved jobs per check with a persisted cursor, and reserves at most
1–25 new preparations per UTC day. Reservations survive retries, Stop/Start and
process restarts. Existing requisition intents are coalesced and never implicitly
resumed. The worker claims before preparing, then rechecks the saved policy,
profile, resume, vacancy, prior application history and matching evidence.

Policy role and location comparisons are exact and case-insensitive; required
skills must all be verified, the score must meet the saved threshold (80–100),
negative preference factors block, and an explicit required experience band must
fit the approved band. Uncertain match criteria block. Employer size and
unadvertised salary are informational when no corresponding restriction exists;
a salary/preference comparison that cannot be made still blocks. A posting date
is required and must be within the policy's maximum age (default 14 days).
An active owner observation expires after 24 hours. These remain owner observations,
never provider verification. Existing already-applied and unknown-submission
exclusions apply before packet creation and again during preparation.

Preparation uses the shared factual packet/provenance engine. A stale packet or
changed resume becomes NEEDS_INPUT. No factual answer is invented. Optional
`telegram_questions` requires an already configured owner/private-chat channel
and explicitly authorizes queuing exact factual questions through its existing
correlated outbox. Delivery still needs the separately approved Telegram worker.
Unknown delivery is not blindly retried. Legal/security/unsupported questions
remain manual. `/naukri status` reports the same stored state, source, heartbeat,
counts and blockers; `/naukri automation start|pause|stop` uses the same control.
No genuine Telegram message was sent during this work.

Pause/Stop and the legacy OFF setting fence execution leases and Naukri extension
plans/tasks/commands, including plans with no execution intent. Queued commands
are cancelled; leased/executing commands retain unknown outcomes. There is no
promise to undo an action already executed. Start does not resume an individually
paused application or restore an old fill authorization. Policy revisions reject
stale controls and delayed claims. Database errors use bounded backoff; heartbeats
go stale during outages. Existing three-attempt preparation recovery is retained.

`DISCOVERY`, `PREPARATION`, `FIELD_FILL`, `SUBMISSION` and `PROVIDER_CONFIRMED` are
shown separately. The only unattended action currently configurable is
PREPARATION. The employer submission cap is fixed at zero; unsupported actions,
platforms and sources are rejected by the API. No genuine Naukri confirmation
adapter exists, so the confirmed submission count is zero. Mock-employer receipts,
filled forms and owner reports cannot increment it. Unknown and owner-reported
outcomes remain separate.

## Discovery audit and official email source

| Existing method | What it actually does | Recurring permission |
| --- | --- | --- |
| URL/structured alert import | Saves owner-supplied facts, normalizes exact requisition and deduplicates | Does not poll the site |
| Find saved jobs / WATCH_AND_NOTIFY | Rescans saved records, optionally deduplicates an in-app notice | Cannot discover a new vacancy by itself |
| Selected Chrome profile | Owner-reviewed local inspection and exact field assistance | No unattended Naukri permission established |
| Prior genuine read-only review | Historical observations in [acceptance](acceptance.md) | Not a standing discovery/submission grant |
| Existing Gmail read-only integration | Separately consented account, sender/label selection, bounded GETs | Disabled until its existing approval/configuration gates pass |
| New job-alert adapter | Scheduled reads from one pinned, sender-limited Gmail policy; extracts exact Naukri requisition links | Separate email activation required; no Naukri page/API fetch |

Naukri's official [FAQ](https://resume.naukri.com/frequently-asked-questions-faq/how-to-create-free-job-alerts/)
and [setup guide](https://resume.naukri.com/guides/2021/07/29/step-by-step-guide-on-setting-up-job-alerts/)
describe preference-based email alerts. They do not grant third-party browser
or submission permission. The terms page was denied to the research browser;
no alternate private endpoint or access bypass was attempted. Permission for
unattended Naukri site access/submission remains unverified and blocks activation.

For a potential authorized email source, the owner configures official alerts in
their own account, then separately approves one Gmail read-only account and body
access. Use the existing account UI to approve an exact `@naukri.com` sender
allowlist, one page per batch, no historical/all-folder scan, and the purpose.
Pin that read policy version in the preparation policy and choose `gmail_job_alerts`.
This does not authorize reading email by itself. Deployment additionally requires
`NAUKRI_ALERT_EMAILS_ENABLED=true`, `GMAIL_READ_SYNC_ENABLED=true` and
`GMAIL_READ_BODY_REVIEWED=true`, after the existing Gmail schema/security and owner
approval process. This work changes no live setting, OAuth scope or schema.

The adapter reuses the existing GET-only Gmail reader (at most 25 selected
messages per batch), its persisted pagination/checkpoints and account revocation
checks. It adds a separate expiring source lease and checks automation authority
before subsequent requests. No DB lock is held across HTTP. Stop prevents late
results from publishing candidates. Only evidence produced under the pinned read
policy and body selection is consumed; old broader mailbox evidence is excluded.
No links, trackers, redirects or attachments in an alert are fetched.

Emails yield **candidate links requiring input**, not confirmed active vacancies.
Sender allowlisting is not sender-authenticity proof. Exact employer/title,
requirements, posting freshness and availability cannot be reliably reconstructed
from a URL slug. The adapter does not guess. The dashboard offers Review alert
facts, binds that import to the message/requisition and then lets the bounded
scheduler evaluate the reviewed posting. Candidate references expire with the
originating email retention window; dedup tombstones retain no message bodies.
A representative genuine alert and separately approved reads are still needed to
validate real templates and determine whether richer extraction is justified.

Thus automatic email ingestion is engineered behind disabled gates; fully
unattended discovery-to-preparation remains limited by missing reviewed facts.
There is no scraper, private Naukri API, anti-bot workaround, cookie export,
CAPTCHA bypass or direct employer submission implementation.

## Locked but awake Mac and release boundary

The normal selected Chrome profile remains the execution target. Backend
scheduling, Gmail GETs, persistence and native service-worker polling require no
foreground UI. Bound Prepare uses `chrome.scripting.executeScript` on the saved
background tab. Existing field filling still requires exact review and active-tab
safety checks; no locked-screen compatibility has been established for genuine
Naukri DOM or for filling. Browser existence/heartbeat is not DOM execution proof.

The installer now supports an optional `execution` launch agent with private logs,
restart-on-failure and throttling. It installs nothing automatically. After exact
SHA approval, review the plan from the approved release and private env:

```sh
backend/venv/bin/python backend/scripts/phase1/install_local.py launchd-plan \
  --service execution --env-file /PRIVATE/OWNER_APPROVED.env
```

Keep Chrome and the logged-in macOS user session running, the Mac awake and on
power. Screen locking is distinct from sleep, logout and shutdown. No unlocking,
TCC/Accessibility permission change, power-setting change or profile fallback is
implemented. Actual behavior must be measured on the owner's locked session.

An owner-invoked monitor is available after approval:

```sh
backend/venv/bin/python -m backend.scripts.monitor_naukri_acceptance \
  --env-file /PRIVATE/OWNER_APPROVED.env \
  --output /PRIVATE/locked-session.private.jsonl \
  --duration-seconds 300 --interval-seconds 30
```

It samples available macOS lock telemetry (UNKNOWN if absent/ambiguous), the owner
API, independently read PostgreSQL state/revision, and persisted worker/extension
heartbeats. It creates a new mode-0600 report, never locks/unlocks, and records
failures rather than a PASS. It does not prove DOM compatibility, field retention,
Telegram delivery or genuine submission. During supervised acceptance, record
normal lock/unlock times separately, schedule one permitted source check, compare
PostgreSQL/dashboard/Telegram, then Stop and verify no new actions. Use fresh
explicit approvals for exact fields and for any independently permitted
submission capability. A short interval proves only that interval; sustained
monitoring/restart/outage evidence is separately required.

Keep the [existing release/rollback procedure](install-and-rollback.md), keys,
private configuration, native host definitions and previous release. No existing
LaunchAgent or native installation is replaced by this change.

## Focused validation and remaining acceptance

Validation receipts are in [recurring validation](recurring-validation.md).
Tests use fictional candidate/jobs/mail and isolated PostgreSQL/Chromium. They
must not be reported as genuine applications, genuine job-alert discovery or
locked-screen acceptance. No full backend/frontend suite or hosted Action ran.

Remaining owner approvals: final exact SHA merge; installation and execution
launch agent; real profile connection and command-channel activation; one selected
Gmail account/body/sender policy and email polling activation; Telegram live test;
normal-lock supervised monitoring; any exact genuine field action. Naukri site
submission additionally needs verified platform permission, a supported technical
confirmation contract and separate owner scope. Those prerequisites do not exist.

Phase 5.3 status remains **PARTIAL / BLOCKED**, with **zero genuine submissions**.
