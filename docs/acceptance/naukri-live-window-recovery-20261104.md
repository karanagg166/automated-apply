# Installed browser-window recovery — Naukri OPEN

[PR #48](https://github.com/karanagg166/automated-apply/pull/48), branch
`fix/live-prepare-discovery-20261030`. Exact installed API/extension candidate:
[`2c9d4815f011db27b5dcc7f092f927b50f790095`](https://github.com/karanagg166/automated-apply/commit/2c9d4815f011db27b5dcc7f092f927b50f790095),
including implementation0c2c1bc. Extension1.3.24 retains the same ID. Times below
are November3 UTC (November4 IST for events after18:30 UTC).

## Problem and behavior

The previous browser connection stopped before sending a heartbeat when its
profile had no normal window. The selected binding could remain offline despite
healthy backend/Telegram heartbeats. Chrome retained Profile8's registration;
that metadata alone did not prove whether its worker was loaded.

The new extension authenticates a windowless heartbeat. The server keeps its
public browser status OFFLINE and refuses job dispatch until a real window is
bound. Only the selected approved account, running Naukri policy, enabled global
execution and command consent permit an inactive blank window. Stop/OFF,
unapproved/unselected bindings and bad credentials deny recovery. A second
heartbeat binds the actual window before work. Recovery is serialized and bounded
to one creation per heartbeat; an older server cannot accidentally dispatch work
from a windowless profile.

The manifest adds only Chrome's documented `background` lifecycle permission;
the exact build permission allowlist was updated accordingly. Host access and the
stable key remain unchanged. Chrome documents this permission's background
lifecycle and inactive window creation in its
[permission reference](https://developer.chrome.com/docs/extensions/reference/permissions-list)
and [windows API](https://developer.chrome.com/docs/extensions/reference/api/windows).
These documents do not establish Mac sleep, explicit Quit, OS-startup or locked
window-creation acceptance for this installation.

## Relevant verification and build

- 109 backend tests passed in11.92s in source; the independent0c2c1bc candidate
 passed the same109 in13.02s. These counts overlap.
- 49 targeted extension tests passed in0.162s, including existing queue guards.
- Two isolated Chromium cases passed in2.90s: denied policy created nothing;
 allowed policy created an inactive blank window and preserved the existing
 window/tab selection. There were0 external/provider requests.
- Ruff E9/F/I, formatting/diff checks, dependency consistency and stable-ID build
 checks passed. Unchanged frontend/questionnaire suites were not repeated.

The initial browser harness attached to an unrelated isolated extension worker;
selecting the fixture worker by its exact URL corrected the harness. This was not
a successful product test until the corrected cases passed. The first package
build correctly rejected the new permission because its exact allowlist had not
yet been updated. That candidate and its failure remain retained. Final2c9d481
changes only that build allowlist from0c2c1bc; all backend, extension and test-driver
bytes were independently compared equal. Its own environment/dependency check
and24-file build passed. The unchanged109/49/2 checks were reused by verified
source identity instead of repeated merely to relabel the package SHA.

## Actual installation and preservation

Profile8 reconnected with a fresh heartbeat before replacement. API replacement
used **STOP110**, preserving1,608 records. Startup completed18:33:49; API
verification passed18:34:06: readiness200, frontend login200, profile5, approved
binding1, profile-sync configuration and protected files unchanged. The19.091s
Stop-plus-follow-up-snapshot time is not isolated Stop endpoint latency.

At18:34:23, the ordinary native maintenance path created one owned inactive
extension-manager tab while preserving front-window/active-tab snapshots.
Extension reload verified1.3.24 and all24 exact files, stable ID/path, fresh native
heartbeat, readiness200, frontend200 and unchanged1,608 records at18:35:45.
No owner window/tab was activated; no keyboard or clipboard was used.

Frontend/native remain414a260; execution/Telegram remain2ceea5e. Exact previous
API0e75386 and extension1.3.23/0c8b1d7 bytes, plists, protected-file hashes and
immutable runtimes are retained. Prepared and executed rollback inventories are
private. Rollback keeps STOP, unloads the new API, restores its exact prior plist
and extension bytes, performs ordinary same-ID reload only in an owned inactive
manager, and checks readiness/account/profile/policy/data before resuming.
It never restores an old database snapshot or replays a Save/Apply. No rollback
was required, and no historical release or failed candidate was deleted.

## Actual Mac Stop/Start recovery

The available Profile8 setup window contained only its neutral blank setup tab
and our inactive manager. It was behind two working Chrome windows. An atomic
read-and-close guard required those exact IDs, neutral URLs, tab count and an
unfocused setup window; changed/personal content would refuse the test.

- 18:38:20: closed only that neutral setup window under STOP110.
- 18:38:27 and18:38:57: two genuine new windowless extension heartbeats arrived.
 The public profile stayed OFFLINE and no window reopened while stopped.
- 18:39:03: independently verified unchanged1,608 records and unchanged front
 window/active tabs in both working Chrome windows.
- 18:39:07: restored the identical policy as **RUN111**, SUPERVISED lifetime
 allowance1/hour1.
- 18:39:35: a new inactive background window was observed with the same approved
 binding and browser session, fresh native heartbeat and unchanged working
 Chrome window/tab selections. No owner reopen, popup or button was needed.

This proves a real last-setup-window close and policy-controlled recovery on this
awake, unlocked Mac. It does not prove recovery after a full Chrome Quit, Mac
restart/sleep, locked window creation or an uncertain application submission.

## Real processing after recovery

The genuine discovery cycle18:39:42–18:40:00 added6 new identities without an
error. At18:41:01 the consumer had polled18:40:52 and the queue held1,614 records:
1,042 SKIPPED,528 NEEDS_INPUT,43 DISCOVERED and1 historical receipt. There were
**0 admitted Apply and0 new verified submissions**. PostgreSQL showed4 sessions,
0 lock waiters and1 idle transaction in this sample; throughput/connection
contention is not declared fully resolved.

At18:41:09 a retained-facts diagnostic covered1,477 listings and found0 fully
eligible. Five otherwise passing records still had unsupported skills and/or
target-role mismatches. No skills or missing personal facts were invented.
The once-asked lower-bound applicant-count decision remains pending.

A second genuine discovery cycle18:44:59–18:45:13 completed without an error
and added0 new identities; the durable total remained1,614. At18:46:12 a fresh
provider profile document in the recovered browser independently reverified the
existing skills Save as SYNC_VERIFIED and the actual downloaded resume as
MATCHED_PDF_BYTES (100,198 bytes). The old Save intent was reconciled, not replayed.
At18:46:26 the queue remained RUN111 with0 admitted Apply and0 new receipts.
These are two observed discovery cycles and a real PDF/profile check, not
recurring application acceptance.

| Acceptance item | Result | Evidence / remaining limit |
| --- | --- | --- |
| Recovery authorization/queue guards | PASS |109 backend/49 extension targeted regressions; explicit denials |
| Inactive window API behavior | PASS |2 isolated Chromium cases;0 provider requests |
| Actual exact API/extension installation | PASS |STOP110;24 files; same ID; readiness and protected state verified |
| Actual Stop denies window resurrection | PASS |2 new windowless native heartbeats; no reopen;1,608 records unchanged |
| Actual Start recovers browser without owner focus change | PASS |New inactive window; same binding/session; both working Chrome windows preserved |
| Real discovery after recovery | PASS |6 new identities; fresh consumer polling |
| Actual post-recovery saved profile/PDF | PASS |Fresh18:46:12 document;100,198 matching PDF bytes; previous Save independently reverified |
| First new application / independent receipt | BLOCKED |0 admitted Apply;0 new verified submissions |
| Recurring AUTOMATIC / full restart / locked application | NOT TESTED |First receipt and critical application checks still required |

Reproduction of isolated checks:

```sh
.venv/bin/python -m pytest backend/tests/test_chrome_window_recovery.py backend/tests/test_chrome_profiles.py backend/tests/test_application_queue.py backend/tests/test_naukri_background_queue.py -q
node --test extension/tests/chrome-window-recovery.test.mjs extension/tests/chrome-command-lease.test.mjs extension/tests/naukri-queue.test.mjs
node extension/tests/chrome-window-recovery.browser.mjs
pnpm -C extension build
```

Repeat the Mac test only on an owned neutral setup window, with exact contents
and focus guards; never close personal Chrome windows to exercise recovery.
Score50, age14 days, applicants1000, all company stages, first-receipt gate and
all other safeguards remain intact. Other platforms remain OFF. No QTrino or
uncertain replay, Gmail send, hosted Actions, merge or cleanup occurred.
Next remains the first eligible supported real application and independent receipt,
then bounded recurring and actual restart/locked application acceptance.
