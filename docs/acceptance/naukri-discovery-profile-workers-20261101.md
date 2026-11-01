# Discovery filtering, application handoff and profile polling — 2026-11-01

**OPEN: no new independently verified application.** Existing branch
`fix/live-prepare-discovery-20261030`, [PR #48](https://github.com/karanagg166/automated-apply/pull/48),
base `main`. Exact implementation and installed API/execution/frontend:
[`653202800885f9abea0ee65f357d1e628127a2c6`](https://github.com/karanagg166/automated-apply/commit/653202800885f9abea0ee65f357d1e628127a2c6).
All times below are UTC. See the
[execution plan](../plans/2026-11-01-real-automation-execution.md) for the complete
owner-requested scope, including later per-platform and contact/draft acceptance.

## Behavior changes

Previously, a detailed job observation that passed age/applicant checks entered
MATCHED / preparation before experience, full preferences, required skills and
minimum score were checked. Discovery now runs the same complete eligibility
function before handing **ELIGIBLE / prepare** work to the independent application
worker. A failed check stays in durable discovery history as SKIPPED or NEEDS_INPUT,
with its actual reason and no application packet/action. Preparation and every
write still recheck current profile, policy, listing, identity and history.
There is no weakening of unknown-applicant, required-skill or experience checks.

The existing PostgreSQL deterministic platform/requisition identity, owner fence,
leases, replay/history protection and outbox are reused. No new database, broker,
connection limit or concurrent browser action was introduced. Discovery/browser
work is scheduled through the extension/native lane; API execution preparation
runs in its existing independent service. The browser lane remains exclusive.

Profile comparison defaults to **1,800 seconds** and exposes its interval in the
frontend. Read-only polling follows a newly confirmed profile version; automatic
summary writes remain pinned to the exact approved version. Missing supported
facts and conflicts create reference-based, deduplicated in-app notifications
linked to `/profile`, with a delivery record. Unsupported extraction is not
reported as a missing fact; the verified login/contact distinction does not
produce an email mismatch notice. Repeated identical polls do not repeat notices.

The frontend separately displays discovered jobs, eligible preparation, work in
progress, newly receipt-confirmed submissions and historical recorded applications.
Skipped/held discoveries are explicitly not submitted applications.

![Actual installed progress section; no candidate data](screenshots/naukri-worker-progress-20261101.png)

## Checks and exact candidate

| Check | Result | Evidence scope |
| --- | --- | --- |
| Queue, profile comparison, submission and questionnaire regressions | **119 PASS, 20.32 s** | Local fictional fixtures; includes discovery exclusion and notification/version cases |
| Final event addition: native ingestion, calendar precision and pre-preparation filters | **4 PASS, 43 deselected, 0.86 s** | Overlapping targeted fixtures |
| Exact candidate's own Python runtime, background queue/profile suite | **67 PASS, 9.75 s** | Overlapping fixtures; no real application |
| Frontend queue/profile preferences | **10 PASS, 2.28 s** | Fictional unit tests; includes 30-minute save and honest progress counts |
| Exact frontend candidate | **10 PASS, 1.79 s** | Same overlapping cases |
| Ruff E9/F/I, frontend typecheck, full frontend format check, diff | **PASS** | Changed source and contracts |
| OpenAPI export and generated frontend types | **PASS** | Default interval changed 3,600→1,800 seconds |
| Exact independent backend/frontend builds and pip check | **PASS** | Own runtime, dependencies and production Next build; no mutable runtime symlinks |

The first edited test run stopped on a test-only unmatched bracket; it was fixed.
A subsequent 66-pass/one-failure run found a UUID passed by the new direct-call
fixture into JSON binding data; the fixture was corrected to use the production
string representation. Neither failing test revision was installed. Final results
above passed. No hosted Actions were dispatched. No schema migration was needed.

## Actual Mac replacement and read-only provider acceptance

Queue STOPPED **50** with **491 records**. The observed **14.400 s** interval covers
the Stop request **and its subsequent queue readback**, not an isolated Stop HTTP
latency. Exact previous API/execution **1b23163** and frontend **c94f1fb** plists,
wrapper and immutable runtimes were retained in a three-service rollback inventory.
Rollback unloads replacements under a stopped queue, restores those exact plists,
verifies readiness/data/account/policy and never restores a database snapshot.

At **16:00:54**, installation passed: backend readiness **200**, frontend login
**200**, worker online, all three new PIDs present, same **491 records**, profile
**v5 / 75 skills**, approved Profile 8 account binding **1**, identical stopped
policy, credentials and protected files. Telegram **a093eab**, native **f13c956**
and same-ID extension **0cef522 / 1.3.16** were unchanged. All historical releases
and rollback files remain. This replacement required no owner Chrome operation.

At **16:01:30**, profile polling policy **20** was independently read back enabled,
**1,800 seconds**, automatic writes **false**, no approved write fields, actual
saved-PDF verification required. Queue resumed **RUNNING 51 at 16:01:50**, preserving
age **14**, applicant threshold **1,000**, score **50**, unknown applicants review,
all-company scope and SUPERVISED allowance/hourly cap **one**. Other platforms
remain disabled; Gmail sending remains disabled.

An authenticated **isolated headless browser** rendered the actual installed
frontend at **16:01:53**: correct 30-minute enabled/read-only controls, 14/1,000/50,
**zero new confirmed submissions / one previously recorded application**. Controls
and cropped progress screenshot were verified. Elapsed **23.342 s**, external
requests **zero**, writes **zero**. Authentication used the existing local signed
owner-session mechanism; a password-login journey is not claimed. No personal
Chrome tab/window, keyboard or clipboard was used.

The actual approved Naukri browser connection completed its new profile comparison
at **16:02:25**: **COMPARED**, summary **MATCHED**, saved resume **MATCHED_PDF_BYTES**,
actual Download **100,198 bytes**, canonical checksum match, no provider error.
No Save or upload was performed. Other profile fields returned **UNSUPPORTED** in
this comparison adapter. Consequently no genuine missing-field notification is
claimed from that observation; notification delivery has fixture coverage only.
The next work is actual field extraction, rather than declaring unsupported
fields absent or inventing owner facts.

At **16:02:45**, independent durable read: **491 records**, 367 SKIPPED,
123 NEEDS_INPUT, one historical recorded application, **zero new admitted Apply
actions and zero new receipts**. The Mac was UNLOCKED. Source error `global_stop`
is the retained installation fence awaiting its next cycle, not a claim of a
fresh provider failure. Current jobs still require valid facts under policy.

## Acceptance and remaining work

| Requirement | Result | Remaining proof |
| --- | --- | --- |
| Filter discovery before application preparation | **IMPLEMENTED / FIXTURE PASS** | New installed real detailed-job handoff or rejection |
| Preserve deterministic deduplication / uncertain-history fences | **PASS, existing behavior preserved** | Repeated real submissions still unaccepted |
| Configurable 30-minute bound profile inspection | **PASS, first actual sample** | Repeated scheduled sample; broader field extraction |
| Actual provider-saved resume byte verification | **PASS, actual Download** | Fresh proof again before an application |
| Deduplicated missing-fact notifications | **FIXTURE PASS / LIVE NOT TESTED** | Actual supported missing fact, owner answer, persistence |
| Honest worker/application frontend progress | **PASS, actual installed render** | Full browser/application journeys remain outstanding |
| First new application / independent receipt | **BLOCKED** | No currently admitted eligible application; pending unknown-applicant decision retained |
| Recurring AUTOMATIC / locked forms / submission restart | **NOT TESTED / NOT ACCEPTED** | First new receipt and specific real-operation evidence |
| Additional platform applications | **NOT IMPLEMENTED / NOT ACCEPTED** | Individually delivered real adapters and account acceptance |
| Apollo / SignalHire and actual Gmail drafts | **BLOCKED: API ACCESS** | Neither current runtime API key is present; no paid entitlement assumed |

The requested “Get Shit Done” plugin was searched through plugin discovery and
local skill paths; no matching installed integration was found. The repository
execution plan was created and concrete implementation/deployment performed.
Apollo/SignalHire code already exists; it is not a verified live connection.
Current official API references: [Apollo API search](https://docs.apollo.io/reference/people-api-search)
and [enrichment](https://docs.apollo.io/reference/people-enrichment). Search alone
is not evidence of a fetched email. No provider lookup or credit consumption was
performed in this milestone. Existing draft-only mail protections remain.

Reproduce local checks from the implementation SHA:

```sh
.venv/bin/python -m pytest backend/tests/test_naukri_background_queue.py backend/tests/test_naukri_profile_sync.py backend/tests/test_application_queue.py backend/tests/test_naukri_submission.py backend/tests/test_naukri_questionnaires.py -q
pnpm -C frontend test tests/application-queue.test.tsx tests/profile-company-preferences.test.tsx
pnpm -C frontend typecheck
pnpm -C frontend format:check
.venv/bin/python backend/scripts/export_openapi.py
pnpm -C frontend api:types
pnpm -C frontend build
```

Continue the real application objective, preserve unanswered decisions rather than
silently relaxing them, and expand supported profile observations. Full automation
is not complete. No merge, hosted CI, cleanup/deletion, other-platform activation,
Gmail send, historical/uncertain application replay or invented receipt occurred.

## Current portal fields, real notifications and reviewed-answer continuity

Further source and installed component updates:

| Component | Exact current implementation SHA |
| --- | --- |
| API | [`2652ff54a98f5845f15717312b211a00cb94e8c3`](https://github.com/karanagg166/automated-apply/commit/2652ff54a98f5845f15717312b211a00cb94e8c3) |
| Frontend | [`c875cbb89dc6aafc16e6ed68b46918b69f0183f2`](https://github.com/karanagg166/automated-apply/commit/c875cbb89dc6aafc16e6ed68b46918b69f0183f2) |
| Execution worker | `653202800885f9abea0ee65f357d1e628127a2c6` |
| Extension 1.3.17, same stable ID, 23 exact files | [`ee7d045d3460994de1cb0831b937a7dd411e0b39`](https://github.com/karanagg166/automated-apply/commit/ee7d045d3460994de1cb0831b937a7dd411e0b39) |
| Native host | `f13c956c3a00f8434a4152f7c8ff451cb5eaca14` |
| Telegram | `a093eabc1ca1f0989b4ff7e3f7be187f442ddb2a` |

Actual hydrated portal DOM inspected at **16:07:39** had nine professional-profile
widgets. The previous name selector did not cover this layout. The new extension
reads its actual name, unmasked phone and location labels, key-skill chips, explicit
empty Projects widget, and presence of employment/education rows. Ambiguous skill
widgets, masked phone numbers and unrecognized fields remain unknown. Career-row
presence is **PRESENT_DETAILS_UNVERIFIED**, never proof of its dates or contents.
An empty Projects widget is distinguished from an unsupported project layout.

Skill comparison ignores order, duplicate labels and capitalization without adding
technology aliases or skills. Name capitalization no longer creates a conflict.
A national phone display with matching local digits remains **unverified for its
international country code**; it is not declared a full match or a conflict.
Different local digits or explicit different international numbers still conflict.
Summary save preimages and single-use write guards are unchanged.

The direct background-tab inspection's before/after front-window snapshots differed;
all selected tabs stayed selected, but the cause of front-window changes was not
established. **Focus preservation is not claimed for that inspection.** That
navigation route was discontinued. The later installed extension maintenance
recorded identical before/after front/selected-tab IDs. No attempt was made to
restore the owner's focus, activate a tab/window, or use keyboard/clipboard.

### Actual deployments, failures and rollback

The first API/1.3.17 installation attempt stopped at readiness and restored the
exact previous API/extension under **STOPPED 52**, ready **200**. Logs established
that the full schema audit passed in approximately **11 seconds**, but the installer
counted quick connection refusals against twenty polls during imports/startup and
shut down the process at its startup-complete boundary. The installer now observes
the exact current PID's declared startup within a bounded 45-second phase, then
requires authenticated HTTP readiness. **No application audit deadline, native
timeout or connection limit increased; cold-start optimization is not claimed.**
At **16:21:22**, API/extension **ee7d045 / 1.3.17** passed readiness, fresh native
reconnect, exact 23-file/same-ID checks, **491 records**, profile **5**, approved
binding **1**, unchanged profile-poll policy and protected services/configuration.

Real comparison at **16:22:25** exposed false alerts caused by name capitalization
and international-versus-national phone formatting. Correction **2652ff5** fixed
those comparisons and superseded stale in-app notices. Resolved notices remain
in history without pretending the owner read them; a genuinely recurring gap may
become active again without repeated identical notifications on every poll.

The first API/frontend correction installer had an operator-only **KeyError**:
its two-service scope retained a reference to the execution service. Previous
API/frontend definitions were restored, the execution service was untouched, and
the complete rollback was independently verified at **16:33:58**: ready **200**,
frontend login **200**, worker online, same **491 records**, profile **5**, binding
**1**, protected files unchanged, queue **STOPPED 54**. The corrected two-service
installer passed at **16:35:27**, preserving that state, then resumed **RUNNING 55**.
Both attempt inventories and every old runtime remain retained.

The initial Current location UI addition duplicated an existing control inside
**Private application facts**, which the isolated wizard tests had mocked out.
The actual headless page caught two matching controls. Final frontend **c875cbb**
removes the redundant addition and uses the existing reviewed career-facts editor.
That editor now confirms the **exact newly saved profile version** after the owner's
explicit review, so read-only polling can follow updated facts. Confirmation
failure keeps automation unconfirmed and is not represented as a failed or
repeatable provider save. A full wizard/editor integration regression covers the
single control and version-specific confirmation. No real personal fact was
changed merely to test this owner-answer path.

Actual Stop HTTP for the final frontend-only replacement was **8.658 seconds**,
**STOPPED 56**. Its stopped preflight and after-read each retained **492 records**;
a discovery transaction committed one new record between the earlier running
snapshot and Stop. No record was discarded to force counts to agree. At
**16:43:47**, frontend **c875cbb** passed login/readiness/profile/binding/extension/
protected-service checks; **RUNNING 57 at 16:44:27**, same 14/1,000/50, all-company,
unknown-count-review and SUPERVISED one/hour-one policy. Besides the immediate
previous frontend, exact known-stable frontend **6532028** remains the rollback
target so the redundant field will not be restored on a failed replacement.

### New live observations and checks

- **16:36:48, actual portal comparison:** name and summary MATCHED; national phone,
  employment and education PRESENT_DETAILS_UNVERIFIED; skills CONFLICT; Projects
  MISSING_FROM_PLATFORM; current location MISSING_FROM_DATABASE. Actual Resume
  Download again matched canonical PDF bytes/checksum, **100,198 bytes**, no error.
  Unsupported fields were not turned into missing facts. Profile policy **22** is
  enabled every **1,800 seconds**, no automatic writes or approved write fields.
- **16:41:28, independent database read:** **three active** in-app notices, for
  skills, Projects and location; **two superseded** formatting notices; **five
  in-app delivery records**. No owner-read event or provider Save was fabricated.
- **16:46:14, actual installed frontend:** one Current location control in the
  existing editor, correct 30-minute/read-only/14–1,000–50 controls and zero new
  confirmed submissions. Two-page queue/profile check **30.758 seconds**, external
  requests **zero**, writes **zero**. This includes both page loads and is not a
  queue-endpoint latency comparison. An earlier passing observation used stale
  SHA metadata/helper selection; it was preserved, corrected to the exact installed
  c875cbb path, and rerun. The quoted result uses corrected metadata and a verified
  LaunchAgent working directory.
- **16:46:21, retained-facts diagnostic:** **466 genuine saved observations / 493
  durable records**, zero eligible by available current facts. This is a re-score,
  not 466 fresh provider visits. No unknown applicant upper bound was invented.

| Follow-up check | Result | Limits |
| --- | --- | --- |
| Profile widget comparison regressions | **23 PASS, 2.41 s** | Fictional fixtures; formatting and notice-resolution cases included |
| Exact API candidate's own runtime | **23 overlapping PASS, 2.66 s** | Own immutable environment; pip check passed |
| Extension queue guards | **24 PASS, 0.160 s** | Existing focused Node cases |
| Actual isolated Chromium with fictional provider pages | **38 PASS, 108.869 s** | Includes two new observed-widget cases; 0 live/unexpected/chooser requests, 33 fixture requests |
| Final wizard/editor, queue and preference regressions | **11 PASS, 2.25 s** | Full real component integration in fictional fixtures; duplicate-control regression |
| Exact final frontend candidate | **11 overlapping PASS, 2.04 s** | Own production build/dependencies |
| Typecheck, selected format, Ruff E9/F/I, build, diff and pip | **PASS** | No unrelated broad suite rerun; no schema migration |
| Real expanded profile inspection / PDF / in-app notices | **PASS, bounded samples** | No personal field save, questionnaire or application implied |
| Real owner answer → confirmed version → provider save | **NOT TESTED** | Missing owner facts remain unknown; provider writes remain separately supported/scoped |
| First new receipt / recurring AUTOMATIC | **BLOCKED / NOT ACCEPTED** | Zero new verified submissions; once-asked applicant-count decision remains pending |

Current relevant frontend reproduction adds the integration test:

```sh
pnpm -C frontend test tests/profile-career-facts-integration.test.tsx tests/profile-company-preferences.test.tsx tests/application-queue.test.tsx
.venv/bin/python -m pytest backend/tests/test_naukri_profile_sync.py -q
node --test extension/tests/naukri-queue.test.mjs
node extension/tests/naukri-execution.browser.mjs
```

The owner reiterated **free-only, agent-led** Apollo/SignalHire setup using verified
account facts, rather than asking them to provide API keys again. No account or
key is claimed created. Current official [Apollo API documentation](https://docs.apollo.io/reference/apollo-api)
requires a work-email-registered free account for the relevant people search/
enrichment actions; a personal Gmail address does not establish that entitlement.
[SignalHire pricing](https://www.signalhire.com/pricing) advertises a free allowance,
and its [API documentation](https://docs.signalhire.com/overview) requires an account
API key; actual account/API allowance must still be verified. No purchase, paid
upgrade, credential invention, provider restriction bypass or Gmail send is allowed.

At **16:49:31**, one retained, never-attempted job was scheduled for a fresh ordinary
listing read under the owner fence, using the **same durable work identity**. It
had no packet, form, admitted action or historical/uncertain receipt; all replay
checks remained enforced. The first operator probe failed on a helper-import
AttributeError and rolled back before changing the work; the corrected attempt
committed its journal once. No new application identity or Apply was created.
The actual provider read completed **16:49:56** and an independent observer verified
it at **16:50:45**: NEEDS_INPUT / `applicant_count_requires_review`, no lease, packet
or admitted action. Its formerly exact ten-applicant observation had become a
lower-bound-only count; the new observation was not replaced with the old ten.
Required experience remained **8–12 years**, so this job would also fail experience
even if applicant uncertainty were permitted. The count guard stopped it first.
This is actual fresh held-discovery evidence, **not live proof of the subsequent
full eligibility handoff or an application**. The observer exited normally.
