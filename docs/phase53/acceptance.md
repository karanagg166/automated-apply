# Phase 5.3 — Naukri discovery and monitored application acceptance

Base/installed release: `8c1635139a8943e9c2b72f39c4db593e1ccaa5b5`.
Chrome reuse design, old launch root cause and approval boundaries: [selected Chrome execution](chrome-profile-reuse.md).

Engineering branch: `feat/phase53-naukri-acceptance`, a linked worktree of the
primary repository. No local `phase-5-3-implementation-plan.md` was found under
the project, Desktop or Downloads. User instructions govern this bounded phase.

Decision: selected-profile routing and recovery are demonstrated on isolated
Chromium/MV3/native/API/PostgreSQL fixtures. Real owner-profile installation and
channel activation remain unapproved. The code is reviewable with genuine read-only discovery and one real
application review draft. Genuine filling, employer submission and live Telegram
delivery have **not** passed acceptance. No Phase 5.3 code is installed.

## Existing implementation versus demonstrated capability

The existing `execution/naukri.py` normalizes owner-supplied posting/alert facts;
it is not a live search adapter. `execution/store.py` supplies requisition-based
intent identity, revision/fence/lease controls, prior-application rejection and
submission denial. `/naukri` reads saved imports and execution state. Its optional
watcher processes saved records only and requires an explicitly started worker.
No Naukri polling, private API, cookie/token extraction or login automation is
implemented or enabled by this change.

The Naukri platform prepares saved packets and manual handoff. Chrome accepts
only a clean selected posting path for assistance; this URL check never proves
that an application form is present. The shared native/extension form engine and
owner Telegram correlation had extensive fictional evidence, but no genuine
Naukri retained-fill or submission evidence.

The installed account record initially contained a past signed-in observation,
not a current API account connection. A read-only transaction against the
existing approved online PostgreSQL found zero Naukri jobs and packets before
this acceptance. Account identity, credentials and portal sessions were not
copied into the application database.

## Supervised genuine discovery

The owner selected their intended Chrome profile and signed in manually.
A visible Logout control produced the shared `signed_in_indicator` result.
That is a DOM observation, not verified account identity or a Naukri API grant.
The native portal check remains a separate evidence boundary; its initial
Settings text `Active endpoint: unverified` is not a successful health receipt.

The Recommendations interface requested job preferences and exposed one
ADMINISTRATOR L3 role at Wipro. It was rejected as outside the target software
roles. Account preferences were not changed.

The owner-selected ordinary search was:

`https://www.naukri.com/backend-developer-jobs-in-india?k=backend%20developer&l=india&nignbevent_src=jobsearchDeskGNB`

One visible results page was inspected, bounded to 20 distinct requisitions.
No pagination crawler, undocumented endpoint or background search was used.
Search criteria entry is part of discovery; no application fields were touched.
Ten candidate decisions and three selected detail-page observations are preserved
in [sanitized live evidence](live-readonly-evidence.json). Account identifiers,
candidate values and private packet/approval records are excluded from Git.

| Candidate | Evidence / disposition |
| --- | --- |
| QTrino Labs — Backend Developer, Gurugram | 0–2 years, recent posting, 2025/2026 technical graduates; Node.js/Python, PostgreSQL, API security and Docker. Best manual-review candidate; posted through Naukri E-hire. One unapproved draft prepared. |
| Aimleap / Outsource Big Data — Backend Developer | Naukri aggregates a 0–4-year Java/Python/big-data description. The current similarly named official company role requires Kotlin/JVM and 4–7 years. The aggregate was not corroborated as the same current vacancy; no packet prepared. |
| Routematic — backend developer | Search advertises 0–3 years, but detail JSON-LD `validThrough` is 2026-02-10 and descriptions conflict on experience. Rejected as expired evidence despite a visible Apply control. |
| Qrestik Technologies | Displayed 1–3 years; cloud/Azure requirements need additional evidence. Not shortlisted for this junior review. |
| Mitigata Insurance | Displayed 1–2 years; older posting with Hibernate/Spring requirements not established in the approved skills. |
| Kuku Fm | Displayed 1–2 years, explicitly experienced role and older listing. Not shortlisted. |
| Talent Anywhere | Node.js/PostgreSQL/Git overlap; displayed minimum one year and currentness unverified. |
| Creative Solution — .NET / Backend Developer | Fresher range, but C#/ASP.NET Core/SQL Server are not established by approved skill evidence. Rejected on skills. |
| CGI — AI/ML Backend Developer | Agentic AI/RAG/Python overlap does not override its 4–7-year requirement. |
| Quess IT Solutions | Node.js/TypeScript/Prisma overlap does not override its 4–9-year requirement. |

The official [Outsource Big Data careers page](https://outsourcebigdata.com/career/)
and [current backend role](https://outsourcebigdata.com/job-posts/backend-developer/)
were checked separately. Similar titles do not establish requisition equivalence.
The owner clarified experience privately for this review; the saved profile was
left unchanged, so the installed matcher still correctly sees that field unset.
Projects were not converted into professional employment experience.

## Genuine packet and database evidence

One QTrino job and one review packet were created through the installed owner API
in the existing approved online PostgreSQL. The packet uses the confirmed private
resume resource, has eight local checklist fields, revision 1, no approved revision
and readiness `needs_input`. The missing notice-period question is explicitly
labelled **Owner checklist (not an observed employer form question)**.

The seven core checklist items are not asserted to be discovered Naukri fields.
The resume is selected locally; it has not been uploaded to Naukri or an employer.
Personal values and their exact provenance are in an owner-only ignored review
artifact. No profile update, provider generation or mailbox job-alert read was
performed.

Independent SQL, inside a read-only transaction, confirmed one canonical source
observation, eight persisted fields, the exact packet revision and zero Telegram
question envelopes for that packet. The packet is readable through the dashboard
API. Its extension task is `null`: a genuine Chrome application tab has not been
bound to it. No extension/database synchronization is fabricated.

## Genuine application compatibility and stop boundary

Three genuine detail pages were inspected: Aimleap, Routematic and QTrino.
Aimleap and Routematic expose Apply-on-company-site buttons without a visible
external link. QTrino exposes plain Apply. No Apply button was clicked: it could
submit immediately, and discovering a drawer does not authorize that action.
Consequently employer redirect destinations, Naukri application drawers, required
employer questions, resume selection on the site, validation and multi-step flows
remain unverified. Only global job-search inputs were visible on these pages.

No security widget was observed in those bounded page reads. This does not prove
site-verified challenge clearance or authorize a future form. Login, CAPTCHA,
access restrictions and rate limits must never be bypassed.

Before any later fill, privately show the exact employer URL, packet/profile/answer
revisions, each actual selected field, value and source, challenge evidence and
possible website-side effects. Obtain specific owner approval for those fields
and input/change/blur events. Preserve existing values, verify retained values
and stop before submission. No current observation justifies that fill request.

## Changes made after the audit

- Owner imports accept reviewed destination, observation time, active/closed/
  already-applied status and published expiry, while retaining `provider_verified=false`.
  Invalid ranges, blank identity facts and invalid observation timestamps fail validation.
  Backend posting-path checks now match the extension's clean posting boundary.
- The saved-job endpoint explains skill/role fit, missing evidence, profile version,
  vacancy currentness and rejection reasons. It performs no portal or Gmail request.
  Active owner observations age out after 24 hours. Unknown, expired and invalid
  evidence remain distinct; an Apply button never overrides expiry.
- Matching uses latest explicit imported criteria without overwriting human-edited
  Job columns. Naukri review metadata and computed expiry enter packet freshness,
  invalidating old plans/reviews when criteria or availability change.
- Worker and native preparation reject closed/expired/unavailable or prior-applied
  Naukri jobs. Requisition identity, idempotency and version/fence controls remain.
- Preparation, inspection and expiry checks no longer queue Telegram notifications.
  Expired required answers change readiness to Needs input. An authenticated explicit
  Ask action is required for a new/reconfirmation question. Question-only contexts
  support canonical Naukri postings and cannot execute a fill or submission.
- Every question send is durably marked `delivery_unknown` before dispatch. Telegram
  offers no idempotency key, so an interrupted send is not automatically repeated.
  Unknown reply IDs cannot resolve an application. Ambiguous delivery requires manual
  reconciliation; this change does not invent an unknown message ID.
- Naukri DOM inspection excludes global navigation/search controls and only considers
  explicit form/dialog scopes. Unverified custom drawers stay manual. Existing
  website-search values never count as completed application fields.
- The dashboard shows actual session-observation age, matching uncertainties and
  unverified delivery. It exposes explicit Naukri checklist Ask actions and preserves
  versioned controls. No submit route or unattended mode was added.
- Proposed extension version 1.3.1 displays its loaded version and read-only DNR
  permission status in Settings, addressing the owner's installation confusion.
  The owner loaded installed release 1.3.0; Phase 5.3 remains uninstalled. No Chrome
  permission or stable extension identity changes are introduced.

## Feasibility and platform permission matrix

| Capability | Technical evidence | Platform permission / current decision |
| --- | --- | --- |
| Official account actions | Owner manual login; visible sign-in indicator observed | Ordinary owner-operated account use; no credential/session extraction; identity/API connection unverified |
| Discovery | Owner-accessible recommendations and one genuine search page, exact links and bounded visible metadata | Official [search/recommendation guidance](https://resume.naukri.com/guides/2021/07/29/step-by-step-guide-on-how-to-find-relevant-jobs/) documents human workflows. Third-party harvesting permission is not established; no crawler/private API/polling implemented |
| Alerts / Gmail evidence | Official [job-alert feature](https://resume.naukri.com/frequently-asked-questions-faq/how-to-create-free-job-alerts/) documented; structured owner facts supported | No connected mailbox read or job-alert import authorized/performed in this phase |
| Application preparation | One genuine private packet, confirmed resume, API read and independent PostgreSQL receipt | Local review only; no employer action or resume transfer; incomplete facts remain unresolved |
| Assisted filling | Generic/native and Naukri-shaped controlled Chromium retention/recovery checks passed | Genuine Naukri form and permission not established; zero genuine fills; exact future field approval required |
| Reviewed submission | Store rejects Naukri submit modes/transitions; no submit proxy/command | Unsupported and disabled; a visible button is insufficient evidence or authorization |
| Unattended submission | No genuine permitted execution or independent employer receipt | Unsupported and disabled. Strict filters, idempotency, rate limits, reviewed answers, receipts, stop and uncertain-outcome handling would all be required before a separately approved capability |
| Naukri's own Auto Apply | Naukri [advertises Neo in Naukri360 Pro](https://www.naukri.com/naukri360/neo-auto-apply-job-agent) | Vendor-native feature only; account entitlement, owner approval and independent execution/receipts are unverified. It does not authorize this application's browser automation; nothing purchased or enabled |

Official terms retrieval was blocked for the web research client. No claim of
third-party platform permission is made from that failure or from owner consent.
The existing tab guard blocks new tab-associated requests; it does not establish
control over pre-existing streams or independent background activity. It is never
a universal network-isolation proof.

## Focused validation

[Validation receipt](validation.md) records exact commands, failures and limits.
No full backend/frontend/extension suite or hosted GitHub Actions was run.
[The screenshot](screenshots/naukri-review-fictional.png) contains fictional data.

## Remaining live acceptance and release boundary

- Finish a current Chrome → native host portal/health receipt in the selected
  profile; Settings' initial unverified text is not such a receipt.
- Review and separately approve an immutable Phase 5.3 installation before using
  the changed Naukri inspection/question boundary on a genuine form.
- Establish a legitimate accessible application form without risking a one-click
  submission, then request exact field approval. Real retained filling, validation,
  multi-step completion and browser recovery on that form remain unverified.
- A real Telegram test needs exact private question/chat approval. The prepared
  notice-period item is a local checklist question, not a discovered employer field.
  No message was queued or sent; no generic approval is inferred.
- Existing profile experience remains unset at the owner's request to leave it
  unchanged. Owner-confirmed review evidence is held privately, not silently saved.

No merge, Phase 5.3 install, service restart, new polling, employer fill/submission
or live Telegram delivery is authorized by this PR. No new migration is added.
Existing private configuration, credentials, approved resume/profile, primary
checkout and installed/rollback releases are preserved. Authorized additions are
one genuine job and its unapproved review draft. See [install/rollback](install-and-rollback.md).
