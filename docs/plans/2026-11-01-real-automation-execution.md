# Real application automation execution — 2026-11-01

Owner-requested continuation of PR #48 on the existing repository and PostgreSQL
architecture. This is an execution backlog, not a completion or live submission
claim. It supersedes obsolete scope and deployment assumptions in earlier plans.

## Required behavior

Discovery runs without an open dashboard. It collects actual listing details,
checks current profile and platform filters, and deduplicates by platform and
provider requisition before handing eligible work to application preparation.
Discovery observations, exclusions and missing evidence remain durable history;
they must not be presented as submitted applications. Repeated searches do not
create repeated application intents.

Application processing consumes eligible work independently of discovery timing,
rechecks facts at preparation and every write, fills supported forms, answers from
verified facts and approved answers, selects the verified PDF, submits once and
independently verifies the provider receipt. Lost or uncertain submissions are
reconciled without replaying Apply. Browser operations share the existing exclusive
inactive-tab lane; independent workers do not justify concurrent unsafe browser
actions, new brokers or higher database connection limits.

Every 30 minutes, compare supported portal profile facts with the confirmed local
profile. Create deduplicated dashboard notifications for missing facts or genuine
conflicts. Link the owner to the exact profile fields; save answers with provenance
and version checks, apply only supported verified updates and independently check
provider persistence. Platform login/contact differences remain valid after the
approved binding. Unsupported extraction must remain unknown, not a missing fact.

Initial scope is Naukri, followed by individually delivered Instahyre, Wellfound,
Y Combinator Work at a Startup and Internshala. Preserve separate OFF / REVIEW /
AUTOMATIC policies and per-platform readiness. Authorized account setup uses only
verified facts; OAuth, OTP, CAPTCHA or other unavoidable owner actions are surfaced
once. Never bypass provider restrictions or silently activate an adapter stub.

Use the existing Apollo/SignalHire adapters for professional contact evidence and
Gmail drafts. Respect actual account access and credits. Gmail sending remains
disabled. No paid plan purchase is authorized. Current runtime has neither
provider API key and both providers are disabled; live enrichment cannot be
represented as verified until account access is supplied and checked.
The owner subsequently requested agent-led free account setup using verified email,
without asking for API keys again. Investigate supported free registration and
actual entitlement; request only an unavoidable owner authentication action.
Do not fabricate a work email or assume free web credits include API access.
Public entitlement check on November2: [Apollo's developer documentation](https://docs.apollo.io/reference/apollo-api)
requires a work-email registration for certain free search/enrichment endpoints.
[SignalHire's pricing page](https://www.signalhire.com/pricing) advertises five
trial contacts and additional extension credits; that alone does not verify this
account's API entitlement. No account authentication, API lookup, credits or
draft has been accepted from those public pages. Free-only setup remains pending
after the Naukri first-submission priority; do not ask for keys again.

## Ordered work and acceptance

| ID | Concrete work | Acceptance required | Current state |
| --- | --- | --- | --- |
| A1 | Run complete eligibility checks in discovery before scheduling preparation | Real rejected observations remain history; no preparation packet/action for them; dedup/replay protections retained | Implemented and installed; real exclusions and positive eligible handoff through one genuine Apply verified; receipt remains absent |
| A2 | Enable 1,800-second profile comparisons and deduplicated missing-fact notices | Actual bound portal comparison, notification, owner answer/version save and supported provider persistence | Installed30-minute comparisons/PDF checks and deduplicated notices;31 provider skills independently saved/verified; remaining facts and broader supported updates pending |
| A3 | Finish first new supported Naukri application | Real fresh identity/PDF/job/history checks; actual fill/submit; independent persistent receipt; dashboard/Telegram outcome | One genuine Apply/questionnaire; original tab lost, history-only quarantine; zero new verified receipts |
| A4 | Bounded Naukri recurring AUTOMATIC | First receipt plus critical checks; repeated real submissions within quotas, no duplicates; restart and locked-operation evidence | First-receipt server guard installed; recurring AUTO still not enabled or accepted |
| A5 | Separate discovery/application visibility and controls | Dashboard distinguishes observed/held jobs from eligible application work and verified submissions; workers make progress independently | Installed separate observed/held/eligible/in-progress/new receipt/historical counts; live dashboard verified |
| B1 | Instahyre adapter and account setup | Actual discovery/form/receipt/recurring acceptance under its own policy | Not accepted |
| B2 | Wellfound adapter and account setup | Actual discovery/form/receipt/recurring acceptance under its own policy | Not accepted |
| B3 | Y Combinator Work at a Startup adapter/account setup | Actual discovery/form/receipt/recurring acceptance under its own policy | Not accepted |
| B4 | Internshala adapter and account setup | Actual discovery/form/receipt/recurring acceptance under its own policy | Not accepted |
| C1 | Connect Apollo and SignalHire to existing contact/draft workflow | Actual authentication, bounded lookup evidence, verified recipient provenance, real Gmail draft; no send | Existing SignalHire account evidenced; free login/API entitlement unverified; no lookup/draft |
| D1 | Integrated frontend/API/schema/worker checks and release | Relevant regressions and local integrated checks, live provider acceptance, rollback and restart evidence; sanitized report pushed | Pending |
| D2 | Review and merge the completed work | Owner's requested completion condition met, reviewed exact head, no unresolved critical acceptance failures; no hosted workflow dispatch | Pending |

The applicant threshold remains 1,000, age 14 days, score 50, all company stages.
The earlier once-asked decision about `100+` lower-bound-only counts remains
pending. A numeric threshold change alone does not authorize inventing its upper
bound. Continue useful independent work rather than repeating the question.

## Current priority — November4, after first genuine Apply

[First genuine questionnaire and recovery evidence](../acceptance/naukri-first-questionnaire-recovery-20261104.md)
is authoritative over older snapshots below. API581ec79 and same-ID extension1.3.30
are installed; execution/Telegram/native remainb6b0690 and frontendae66975. Actual
readiness,2,041-record preservation, profile5 and account-binding1 passed. The
actual frontend resumed RUN130 with score50/age14/applicants1,000/any-skill and the
unchanged lifetime-one/hour-one supervised policy.

One new eligible worker Apply reached a real recruiter questionnaire. The text
editor plus optional Skip control is now supported. The owner answered the missing
training fact, but the original browser session changed and its exact tab is no
longer available. No answer was admitted; no Apply may be replayed. Complete the
bounded independent account/history reconciliation, retain the uncertain packet
and admission permanently, and never promote an absent history row into evidence
that retrying is safe. The original lifetime-one allowance was consumed. The owner subsequently
approved one additional distinct eligible attempt: only the lifetime cap changed
to2, hourly1 and all other controls stayed unchanged, and the actual frontend
resumed RUN132. The original uncertain admission remains consumed. Keep
AUTO gated on a strict persistent first receipt. Current receipt count is zero
new, with historical QTrino kept separately.

The owner-lock fast path and Stop/Start history fix are installed. Targeted fixtures
passed, but performance/focus/real-form restart acceptance and recurring locked-Mac
submissions remain incomplete. Existing earlier bounded locked **read** evidence
is retained and does not establish locked filling/submission. No other platform
activation, hosted Actions, merge or cleanup until its applicable prerequisites.

## Execution and evidence rules

November4 live continuation: any-skill policy was installed and saved through the
actual frontend, RUN116. A genuine internship scored90.56 and passed fresh listing,
account/PDF and prior-status checks. Its admission request failed503;0 admitted
Apply/new receipts. Read-only reconciliation found no exact history row; keep
that identity quarantined without another Apply. Online public constraints and
trigger guards still implement the old manual-only lifecycle. Sourceae66975 adds
a pinned eight-constraint/three-function followup, ordered packet/audit writes
and small quota projections. Source108 regressions and exact candidate108 pass;
actual PostgreSQL17 public-SQL journey and rollback guards pass9 groups. Online
DDL003 was subsequently applied once on November4 through the existing authorized
Supabase CLI administrator session. Full online catalog/security and preserved
STOP117/1884/profile5/binding1 checks passed; the actual frontend resumed RUN118
under lifetime-one/hour-one SUPERVISED. Full private restoration of the encrypted
owner archive also passed47 table counts/20,937 rows, two PDF checksums and two
OAuth envelope decryptions without refresh or provider calls. The earlier MCP
OAuth refresh failure does not require an owner action for this completed repair.
One fresh candidate redirected; another exposes Apply on company site and remains
unsupported. Zero new admissions/receipts: continue genuine direct candidates and
required-fact parser diagnosis before AUTO. See the
[current live report](../acceptance/naukri-online-worker-repair-20261104.md).

Latest owner correction (November4, current chat): require **at least one verified
listed skill**. This supersedes the earlier every-listed-skill choice below.
Keep minimum score50 and the remaining age/applicant/experience/location/history/
identity/resume/quota gates. Preserve unverified skills as unknown; do not add
claims to profile/resume or invent screening answers. Expose all/any skill mode
in the existing per-platform dashboard policy, defaulting old data to all until
the owner's explicit correction is applied. Deploy all policy consumers together
under STOP, persist this correction with its prior decision, then recheck held
jobs and pursue the first supported real application/independent receipt.

Owner decision (November4, current chat): **Keep requiring every listed skill**.
The owner explicitly chose that rule for a genuine86.11-score internship held on
unverified AWS. Preserve the strict skill gate independently from minimum score50;
do not add AWS without actual verified evidence or silently allow skill gaps.
Fix the Express/Express.js spelling equivalence without inferring a new skill.
The prepared optional skill-gap control was not installed or enabled; its draft
was preserved privately and removed from the current change. Record the owner's
decision durably, never ask it again, and pursue only fully qualified real jobs.

November3 recovery task: the selected binding has no fresh extension heartbeat
and its old normal window is absent. Prepare policy-checked recovery from a
windowless loaded profile: authenticate its ordinary heartbeat without granting
browser work, keep its public status offline until a real window is bound, and
allow one inactive blank window only for the selected, approved binding while
Naukri automation is running and command consent remains enabled. Use Chrome's
documented background permission and `windows.create({focused:false})`; never
activate an existing window, navigate an owner tab, or launch a different profile.
Reject recovery under Stop/OFF, missing approval or bad credentials. Validate
backend and extension guards plus actual isolated Chromium focus behavior. The
current offline installation may still need the once-requested owner reopen to
receive the update; do not claim installed Mac recovery or real application
acceptance from a prepared candidate or fixture.

Current live inspection bottleneck (November 2 continuation): 167 pending reads,
31 URLs advertising a zero-year minimum, and the recovered cohort at positions
99–116. Prioritize ordinary listing reads whose URL experience hint contains the
saved verified experience, after every lease check and application/receipt work.
URL hints must never populate job facts or authorize submission. Preserve FIFO
within priority lanes, and return inspections waiting two hours to the front of
the read lane to prevent starvation. Unknown hints/profile experience keep FIFO.
Validate restart ordering, aging, active-lease protection and unchanged real
eligibility; install only the exact tested API with queue STOPPED and rollback.

Keep source and immutable installed releases distinct. STOP during replacements,
preserve exact prior releases, stable extension ID, credentials, approved bindings,
application history and rollback files. No owner tab/window activation or use of
keyboard/clipboard. Protect uncertain saves/submissions from repeats.

Build and run targeted regressions for changed behavior, then the relevant local
integration checks. Use actual portal evidence for live acceptance. Record exact
component SHAs, test counts, timings, failure codes and PASS / FAIL / BLOCKED /
NOT TESTED results in sanitized reports linked from PR #48. Do not publish personal
profile/resume/mailbox/browser contents. Do not trigger hosted Actions.

Completion means the agreed supported flows have demonstrated real recurring
applications and all critical acceptance checks pass. A Mac-only service requires
the Mac awake, connected and the bound browser available; no zero-error or
indefinite 24/7 guarantee is claimed from a bounded test. New desired features do
not make the current scope unbounded. Unavailable provider access and owner-only
facts remain explicit, not fabricated success.

The requested “Get Shit Done” plugin was searched in connected plugin discovery
and local skill paths; no matching installed integration was found. The search
returned unrelated integrations. Continue this executable repository plan without
claiming that plugin is installed; additional plugins may exist in the
[plugin directory](https://chatgpt.com/plugins).

Latest implementation and installed evidence: [policy rechecks and restart report](../acceptance/naukri-policy-rechecks-20261101.md). The live unknown-count rule remains review; an explicit narrow lower-bound option is now available without selecting it for the owner.

First-receipt server prerequisite: [exact implementation and installed negative proof](../acceptance/naukri-first-receipt-gate-20261102.md). This does not replace first real submission or critical live/locked acceptance.

Actual inactive profile setup and genuine skills editor inspection:
[installed1.3.18 evidence](../acceptance/naukri-profile-editor-inspection-20261102.md).
The provider editor was inspected, not saved. Existing28 skills must be preserved;
its observed remaining input capacity constrains additions. First new application
and recurring acceptance remain OPEN.

Genuine provider profile-write acceptance: [verified add-only skills Save](../acceptance/naukri-verified-skills-save-20261102.md).
The installed system saved31 skills while preserving all28 originals and verified
them on an independent provider document with actual PDF-byte checks. Native
contract and actual frontend launcher deployment mismatches were corrected and
recorded. Remaining profile facts, first new application, recurring AUTO,
performance and locked/restart acceptance remain unfinished.

[Installed dashboard read batching](../acceptance/naukri-dashboard-read-batching-20261102.md)
reduces actual profile/queue status SQL counts from6/8 to2/5 under the unchanged
connection budget. APIb3abc9e installed; real skills `SYNC_VERIFIED` retained.
Performance, first application and recurring/locked acceptance remain OPEN.

[Locked provider reads and installed real listing details](../acceptance/naukri-locked-reads-and-real-details-20261102.md):
four genuine locked readiness200 samples plus actual discovery/profile-PDF/listing
operations; extension44bbc4c/1.3.21 installed. This is bounded read acceptance,
not locked filling/submission, sleep recovery or full recurring acceptance.
First new application remains OPEN.

[Installed bounded ordinary-read continuation](../acceptance/naukri-bounded-read-continuation-20261102.md):
extensionec1a5b7/1.3.22 installed under STOP100 then RUN101, unchanged SUP1.
Real discovery and rejected-listing processing continue while the Mac reports
LOCKED; zero new submissions. A live throughput improvement is not yet proven.
Next investigate ordinary search controls to find more suitable fresh jobs,
without relaxing unknown counts or required experience.

Current task: when the confirmed profile has less than one year of verified
experience, interleave an ordinary `<target role> fresher` search with each
original target-role search. Do not change saved target titles, personal facts,
matching, filters, discovery interval, pagination bound, submission authorization
or history. Preserve original searches because the keyword is only a discovery
hint. Validate durable query rotation/restart/dedup with targeted regressions,
build and install the exact API candidate under STOP with rollback, then inspect
actual resulting searches and full-listing eligibility before claiming benefit.

Actual November2 evidence changes the next task: the11:13 fresher document before
sorting contains junior/sub-year listings, but the completed Date-sorted search
adds three senior identities with zero overlap with that initial set. Preserve
the genuine Recommended ordering for fresher keyword searches, validate its
recognized control/page/document and retain full listing age/eligibility checks.
Keep existing Date behavior for complementary original searches. Verify isolated
sort-change regressions and exact extension cutover, then compare genuine
admitted candidate identities with the initial keyword result set. Do not claim
the backend keyword change alone improved final discovery.

[Focused fresher discovery and actual search-order correction](../acceptance/naukri-focused-fresher-discovery-20261102.md):
API8473bdc and extension0c8b1d7/1.3.23 installed, RUN105 unchangedSUP1. Real
Date-sorted output contradicted the initial junior results; the corrected actual
Recommended cycle added17/17 identities from its captured set. Suitable yield
and the first application remain unaccepted. Next address the inspection backlog
and ensure application progress/reconciliation is not delayed behind discovery;
full eligibility, history and admission guards remain required.

Current scheduling task: recover/check all active leases before prioritizing
existing application and reconciliation operations over `inspect_job`, retaining
FIFO within each lane. No extra database queries, concurrency, write admission or
quota changes. Verify restart ordering and active-lease exclusion, build/install
the exact API candidate under STOP, then retain genuine live submission status.

[Installed experience-guided inspection](../acceptance/naukri-live-inspection-order-20261102.md):
API0e75386 under STOP108/RUN109, same SUP1 policy. Five genuine native
claims prioritized zero-minimum experience hints, including three recovered
candidates; all five rejected/held and no Apply admitted. Page/context holds
need diagnosis; URL hints do not establish eligibility. First receipt and
recurring/restart/locked application acceptance remain OPEN.

[Installed actual browser recovery](../acceptance/naukri-live-window-recovery-20261104.md):
API/extension2c9d481, extension1.3.24 same ID. STOP110 prevented reopening despite
two fresh windowless native heartbeats; RUN111 recovered a new inactive window
with the same approved binding/session and unchanged working Chrome selections.
Two real discovery cycles completed; fresh provider PDF bytes100198 and previous
skills Save independently reverified18:46:12UTC.1,614 retained identities and
0 admitted Apply/new receipts. First application and recurring/restart/locked
application acceptance remain OPEN; unknown-count decision remains pending.
