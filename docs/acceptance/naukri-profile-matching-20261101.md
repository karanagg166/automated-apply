# Real profile completion and matching corrections — 2026-11-01

**OPEN: no new verified application receipt.** Owner authorized filling missing
profile data from confirmed evidence. Work remains on the existing branch
`fix/live-prepare-discovery-20261030`, [PR #48](https://github.com/karanagg166/automated-apply/pull/48).
Implementation: [`f13c956c3a00f8434a4152f7c8ff451cb5eaca14`](https://github.com/karanagg166/automated-apply/commit/f13c956c3a00f8434a4152f7c8ff451cb5eaca14).
Previous [screening release acceptance](naukri-screening-continuation-20261101.md)
remains applicable. All times below are UTC; private profile/resume/DOM evidence
and exact save intents remain outside Git.

**Later live continuation:** employment was saved once and independently verified;
the provider switched this account to its professional profile layout. Extension
**1.3.15 / 08aab53f3ae0eeb018dedcbdeed30544bae4504f** now supports that genuine
layout, and the installed extension again verified the real canonical PDF there.
Details below supersede the earlier unsaved-employment status without deleting it.

## Real changes and verification

The genuine approved Profile 8 page had five skills and empty summary, employment
and project sections. The local verified profile already held a summary, role,
education and four projects. No login/contact email was disclosed or overwritten.

With the queue STOPPED revision **35**, the confirmed canonical PDF was parsed
locally. **19 explicitly printed skills** missing from the local record were added,
preserving all 23 existing skills, every career record, contact field and preference.
Local profile **version 3 → 4**, **42 skills**. The owner current-session instruction
authorized this additive completion from the confirmed PDF. Its confirmation and
source digest were persisted atomically with an audit record; this was not an
unreviewed arbitrary import. Resume bytes and private profile snapshots are retained.

An initial operator script imported model metadata before loading the selected
production configuration. Its transaction failed with `UndefinedTableError` before
writing (`job_agent.owner_preferences` was not the configured schema). The corrected
script loads configuration before model imports and uses the original owner lock,
version comparison, schema validation and transaction. No schema/table was created,
no database settings changed, and no partial profile update was committed.

The actual Naukri **Profile Summary** Add control and its genuine unlabeled
`textarea#summary` were inspected. The existing verified 311-character summary was
filled and saved **once**, with a private preimage/save-intent journal. Independent
page reload verified the exact saved summary and approved account. Placeholder
instructions were never interpreted as candidate summary text.

Naukri **Key skills** was completed using its ordinary autocomplete options. The
original five labels were preserved; **28 total provider labels** were saved once,
then verified after an independent reload on the same approved account. Only exact
verified labels or explicit spelling equivalents were selected. **16 canonical
labels had no supported exact suggestion** and were left out of this provider save;
they remain in the local verified profile. No related skills were invented.

The first chained browser-timer skill fill progressed very slowly in the inactive
tab. It was explicitly cancelled before Save; its local cancellation marker was
not evidence of owner adoption. External bounded DOM steps completed the supported
selection. An initial final-state assertion occurred before React's asynchronous
chip update; actual selected labels were re-observed before continuing. No failed
attempt clicked Save or replayed a submitted save.

Employment was filled from the confirmed role and resume month evidence, preserving
the four-month total and not asserting current employment. **The provider kept its
Save button disabled** despite visible fields and no rendered validation error.
The form was cancelled unsaved; the disabled control was never altered or bypassed.
Employment/projects, birthday, languages, compensation and other missing personal
facts are not claimed complete. No fabricated dates, salary, authorization or
certification was entered.

### Actual employment completion and professional-layout transition

The first disabled employment form was cancelled unsaved. A second ordinary form
attempt retained the verified role/company, June–September 2026 month evidence,
four-month total, noncurrent-employment state and a grounded description. After
separate settled field/blur events, the provider's genuine Save button became
enabled with no displayed validation errors. The initially reported disabled state
was retained; a later cancellation guard refused to cancel once that state changed.
No disabled attribute, provider validation or private component state was altered.

Queue was STOPPED as revision **37** before the one Save at **10:57:57**. Its private
durable intent contains exact preimage, account/profile binding, fields and outcome.
At **10:59:01**, independent page reload verified exactly one saved role/company,
**Jun 2026 to Sep 2026 (4 months)**. No current-employment or salary claim was added.
There was no repeated Save and no application action. The public provider bundle
was read to understand ordinary field callbacks; no private API, cookie, framework
state or provider function was invoked directly.

Saving employment caused the genuine provider to switch from its fresher layout
to the professional profile page at the same URL. The earlier adapter could not
assume that account and resume widgets were unchanged. The queue remained stopped
while this compatibility was corrected:

- Verified account identity appears in the scoped `.detail-list .with-cta`
  `span.txt[name="Email"]`; it still matches the approved login binding independently
  of canonical contact email. No email was overwritten.
- Professional summary uses a widget/card and a collapsed **Read More** control.
  The adapter expands only that observed summary control before hashing/comparing
  its complete text; truncated text is not accepted as the saved summary.
- Resume Download is the observed `#lazyAttachCV.card` preview's labeled role-button
  span. The same bounded MAIN-world blob interception captures the PDF generated
  by that ordinary UI, then the isolated world checks approved identity and digest.

A direct AppleScript-world capture experiment returned
`profile_resume_download_pdf_not_observed`, while actual resource timing showed a
successful 100,198-byte download response. It was not claimed as checksum success.
The production extension's MAIN-world capture was subsequently tested separately
and passed on the genuine page. No provider endpoint, authorization header or
cookie was extracted or replayed by the adapter.

The exact extension-only candidate
[`08aab53f3ae0eeb018dedcbdeed30544bae4504f`](https://github.com/karanagg166/automated-apply/commit/08aab53f3ae0eeb018dedcbdeed30544bae4504f)
was built in an owned immutable linked worktree. **Seven focused actual isolated
Chromium cases passed in 4.453 seconds** (three preceding modern-profile cases
overlap); **32 focused Node cases passed in 0.976 seconds**. Provider/unexpected/
chooser requests were **0 / 0 / 0**. Professional-layout cases verify the actual
account/widget shapes, full expanded summary, MAIN PDF capture/isolated identity
recheck, one Download/no new tab/no Delete, and wrong-account refusal.

At **11:04:40**, extension **1.3.15**, **23/23 exact files**, same stable ID, ordinary
Reload and fresh native reconnect passed. Queue STOPPED **37**, **358** records,
profile version **4**, approved binding **1**, all service/native references and
protected credentials/configuration were preserved. Backend/database ready returned
**200 in 2.130 seconds**. Front-window and all selected-tab ID snapshots matched
before/after cutover. A verified exact **23-file 1.3.14** rollback inventory and all
previous releases/plans remain. API/execution/native stay f13c956, Telegram a093eab,
frontend f90cfe7; only the extension changed.

At **11:04:55**, queue resumed **RUNNING revision 38**, unchanged score **50**,
SUPERVISED allowance **1**, hourly cap **1**, other filters unchanged. A temporary
read-only comparison had no approved profile write fields. At **11:05:20**, the
installed extension genuinely downloaded the professional-layout saved resume:
**100,198 PDF bytes/checksum match canonical**, outcome **COMPARED**. Its approved
account/profile checks passed. Original disabled comparison policy was restored
as revision **19** at **11:05:37**. This verifies the real changed layout; it is
not an application receipt or locked-screen submission acceptance.

Two further genuine new-release discovery cycles had admitted **11 new jobs in
total (347→358)** by **10:55:29**, no source error. Inspection continues under the
unchanged filters. No new Apply admission, answer/upload, submission receipt or
submission notification has been claimed. QTrino remains historical and unreplayed.

### Further genuine profile/discovery continuation

An empty professional **Resume headline** was completed from the confirmed role,
four-month experience and verified technical skills, without claiming current
employment. The observed form permits 250 characters; the 128-character factual
headline was saved **once at 11:12:00**, then independently verified after reload
at **11:13:15** on the same approved account. Exact text/source/save intent remains
private. The queue was STOPPED **39** for Save and resumed **RUNNING 40** with
unchanged SUPERVISED-1/hour-1, score-50 policy after verification. Opening this genuine
modal adds the observed `?action=modalOpen` query; an initial strict URL guard refused
input until that exact owned control transition was recognized. No endpoint was
guessed. A hidden retained editor node was not treated as a failed save: the actual
saved widget and independent reload established persistence.

The actual professional project form requires **client label and start month**,
plus project status and an end date for finished projects. The resume's isolated
project month labels do not establish these facts. The untouched form was cancelled
unsaved, the own inactive setup tab restored, and the owner was asked once for the
specific missing project facts. This does not block independent job discovery;
no personal-project client or duration was invented.

At **11:14:31**, genuine discovery had increased the queue to **396 records**:
261 SKIPPED, 102 NEEDS_INPUT, 31 DISCOVERED, one MATCHED pending eligibility and one
retained historical receipt. Source **11:13:31→11:13:50** admitted **18 new unique
jobs**, no source error. The previous **11:05:34→11:05:56** cycle admitted **20**.
The MATCHED state means listing ingestion, not successful eligibility/preparation:
the subsequent query found no remaining MATCHED work, and no new Apply or receipt
is claimed. Worker and Telegram live polling continued. First-receipt/recurring
AUTOMATIC and locked real submission acceptance remain OPEN.

## Code corrections

- Exact skill spelling equivalents now match: React/React.js/ReactJS,
  Node.js/NodeJS, Next.js/NextJS, Express.js/ExpressJS, Postgres/PostgreSQL and
  similarly explicit variants. Required-skill aliases are deduplicated before
  scoring. C/C++, Java/JavaScript, SQL/MySQL and ambiguous Node remain distinct.
- An unrestricted preferred-location list plus `any` remote preference now accepts
  an explicitly known location for location scoring. Previously onsite jobs lost
  20 points even though the owner had imposed no location restriction. A restricted
  location still does not match elsewhere; a missing location remains unknown.
- Genuine modern Profile Summary H1/cards/Add/pencil and modal controls are
  supported. Empty placeholder cards stay empty. Short-lived action permits keep
  their original duration; MutationObserver reacts to actual React DOM mutations
  instead of chained inactive-tab timer sleeps consuming the permit.
- A visible/adopted execution document stays fenced after it becomes hidden again.
  Null preimage references omitted by Chrome injection are treated as null only
  for an actually verified empty summary. Nonempty hashes still must match.

No submission filters, daily/hourly limits, profile login binding, metadata conflict
rules or first-receipt gate were relaxed. In particular the saved early-stage/startup
requirements remain enforced. A missing resume skill is a data-completeness issue;
it is not permission to infer unrelated skills from project code.

## Exact deployment and real post-restart behavior

API, execution worker, native host and same-ID extension **1.3.14** use exact
**f13c956c3a00f8434a4152f7c8ff451cb5eaca14**, **23/23 files**. Telegram remains
**a093eabc1ca1f0989b4ff7e3f7be187f442ddb2a**; frontend remains
**f90cfe7ea3dfc7ca20efe1a1995b3da26707a028**. The immutable candidate has its own
pinned Python environment; no running release was edited as development source.

Queue STOPPED revision **35** through cutover; all **347** existing records,
account binding revision **1**, credentials, profile version **4**, saved resume,
history and policies preserved. Exact old plists/native wrapper/all **23** old
extension files and their hashes are retained in the new private rollback plan;
older plans/releases remain intact. The generic retained installer rollback prose
still mentions “22 previous files”; the actual inventory/assertion/backups contain
23 and rollback uses that inventory, not the prose. Rollback never restores a
database snapshot over outcomes or reverses the owner's verified profile additions.

At **10:49:20**, backend/database readiness returned **200 in 2.212 seconds**,
frontend login **200**, selected native connection returned CONNECTED after ordinary
same-ID Reload, and front-window/all selected-tab ID snapshots matched before/after
cutover. Paired screen state was **UNLOCKED → UNLOCKED**. Protected-file digests,
record count, account and policy checks passed. No focus, owner keyboard or clipboard
operation was used. Only the existing owned inactive setup/profile tab was used.

At **10:49:24**, queue resumed **RUNNING revision 36**, minimum score **50**,
SUPERVISED one-application allowance/hourly cap **1**, unchanged other filters.
The first genuine new-release discovery cycle, **10:49:40 → 10:50:04**, admitted
**ten new unique real jobs**, **347 → 357** records, no source error. Actual job
inspection continues; URLs/durable rows are not successful applications.

At **10:51:04**, the installed extension's ordinary read-only profile comparison
independently reported **summary MATCHED**, and actual Resume Download again yielded
**100,198 PDF bytes**, checksum matching the canonical PDF. Account binding and
confirmed profile version 4 passed. No profile write fields were approved for this
probe. The original disabled comparison policy was restored as revision **17** at
**10:51:14**. Telegram continued fresh live polling with no reported error. There
were still **zero new Apply admissions and zero new receipts** at this snapshot.

## Targeted checks and limits

| Check | Result | Evidence class |
| --- | --- | --- |
| Matching/live-discovery/background queue/queue regression set | **96 PASS, 9.24 s** | Isolated fictional database; includes 13 added skill cases and one location case |
| Exact immutable candidate own environment | **35 PASS, 3.27 s** | Matching, location and profile-sync cases; overlapping preceding matching tests |
| Focused modern profile Chromium run | **3 PASS, 4.331 s** | Actual isolated inactive Chromium with fictional values |
| Final combined execution/profile/chatbot Chromium run | **32 PASS, 107.926 s** | Actual isolated Chromium; three new modern-profile cases |
| Provider/unexpected/chooser requests in Chromium | **0 / 0 / 0** | No fixture request reached live Naukri |
| Ruff, selected Prettier, whitespace, candidate pip check and extension build | **PASS** | Exact implementation/candidate |
| Real provider summary save and independent reload | **PASS** | Genuine Profile 8, one save, exact value persisted |
| Real provider skills save and independent reload | **PASS** | 28 supported labels, originals preserved |
| Local verified-profile completion | **PASS** | Atomic version 3→4, 19 additions backed by canonical PDF |
| Real employment save | **PASS after retained initial failure** | Initial disabled form cancelled; second Save enabled normally, clicked once, role/months independently verified after reload |
| Professional-layout account and saved PDF | **PASS** | Same approved identity; genuine installed 1.3.15 Download and PDF byte/checksum match |
| Required-upload and real questionnaire resumption | **NOT TESTED LIVE** | Previous fixture guards remain; no new eligible application reached them |
| First new real application/independent receipt | **BLOCKED** | Discovery/inspection underway; no admitted qualifying submission |
| Recurring AUTOMATIC / 24/7 submission | **NOT ACCEPTED** | First new receipt and critical acceptance remain required |

The initial modern-profile fixture failed before installation because Chrome
injection omitted a null preimage; corrected empty-value handling preserves the
nonempty hash fence. A later fixture used textual “Edit” inside a heading where the
actual site has an icon; correcting its actual structure resolved that false layout
failure. A mistyped profile-sync pytest filename ran zero tests; the exact candidate
used the correct file. These are fixture/operator failures, not new real receipts.

Reproduce:

```sh
.venv/bin/python -m pytest backend/tests/test_application_assistant.py backend/tests/test_phase2_live_discovery.py backend/tests/test_naukri_background_queue.py backend/tests/test_application_queue.py -q
.venv/bin/python -m pytest backend/tests/test_naukri_profile_sync.py -q
NAUKRI_PROFILE_ONLY=1 pnpm -C extension exec node tests/naukri-execution.browser.mjs
pnpm -C extension exec node tests/naukri-execution.browser.mjs
pnpm -C extension build
```

Continue real discovery/inspection using the completed verified profile, repair
supported employment/project form handling, obtain missing personal facts only when
needed, and submit one genuinely eligible supported application under the standing
authorization. Verify receipt independently before bounded recurring AUTOMATIC.
Never replay QTrino or uncertain submissions. No merge, hosted Actions, Gmail
sending, other-platform activation, release deletion or cleanup occurred.
