# Naukri account binding saved; compatible candidate ready for installation review

**OPEN: no new live application or provider receipt.** The first new submission,
recurring AUTOMATIC operation and locked-browser acceptance have not passed.

- PR/base: [#48](https://github.com/karanagg166/automated-apply/pull/48), `main`.
- Branch: `fix/live-prepare-discovery-20261030`.
- Exact implementation/build candidate: [`fc91a219d5b824f934bb733eaf20166661e1f08b`](https://github.com/karanagg166/automated-apply/commit/fc91a219d5b824f934bb733eaf20166661e1f08b).
- Still installed: services/native/frontend **`ee8c591b382626f657f3e99f2e757c303ec217b0`**;
  Profile 8 extension **1.3.3**, ID `gdjbmkffcpicbpiikcohlmokkmcpipgp`.
- Candidate extension **1.3.4**, same key/ID/permissions, **22/22** built files
  matching its exact Git source; not installed or runtime-reloaded.
- Previous [installed audit and failures](naukri-installed-ee8-audit-20261031.md)
  remain applicable. Existing `70dad04` listing/batching fixes are ancestors of
  this candidate, not a separate installed version.

## Actual Mac and online evidence

The owner explicitly confirmed Profile 8 as the intended Naukri account. A
separate, versioned platform-account binding was committed to the existing online
PostgreSQL owner-preference store and read back at **revision 1**. It binds the
candidate ID and selected authenticated Chrome installation to the hash of the
observed portal identity. The canonical contact email was checked unchanged;
the two identities still differ legitimately. Neither email, account hash,
candidate ID nor resume bytes are published here.

The first read-only live inspection saw the genuine `.section.resume` section,
`.action-container .download` div, `input.upload-input` and Update resume button,
and the `.chip-summary .email-verify` identity node. No Download, upload, Apply,
personal tab mutation or focus change was performed. Later Naukri/extension
settings tabs were no longer open. The persisted account approval therefore uses
the previously captured actual profile UI observation plus the owner's current
explicit confirmation. **It does not claim a fresh portal identity or saved-PDF
verification.** Every future write requires a fresh adapter identity match.

An initial one-connection binding attempt failed with **`connection_limit`**;
no approval was claimed saved by that failed attempt. With the queue confirmed
STOPPED revision 4 (HTTP 200, **2.542 s**; health 200, **0.039 s**), the existing
Telegram poller was briefly gracefully stopped to release capacity, its old PID
exit verified, and one NullPool operator connection was used. Binding persistence
and readback took **8.786 s**, including database reads and integrity checks.
Telegram was restored from its unchanged installed plist. No production source,
configuration, credentials, connection limits or installed component was replaced.
Intermediate operator-script schema-bootstrap/preference-location errors were
fixed locally before persistence; their failed transactions were not acceptance.

A private `pg_stat_activity` snapshot during the bounded maintenance observed
**5/5** role sessions: two named API, one readiness, one Telegram, one operator;
all service sessions were idle/Client, the operator active, **zero lock waiters**.
Execution did not have a session in that snapshot. Current installed execution
logs also contain PostgreSQL TooManyConnectionsError failures. The three earlier
locked readiness failures are now correlated with fixed log category
**`connection_limit`** for all three timestamps. This is evidence of capacity
exhaustion; **screen locking as a cause is not established**. Two API-labelled
server sessions with a configured one-slot API pool warrant follow-up after a
clean approved cutover; no unidentified backend was terminated.

## Implementation and limits

Preparation and profile synchronization no longer hash the contact email to
decide which platform account is approved. They require the persisted account
binding. Native admission and final Apply admission recheck its candidate,
selected Chrome installation, account hash and revision. Missing, changed or
foreign bindings fail closed; reconnects retain the independent approval.
Authenticated owner GET/PUT account-binding routes reuse existing owner controls.
No migration is required.

The extension recognizes the observed modern email and resume controls. A bounded
MAIN-world function clicks the genuine Download control once and observes a PDF
Blob URL that the site's handler creates for its download anchor. It consumes
that download, verifies the PDF header/size and returns only SHA-256 and byte count.
It restores temporary hooks on every exit. The isolated adapter rechecks account
and page context and compares the result against the locally verified canonical
PDF before reporting PROFILE_VERIFIED. The service worker restricts this to its
own inactive tab and checks ownership before/after capture. Existing explicit
same-origin PDF links remain supported. No private endpoint is guessed and no
new Chrome permission is requested.

**The provider's live Download response mechanism remains untested.** If it does
not produce the supported PDF Blob/download-anchor flow, it returns a bounded
unsupported result; filenames never establish verification. Resume replacement,
current questionnaire completion and multi-step resume selection remain unfinished.
The first actual supported direct-Apply path must pass provider PDF verification
and two independent application-history documents before success is recorded.
QTrino and uncertain outcomes retain permanent replay fences.

Readiness now uses NullPool behind the existing coalesced in-flight probe. Its
server connection closes after the observation rather than consuming an idle role
slot between calls. Business pools, role limit, native deadlines and database
timeouts are unchanged. This may add TLS connection cost to each separate probe;
real installed latency and capacity improvement are **not yet measured**. Previous
20-candidate batching and batched Stop events are included, but their installed
76-second discovery / 26.05-second Stop improvements remain unmeasured.

## Validation, counts and resource evidence

These are isolated fictional tests unless explicitly labelled actual Mac above.
Overlapping runs are **not added together**.

| Check | Result | Exact evidence |
| --- | --- | --- |
| Focused backend initial combined run | PASS | **114 passed**, 20.36 s; identity, queue, submission, profile sync, readiness, operational health |
| Incremental identity/reliability after added approval cases | PASS | **35 passed**, 8.51 s; overlaps the combined run |
| Exact pinned candidate own venv | PASS | `pip check`; **34 passed**, 4.65 s; identity/submission/profile sync |
| Extension Node existing full suite | PASS | **159 passed**, 9.398 s, before two added orchestration cases |
| Changed queue Node file including those cases | PASS | **14 passed**, 0.150 s; overlaps existing suite, **2 new** cases |
| Actual isolated Chromium execution | PASS fixtures | **14 cases**, 12.475 s; **0** live Naukri/unexpected requests or chooser events |
| Actual isolated Chromium queue | PASS fixtures | **4 cases**, 8.916 s; **0** live Naukri/unexpected requests or chooser events |
| Disposable PostgreSQL readiness | PASS fixture | **1 passed**, 8 deselected, 0.81 s; concurrent callers pass while business transaction holds its pool, probe leaves zero named idle server sessions |
| Build/contracts/static | PASS | OpenAPI/types regeneration, frontend typecheck and production build, exact candidate independent production build, extension build, targeted Ruff E9/F/I and diff checks |
| Installed provider PDF / replacement | BLOCKED | Profile page needs reopening; candidate not installed; no live PDF checksum |
| First new submission / receipt / notification | NOT TESTED | **0** new applications/receipts/messages; QTrino not replayed |
| Repeated discovery/filter/match/queue | NOT TESTED candidate | Prior installed cycle saved 20 URLs; no new candidate cycle |
| AUTOMATIC mode | BLOCKED | First new confirmed submission and critical live checks still required |
| Awake locked browser/restart recovery | NOT TESTED candidate | Historical 3/3 readiness failures retained; heartbeat is not browser acceptance |

The exact candidate uses its own immutable venv and pnpm dependency/build outputs;
no mutable directories are symlinked into it. Measured allocated size: **1,022,288
KiB** (`du -sk`), not a RAM comparison or cleanup authorization. The separate
candidate frontend log recorded a 5.7-minute TypeScript phase, versus 5.5 seconds
in the earlier development build; workload/scheduling/power conditions were not
controlled, so this is not attributed to a source regression. Long-run CPU/RAM,
installed throughput and repeated queue/control timings remain NOT TESTED.

Initial regression iterations failed on fixtures missing the newly required
binding (53 pass/1 fail, then 69 pass/2 fail); explicit approved fixture bindings
fixed those tests. Initial disposable DB invocations used nonexistent local roles
and failed setup; the final run used the pre-existing isolated fixture's configured
administrator and passed. No production data was used by regression tests.

## Concrete cutover and rollback inventory

A private hash-verified plan is prepared at
`~/Library/Application Support/Automated Apply/installation-plans/naukri-fc91a219d5b824f934bb733eaf20166661e1f08b/`.
It contains previous/proposed four LaunchAgent definitions, previous/proposed
frontend launcher and native wrapper, unchanged native manifest inventory and
**21/21** previous extension files. The existing immutable `ee8c591` release,
private configuration and every historical release are retained. Six installed
references plus private-env/native-manifest hashes were rechecked unchanged after
preparation. No release was deleted or merged.

After owner approval of **exact `fc91a219d5b824f934bb733eaf20166661e1f08b`**:

1. Revalidate STOPPED queue/no active action, plan hashes and original process IDs.
2. Gracefully stop services; verify every original PID exits **before** replacing
   references or starting any replacement. Stop on any failed exit guard.
3. Install the six reviewed references; preserve private env, native manifest,
   stable extension key/origin, profile and data. Start API and require readiness
   before starting the other services.
4. Install the complete 22-file build in the stable deployment directory and use
   Chrome's ordinary Reload with no permission expansion or profile-preference
   edits. Verify runtime heartbeat separately from disk comparison.
5. Reverify the bound account and actual provider PDF. Only then discover and
   process a new eligible job under the one-application standing authorization.
   No repeated Apply after ambiguity; independently reconcile provider history.

Rollback: stop candidate services/verify exits, restore the exact six previous
references and 21 extension files, ordinary same-ID Reload, restart `ee8c591`, and
verify STOPPED queue/health/native identity/history. Preserve the approved binding,
application records and any uncertain-action fences. Do not restore a stale
database backup or replay a submission. Actual candidate cutover/rollback remains
NOT TESTED until installation approval.

## Reproduction and next actions

```sh
.venv/bin/python -m pytest backend/tests/test_naukri_identity.py backend/tests/test_naukri_submission.py backend/tests/test_naukri_profile_sync.py -q
pnpm -C extension exec node --test tests/naukri-queue.test.mjs
pnpm -C extension exec node tests/naukri-execution.browser.mjs
pnpm -C extension exec node tests/naukri-queue.browser.mjs
# Set PROFILE_TEST_DATABASE_URL to the existing disposable localhost fixture only:
.venv/bin/python -m pytest backend/tests/test_reliability_postgres.py -k readiness_live_query -q
pnpm -C frontend typecheck
pnpm -C frontend build
pnpm -C extension build
.venv/bin/python backend/scripts/verify_extension_cutover.py --sha fc91a219d5b824f934bb733eaf20166661e1f08b --extension-dir extension/dist
```

Next owner action is exact-SHA installation review and opening the Naukri profile
page in Profile 8 before switching to another tab. The account question has been
answered and will not be asked again for this binding. Next engineering acceptance
is genuine provider PDF verification, then the first supported new application;
resume replacement/questionnaire integration and recurring/locked/restart evidence
remain open. Only Naukri may become active. Gmail remains READ + CREATE DRAFT only.
No hosted Actions, outreach to the provider, merge or cleanup was performed.
