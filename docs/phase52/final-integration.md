# Phase 5.2 final integration

Release decision: ready for code review; merge, installation, genuine filling and
live Telegram delivery still require separate owner approval. No further phase
is included.

The integration starts at reviewed PR #44 head
`231913c25fd79052b9468bb0b1dde5b5bf6cb4a0` and applies AGY's exact local commit
`8f900b4ab3fb8f3e8fe1da701d293af370221f47`, inspected before integration. Both
were available in the primary repository's object database. Work was performed
on `integration/phase52-final-20261029` in a linked worktree. The primary checkout,
AGY worktree, existing backend/native/extension production implementation and
installed release `0384fb403618c396fa60c7fb79a6b4ecebafa925` were preserved.

## Combined dashboard and contract corrections

- Durable exact application/job task, destination, tab, packet/profile revisions,
  current step, challenge status and next action remain visible.
- AGY's field → proposed answer → evidence/provenance → status → next action
  review, manual-action panel, progress display and receipt history are integrated.
- Pause/resume/cancel retain optimistic task-version checks. A conflict refreshes
  state without replaying the action. Unsaved edits block resume and approval.
- Dirty answers survive server answer/revision refreshes and edits made while a save is in flight. Browser unload warns
  before discarding dirty edits. Stale-packet/form warnings preserve saved work.
- Task states and result statuses derive from generated OpenAPI types. Regeneration
  produced no diff against the reviewed backend contract. Production API routes,
  native protocol, extension permissions and fill implementation are unchanged.
- Only `retained_after_blur` results with status `filled` count as verified receipt
  history. Assignment-only, failed and interrupted/unknown receipts stay manual.
  Partial receipts can contain some verified results without implying completion.
- Receipt IDs (`f0`, etc.) identify one DOM snapshot; packet field IDs are UUIDs.
  The current API has no mapping between them. Consequently the dashboard shows
  verified page-local results in receipt history and does **not** invent per-packet
  field verification. A saved answer's review status is separate.
- No task, stale task and unavailable status never imply a cleared challenge.
  `submission_unknown` and `submitting` never complete the submission progress step.
- The guard notice explicitly excludes pre-existing streams and independent
  background activity; it does not promise universal network isolation.

[Combined fictional dashboard screenshot](screenshots/extension-field-review-fictional.png).

## Focused validation performed for this integration

No full suite or hosted GitHub Actions was run. The prior 187 backend, 104
extension and 100 AGY frontend tests were not rerun as suites.

| Check | Result |
| --- | --- |
| Affected frontend and gateway tests | 68 passed across `field-review-experience`, `applications`, `extension-assistant`, `extension-gateway` |
| Final copy regression | Extension-assistant's 16 tests passed after updating the guard wording assertion; the other 52 affected tests passed with the final source |
| Generated OpenAPI / frontend API types | Export/regeneration passed; generated file unchanged |
| Typecheck | Passed |
| Production build | `pnpm -C frontend build --webpack` passed |
| Production dashboard Chromium | 1 passed: field/provenance rendering, exact versioned pause, reload, stale resume rejection; refreshed fictional screenshots |
| Native-host/extension smoke | 7 real isolated Chromium/MV3/Python native cases passed, fictional HTTP backend |
| Integrated PostgreSQL journey | 1 real Chromium → MV3 → Python native host → FastAPI → disposable PostgreSQL 17 journey passed |
| Targeted interruption/permission regressions | 7 passed: partial cancellation, in-flight inspection invalidation, browser restart, navigation/closure, dashboard cancellation, missing origin grant, guard permission denial |
| Real network guard Chromium/HTTP | 5 cases passed: GET/POST/direct form blocking, worker restart, unrelated tab, explicit release |
| Fixture safety | 4 negative checks: non-testing environment, remote database, usual PostgreSQL port and wrong database name rejected before connection |
| Formatting / Ruff / whitespace | Changed frontend/test files and fixture script passed |

Commands use the existing dependency environments, pnpm exclusively for JS and
isolated browser profiles. The production build uses the documented webpack
fallback for the engineering worktree's external dependency symlink; standalone
tracing reports files outside its root. Installation must use a release-local
dependency installation before producing its standalone artifact.

The updated stack harness owns a fresh `postgres:17-alpine` container, uses
`--pull=never`, exposes only a random loopback port, creates fictional ORM tables,
and removes its container after the journey. It accepts no owner DSN. An
independent `psql` query confirmed the task receipt in PostgreSQL after the API
read. One retained field, one preserved pre-existing value, one durable receipt,
a refused duplicate fill, cancel and explicit guard release were observed.
There were zero fixture employer write requests or submissions. This is test
persistence evidence, not a migration or production-database acceptance claim.

## Critical stack audit

| Boundary | Evidence and result |
| --- | --- |
| Exact application/tab and owner | Existing task UUID, application/job, browser-session/tab and plan checks retained; gateway fixed routes/owner session/CSRF and native actor checks inspected |
| Stale packet/answer rejection | Backend context/answer-revision checks preserved; final UI generated types, dirty-refresh test and Chromium stale-resume check passed |
| Chrome access | Production manifest unchanged: required DNR and per-origin optional HTTPS grants; refusal checked before opening a task tab |
| Guard lifecycle | Installed before authorization/events; pause/cancel keep it; explicit takeover releases it; real Chromium/HTTP and PostgreSQL journey passed |
| Partial pause/cancel | Versioned dashboard pause passed; partial DOM cancellation saves completed results and stops remaining fields; current backend audit-only interrupted receipt path inspected |
| Browser restart / refresh / navigation | Native recovery smoke, targeted session/tab/navigation checks and dashboard reload passed; no executable authorization is restored |
| Retained values / database receipts | Eventful retained readback, API read and independent PostgreSQL row inspection passed; unknown/assignment receipts cannot become a dashboard success |
| Telegram correlation / duplicates | Existing exact prompt reply, owner identity, expiry/context/revision and delivery-unknown handling inspected; no real message sent; prior reviewed backend tests remain recorded separately |
| Submission | Extension/native commands expose no employer submit; dashboard has no extension fill/submit route; controlled journeys observed zero submissions |

The tab guard cannot demonstrate control of pre-existing streams or independent
background activity. Service-worker-controlled eventful pages remain read-only.

## Genuine acceptance remaining

Fresh read-only [Hevo inspection](final-hevo-inspection.json) at
`https://jobs.lever.co/hevodata/6cbbe304-e065-4711-bf3e-756795d2bc2a/apply`
returned HTTP 200, ten ordinary fields and `WIDGET_PRESENT_UNVERIFIED`.
The owner previously reviewed the exact private packet/proposed profile values
and explicitly kept Hevo read-only. That scope remains unchanged. No candidate
values were entered and no challenge was manipulated.

The prior [genuine-site observations](acceptance.md) also found unverified
widgets on Razorpay, Cloudflare, Veeva and Sarvam. No current generic adapter can
establish supported site-verified challenge resolution. Genuine retained filling
and genuine multi-step completion therefore remain unverified; this release does
not claim a live PASS. Additional fill approval cannot bypass this limitation.

For a future legitimate eligible form, first present privately its exact employer
URL, saved application ID, packet/profile/answer revisions, each selected field's
exact proposed value and source, and current challenge evidence. Request specific
owner authorization for those fields and any input/change/blur events. Fill only
after that authorization and fresh eligibility checks; validate retained values
and stop before submission. Real Telegram delivery needs its own specific owner
approval of the destination chat and test message.

## Publication, installation and rollback

Publish the integration commit to PR #44's existing branch and mark that PR ready
for code review after checking its exact remote SHA and mergeability. This does
not authorize merge or installation. Manual-only workflow triggers are preserved.
No other frontend PR or handoff PR is created.

Installation needs separate approval to activate the exact reviewed SHA across
backend/frontend/native host and reload extension ID
`gdjbmkffcpicbpiikcohlmokkmcpipgp`. Chrome permissions are `contextMenus`,
`activeTab`, `nativeMessaging`, `storage`, `scripting`, and required
`declarativeNetRequest`. The new DNR permission must be accepted at installation;
Chrome does not permit optional declaration of this API. Optional
`https://*/*` only permits later individual `https://<chosen-origin>/*` prompts;
it grants no blanket host access. Each employer origin and exact fill remain
separate owner gestures. No tabs enumeration or cookies permission is requested.

Keep installed `0384fb4…`, existing rollback worktrees, service/native backups,
credentials, approved online database and encryption keys. No migration or real
data write is required. Follow [installation and rollback](install-and-rollback.md).
Private/runtime file hashes and the primary Git state are rechecked before
publication; inventories stay ignored. No production services were restarted.
