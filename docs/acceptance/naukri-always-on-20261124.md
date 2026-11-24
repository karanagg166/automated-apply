# Naukri availability and restart recovery

## Why the live worker is blocked

The exact local release passed managed startup under launchd. The approved
Brave profile initially had no browser window or Naukri tab. Its process and
extension can be alive while the native broker correctly reports offline. The
production guard denies background window creation because the previous live attempt
changed macOS window focus. A fresh portal account and résumé check still
requires a visible dedicated window. [Live window evidence](brave-window-focus-and-login-20261115.md)

The guarded dedicated launcher verified zero tabs, then opened one ordinary
window with the queue stopped. Brave restored an older profile tab alongside
the new one. The new duplicate was closed, leaving the older Naukri profile
inactive and a neutral tab active. The live readiness read confirmed that
the selected Brave connector reconnected and the approved account binding
persisted. A fresh read verified the account and canonical PDF in the retained
tab. The production release remains `1afc1b4cfd64c249a048a666805832f8ffb9bdb5`.

## Live supervised run

One fresh full-stack listing was selected from a date-sorted Naukri search.
The queue independently verified eligibility and prepared the packet. An
initial browser inspection lease expired and recovered. Subsequent leases
reached `READY_TO_APPLY`, then expired before an Apply admission. Sanitized
extension traces captured `backend_not_ready` during polling and inspection.
The exact live HTTP error and SQLSTATE were unavailable. An earlier live
trace tied the same bridge symptom to owner-row contention. See the
[earlier lock investigation](naukri-policy-rechecks-20261101.md).

The bounded run ended at STOP revision 170 and removed the one-listing scope.
All three historical reservations and quarantines remain. The fourth admission
is available. There were zero new admissions, zero live worker receipts, and
no active leases. Brave remains connected with browser commands disabled.

Availability is also a machine constraint. The Mac entered idle sleep while on
AC at 20:41:31 IST and woke at 20:42:58 IST. Its AC idle system sleep timer was
one minute at the readback. Per-user LaunchAgents require a logged-in session.
Browser alarms do not wake sleeping hardware. The prior locked startup failure
also showed why the installed Desktop paths require macOS file access
consent. [Apple launchd guide](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html) ·
[Apple sleep settings](https://support.apple.com/en-us/guide/mac-help/mchle41a6ccd/mac) ·
[Apple file access controls](https://support.apple.com/guide/mac-help/control-access-to-files-and-folders-on-mac-mchld5a35146/mac) ·
[Chrome alarms](https://developer.chrome.com/docs/extensions/reference/api/alarms#device-sleep)

## Reliability changes

The existing heartbeat used a timed promise around `sendNativeMessage()`.
When macOS stalled native startup, the JavaScript timer returned an error but
left the browser channel pending. More than 400 helpers were observed under
the dedicated Brave process during the incident. A sampled helper was waiting
in the dynamic loader at an open operation while macOS logged Desktop-folder
access checks. The heartbeat now opens a port for one request and closes it on
reply or timeout. A closed channel fails the heartbeat. Response validation
still requires correlation and still rejects submission claims. The readiness
tool now distinguishes a fresh native heartbeat without a window from a stale
or disconnected bridge. [Chrome native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging) ·
[Chromium host lifecycle](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/chrome/browser/extensions/api/messaging/native_message_process_host.cc)

A disposable PostgreSQL test reproduced an HTTP 503 when a separate
transaction held the owner row. The original response omitted the rollback
header that enables the native host's bounded retry. The updated handler
marks only Naukri poll lock or serialization failures before broker dispatch,
and only after rollback succeeds. Lost or ambiguous commits and failed
rollbacks keep their existing handling. A successful repeat can reserve an
inspection lease without reserving an Apply.

The isolated Brave and PostgreSQL fixture now checks recovery of the same
binding with a new browser session after restart. The fixture uses its own
profile, a fictional portal, and the real native bridge with the queue stopped.
It supplies no evidence about live Naukri eligibility, locked desktops, or
production submission.

| Check | Outcome |
| --- | --- |
| Browser extension unit suite | 410 passed at heartbeat commit `09c51bdc8d80370d647082e41c54ae3a8968e8c3`, including four native heartbeat cases. |
| Rust browser readiness unit tests | Four passed at the heartbeat commit. |
| Isolated Brave/PostgreSQL integration | Both selected tests passed at the heartbeat commit. The native restart recovered the binding, and the supervised exception remained scoped to one listing. |
| Native poll rollback regression | The original response failed the rollback header assertion. After the fix, five PostgreSQL regression tests and 16 native transport tests passed at `98d5438bff23836dbc97b6978c1f19301aa347cf`. The unconfirmed commit test received no retry header. |
| Live installation of both changes | Pending the full combined acceptance and exact-release installation. |
| Recurring live Naukri submission | Pending a strict worker receipt and verified provider permission. |

## Route to continuous operation

1. Run discovery, ranking, and packet preparation independently of browser
   windows. For an awake overnight test on the current Mac, keep it powered,
   awake, and logged in, then measure recovery after network loss, browser
   restart, screen lock, and sleep. A full 24-hour observation is still
   required by the [saved delivery plan](../plans/completion-execution-20261116.md).
2. Finish the one authorized Naukri attempt on the dedicated visible profile
   with a new account, PDF, and listing readback. Verify the strict worker
   receipt and preserve the lifetime and hourly limits and earlier quarantines.
3. Treat recurring Naukri submission as a distinct provider gate. Naukri's paid
   first-party NEO product offers optional auto-apply. Its public material
   does not establish the project's canonical PDF, quotas, quarantine,
   or receipt guarantees. The exact current Naukri terms page could not be
   fetched during this check. No supported third-party applicant submission
   route or applicable platform permission was verified. The prior owner
   decision on provider outreach remains in effect. [Naukri NEO](https://www.naukri.com/naukri360/neo-auto-apply-job-agent) ·
   [Info Edge investor disclosure](https://nsearchives.nseindia.com/corporate/NAUKRI2_28102026120841_Outcome_of_Board_Meeting_Results.pdf) ·
   [Naukri permission record](naukri-unattended-plan-and-permission-20261031.md)
4. Keep the application worker's write capability per provider. Greenhouse and
   Lever expose public posting reads, while their application submission APIs
   require authorized employer credentials. Use the ordinary application
   handoff for postings where the project has no authorized submission
   channel. [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html#submit-an-application) ·
   [Lever Postings API](https://github.com/lever/postings-api#apply-to-a-job-posting)

The laptop power settings were unchanged. The bounded supervised run left the
queue stopped again, and recurring submission remains disabled.
