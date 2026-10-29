# Phase 5.2 — Chrome application assistant acceptance

Base release: `0384fb403618c396fa60c7fb79a6b4ecebafa925`.
Review branch: `feat/phase52-extension-hardening`.

The new release is prepared for review; it has not replaced the installed release.
The primary checkout and private runtime configuration are preserved. No new
platform integration, hosted Actions run, genuine application fill, employer
submission, or real Telegram message was performed.

## What changed and why

The original popup lost its executable context when closed, had no durable tab
ownership, refused framework-controlled inputs, and rendered the workflow as a
single preparation/fill sequence. Native plans and owner-authenticated Telegram
questions already provided useful approval and freshness boundaries.

The assistant now coordinates the MV3 worker, existing native host, existing
PostgreSQL-backed repository contracts, and dashboard around one packet task.
It records packet/profile/answer revisions, Chrome session/tab identity, page
step, challenge state, authorization identity, and bounded fill receipts in
existing private `OwnerPreference`/`AgentOperation` storage. No migration is added.
An owner-row lock serializes job/tab ownership and task version changes.

The popup separates destination review, Open Application, Inspect, Prepare
Answers, Review Answers, Ask Me on Telegram, Fill Approved Fields, Pause, Resume,
Cancel and Open Dashboard. Ready fields have individual selection controls.
Reviewing the preview grants no browser-write authorization until Fill is clicked.

Opening a packet first displays its exact destination. A separate click invokes
Chrome's permission prompt for `https://<chosen-origin>/*`. The manifest declares
optional HTTPS origins; it grants no host access by default and adds no `tabs`,
cookies, debugger, credential, content-script or external messaging permission.
The separately owner-approved `declarativeNetRequest` permission is
reviewed at installation because Chrome forbids this API in optional_permissions. The guard activates only after the separate explicit Fill action. It supplies
two session rules restricted to the exact application tab: all new tab-associated
requests and top-frame navigation are blocked without inspecting their content.
Toolbar `activeTab` remains usable for explicit inspection of the selected page.
Only the exact extension popup can issue application assistant messages.

Worker startup restores identifiers and pauses pending tasks; it restores no
executable authorization. Browser restart changes the session identity and
clears old numeric tab bindings. Closed tabs, refresh, navigation, active-tab
changes, cancellation and global stop invalidate prepared execution. A cancelled
or failed partial fill can still save its audit receipt without reviving the task.
During eventful filling, a bounded status poll observes dashboard pause/cancel;
local Pause/Cancel also interrupts the isolated DOM loop before another field.
Values already delivered to the website cannot be undone by cancellation.
Pending DOM fills are interrupted by document ID when a worker restarts. A lost
FILLING operation receives an explicitly unknown, unverified audit outcome;
recovery never invents a completed-field count.

The network guard remains active after fill, pause, cancel and worker suspension.
A separate Return browser control action pauses execution and restores website
networking for owner-operated use. The popup warns that page-scheduled requests
may then resume. Local takeover can restore networking when backend status is
unavailable; synchronization remains explicitly pending in that case. A browser
restart naturally clears Chrome session rules and invalidates old tab identity.

The guard covers new requests associated with that tab. It does not establish
control over pre-existing streams or independent background execution. Eventful
filling on service-worker-controlled pages is read-only; integrations using
unverifiable background channels remain unsupported. This is not a universal
proof about arbitrary website code.

## Actual form coverage

| Control or behavior                                  | Demonstrated support                                                                           | Limits                                                                                        |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| Full name, email, phone, professional links          | Grounded proposals from approved profile; native control filling                               | First/middle/last require separately approved facts, never an inferred split                  |
| Native text and textarea                             | Optional native setter plus input/change/blur, delayed value verification                      | Event-free assignment is explicitly unverified website retention                              |
| React controlled text/textarea/select/checkbox/radio | Real installed React in an isolated Chromium world; actual React state checked                 | Vue/Angular use standard events but are not separately demonstrated                           |
| Native select                                        | Exact unique displayed option; code/option snapshot binding                                    | Disabled, ambiguous or changed options remain manual                                          |
| Native datalist                                      | Exact reviewed option and retained input                                                       | No free invention of a choice                                                                 |
| Accessible combobox                                  | Already-open, uniquely owned, static DIV/SPAN/LI options; exact retained label                 | Closed, fetched, detached, transformed or ambiguous choices remain manual                     |
| Radio/checkbox                                       | Exact grounded group choice; controlled fixtures verified                                      | Consent/legal declarations and self-identification remain manual                              |
| Date/month                                           | ISO values, constraints and delayed checks                                                     | Custom calendars and ambiguous locale dates remain manual                                     |
| Employment/education entries                         | Distinct sections, step and stable entry/control identity; exact owner answers                 | Anonymous repeated histories are manual; aggregate experience never supplies individual dates |
| Conditional fields and multi-step forms              | DOM change stops filling; fresh snapshot/review per step; controlled two-step journey verified | Save/continue is owner-operated; URL-changing destinations remain manual                      |
| Existing values and owner edits                      | Preserved, including values entered after preparation                                          | Existing values are never returned in proposals                                               |
| Validation/reset/partial fill                        | Failed retention and validation errors receive explicit statuses; partial receipts retained    | A delayed readback is a bounded observation, not a permanent guarantee                        |
| Resume attachment                                    | Confirmed canonical PDF reference and manual upload guidance                                   | Automatic extension file upload and genuine failed-upload recovery are not implemented        |
| Submission                                           | Extension/native commands cannot submit                                                        | No genuine employer submission capability is enabled                                          |

SHA-256 semantic field identity incorporates origin/path, page step, semantic
labels, accessible/group metadata, section/entry context and stable control
identity. Ephemeral `fN` IDs only address the current reviewed snapshot.
Previews are bounded to 24 unanswered fields. Labels reaching the 160-character
inspection limit remain manual and cannot queue an inexact Telegram question.
Repeated anonymous employment sections stay manual even when ordinal keys differ;
stable unique section IDs preserve identity when sections reorder.

## Security challenges

The explicit states are `NONE`, `WIDGET_PRESENT_UNVERIFIED`,
`CHALLENGE_BLOCKING`, `MANUALLY_RESOLVED_AND_SITE_VERIFIED`, and `UNKNOWN`.
An observed widget or blocking challenge permits ordinary read-only proposals
where inspection is otherwise allowed. Automated writes stop. No CAPTCHA tokens,
responses or completion events are read, changed, forged or reused.

Disappearance alone changes document-local state to UNKNOWN. A durable task
also remembers a prior observed challenge across refresh/new document IDs;
a later signal-free document cannot clear it. No current generic adapter emits
`MANUALLY_RESOLVED_AND_SITE_VERIFIED`. Consequently these challenged live forms
remain manual. A future verified first-party adapter must still require fresh
inspection, packet review and authorization after manual completion.

## Genuine public-site observations

[Machine-readable observations](live-inspection.json) record timestamps, HTTP
status, exact destination, public field metadata, unsupported reasons and state.
The harness uses fresh isolated Chromium contexts without personal profiles,
credentials, candidate values, clicks, filling, uploads or submission.

| Public application                                                                                                   | HTTP | Ordinary fields identified | Manual diagnostics | Result                                          |
| -------------------------------------------------------------------------------------------------------------------- | ---- | -------------------------: | -----------------: | ----------------------------------------------- |
| [Razorpay AI Builder / Greenhouse](https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited/jobs/4744950005)  | 200  |                         12 |                 10 | Widget unverified; read-only                    |
| [Cloudflare AI Security Research / Greenhouse](https://job-boards.greenhouse.io/cloudflare/jobs/8097321)             | 200  |                         11 |                  8 | Widget unverified; read-only                    |
| [Veeva Associate Software Engineer / Lever](https://jobs.lever.co/veeva/52ba79af-1086-457d-b5d2-8e184f111ffd/apply)  | 200  |                         22 |                 10 | Widget unverified; read-only                    |
| [Hevo Data SDE I / Lever](https://jobs.lever.co/hevodata/6cbbe304-e065-4711-bf3e-756795d2bc2a/apply)                 | 200  |                         10 |                  1 | Widget unverified; read-only                    |
| [Sarvam Platform Engineer / Ashby](https://jobs.ashbyhq.com/sarvam/fcb15601-6440-41f7-aa79-b9992057a4b2/application) | 200  |                          5 |                  0 | Widget unverified; read-only                    |
| Old Veeva Software Engineer URL recorded in JSON                                                                     | 404  |                          0 |                  0 | Closed/unavailable posting; no success inferred |

The owner reviewed the exact Hevo destination and four profile-derived proposed
values privately, and explicitly requested that it remain read-only. Personal
values and private approval evidence are excluded from this report and Git.
The existing approved profile and confirmed resume were verified through the
installed API and a read-only transaction against its existing approved online
database. No candidate detail was invented or uploaded.

No genuine-site retained fill or genuine multi-step completion has been
established. The controlled fixture evidence below is kept distinct from live
inspection. The Razorpay challenge was not assumed to be cleared.

## Database, Telegram and dashboard integration

See [backend/native contract](backend-contract.md) and
[dashboard contract and screenshots](frontend-contract.md).
Native and dashboard actions share versioned task storage. The gateway adds
only three fixed owner-authenticated/CSRF-protected task routes. The dashboard
polls the exact packet identity, distinguishes existing values from verified
assistant values, exposes pause/resume/cancel, and shows actual next action.
Manual control reasons are bounded snapshot metadata persisted without values.

Ask queues existing owner-only correlated Telegram prompts. Only a reply to the
specific prompt can resolve it; standalone messages cannot choose a waiting
application. Type, expiry and packet context are checked; an answer revision
updates its task while retaining tab/step, invalidates old plans and requires
review. Multiple questions/applications remain separate. Interrupted sends use
`delivery_unknown` and do not blindly duplicate a prompt after restart.

Local actual SQL tests use fictional SQLite fixtures for persistence and
transitions. Four additional focused scenarios exercised PostgreSQL 17 row-lock
concurrency in a fresh disposable ORM fixture database: duplicate task identity,
version updates, authorization consumption and exclusive tab ownership. Each
race had one identity or one winner as appropriate. The existing cached
`postgres:17-alpine` image was used with `--pull=never`, and the container was
removed afterward. This does not claim a new production migration or full
catalog verification. Real bot delivery and deployment of these new contracts
await the owner's installation approval. Existing private runtime is unchanged.

## Capability modes and future eligibility

| Mode                | Current capability                                                                                  |
| ------------------- | --------------------------------------------------------------------------------------------------- |
| PREVIEW_ONLY        | Read-only proposals; no authorization or employer writes                                            |
| ASSISTED_FILL       | Explicit selected fields in a reviewed packet/tab/step; per-origin grant and retained-value receipt |
| REVIEWED_SUBMISSION | Disabled for all genuine sources in this extension                                                  |
| UNATTENDED_APPROVED | Disabled by default and not implemented for genuine sources                                         |

Future unattended eligibility requires an explicitly reviewed site adapter,
per-origin approval, job filters/match threshold, verified current answers,
job/packet deduplication, durable execution/submission receipts, bounded retries
that reconcile uncertain outcomes, and the global stop. Challenge-required and
submission-unknown tasks must never be retried into submission. Existing
fixture-only submission machinery remains separate and is not an authorization
for any employer destination.

## Targeted validation

Final counts and commands are in [validation receipt](validation.md). No full
backend or frontend suite was run and no hosted GitHub Action was dispatched.
Screenshots contain fictional data only:

- [Popup](screenshots/extension-popup-fictional.png)
- [Dashboard challenge](screenshots/extension-dashboard-challenge-fictional.png)
- [Dashboard stale task](screenshots/extension-dashboard-stale-fictional.png)

The focused native browser test uses a real MV3 worker, real Python native host,
real isolated Chromium DOM, and a fictional HTTP backend. Database contracts are
checked separately. Its test extension copy grants only a fictional intercepted
ATS origin; DNS to that origin is blocked and all fixture interactions are local.
The production manifest and installed Chrome profiles are not changed by it.

## MV3 implementation references

The permission and recovery choices follow Chrome's official
[Tabs API](https://developer.chrome.com/docs/extensions/reference/api/tabs),
[Permissions API](https://developer.chrome.com/docs/extensions/reference/api/permissions),
[Storage API](https://developer.chrome.com/docs/extensions/reference/api/storage),
and [Declarative Net Request API](https://developer.chrome.com/docs/extensions/reference/api/declarativeNetRequest).
Identifiers/status persist in trusted local storage; a browser-session UUID stays
in trusted session storage. Full candidate answer previews are session-only.
