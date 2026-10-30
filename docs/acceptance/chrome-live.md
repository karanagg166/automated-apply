# Chrome live acceptance: one cycle passed, workload reliability failed

Branch `fix/live-prepare-discovery-20261030`; [PR 48](https://github.com/karanagg166/automated-apply/pull/48),
base `main`. Installed and exercised SHA:
[`48e6c3a2ba7a0283a2e07e79ab2c59ecddd45a14`](https://github.com/karanagg166/automated-apply/commit/48e6c3a2ba7a0283a2e07e79ab2c59ecddd45a14).
Recorded 2026-10-30. This report supersedes any inference that the earlier
[ten-minute background window](reliability-installation-20261030.md) established
stability under native command workload. **Stage 1 remains FAIL under workload;
Stage 2 is incomplete.**

## Actual Mac evidence

The selected existing Profile 8 extension was retained in place. Its 17 built
files match the approved candidate byte-for-byte. No Chrome preference edits,
permission changes, profile switching, new identity or extension installation
were required. The stale heartbeat later recovered. The cause of the delay after
the Mac reboot was not proven; a working heartbeat is not itself a DOM PASS.

With no in-flight commands and the acceptance task paused, the approved API and
execution worker were gracefully stopped and restarted at the same source SHA.
Readiness returned HTTP 200 in 1.437s. Nine post-restart HTTP checks passed,
including three readiness requests in 1.102, 1.103 and 1.122s. An actual framed
native-host request and independent database history comparison also passed.
This was a graceful restart, not an unexpected-crash test.

One new real **Open → Prepare** cycle then completed through the selected Chrome
extension and native host against the previously approved job page. The helper
used fresh command request IDs, preserved prior terminal commands, and reconciled
the same profile binding, browser session, tab/window, application identity and
packet revision between Open and Prepare. Observed command admission-to-completion
times were **65.029s Open** and **99.559s Prepare**, including alarm/polling delay.
The complete helper run took **239.075s**, including setup, task reads and final
Pause. These times are observations, not browser-only execution timings.

Prepare saved exactly one new read-only plan, accurately labeled `NEEDS_INPUT`,
with **zero fields, zero actions, zero approved fields and no fill authorization**.
The page did not provide a verified application form. A completed read-only DOM
inspection does not establish that a form can be filled or that an application
was submitted. The existing application identity was reused; an independent
before/after count of the application-packet table was not captured.

The task was paused after the cycle. No uncertain command was replayed. Both new
commands completed; old terminal command values and selected binding were
unchanged. Four pre-existing non-target Chrome tabs retained their IDs and URL
hashes, and the new task tab was separately identifiable. That read-only Apple
Events comparison began after command admission and before the observed new tab;
it records URL/presence, not DOM equality or unrelated page background traffic.
No raw tab URL, title, page content or browser credential was retained by that
comparison.

## Representative workload failure

The HTTP-only monitor ran alongside this real cycle. It did not open its own
database connection. It recorded **71 complete samples** from 10:31:28 to the
last sample timestamp in the accompanying JSON, then was deliberately stopped
after the cycle and task Pause to avoid continuing unnecessary failing workload.
It had originally been bounded to 90 samples; no 90-sample completion is claimed.

| Endpoint | Result | Mean / maximum seconds |
| --- | --- | --- |
| `/health` | 71/71 HTTP 200 | 0.0146 / 0.1173 |
| `/ready` | 62 HTTP 200; **9 HTTP 503** | 2.5460 / 5.9354 |
| Profile status | 70 HTTP 200; **1 observer ReadTimeout** | 4.1316 / 12.0034 |

The API log contains **nine readiness errors**, all classified `probe_timeout`,
in the matching workload window. A separate database snapshot showed one session
each for API, execution and Telegram plus the acceptance helper and temporary
audit (5/5 during that audit). No connection-limit error was observed in this
cycle. The audit then closed its connection. The readiness failures occurred
without a full-time DB observer and cannot be attributed to that earlier
observer-overlap mistake.

The installed API uses its single session pool slot for both business requests
and live readiness queries. Valid command/task transactions and status requests
hold that slot for multiple remote SQL round trips; a readiness request can spend
its entire five-second deadline waiting in that same queue. Background monitoring
alone did not reproduce this. The separate pool-occupancy regression described
below establishes the queue mechanism in an isolated real PostgreSQL fixture.

The profile monitor's 12-second timeout is retained as a failure; it was not
silently retried or relabeled as a successful product response. Its request may
have continued server-side. A later status read passed, but that does not erase
the observed latency failure.

## Status matrix

| Requirement | Status | Scope / next action |
| --- | --- | --- |
| Same selected Profile 8 and installed extension identity | PASS | Existing installation retained; exact build-content comparison |
| First real Open → Prepare after backend/worker restart | PASS | Two terminal commands; one persisted zero-field read-only plan |
| Correct native/task/tab/window/session binding | PASS for this cycle | IDs/revisions reconciled privately; historical terminal values preserved |
| Three consecutive successful cycles on a reliable release | NOT TESTED to completion | One completed; further cycles held for readiness correction |
| No duplicate read-only plan | PASS for this cycle | Exactly one new plan for the successful Prepare |
| No duplicate application packet | NOT TESTED by table count | Pre-existing application identity retained; do not infer a count from plans |
| Unrelated tabs retained | PASS for observed IDs/URLs | Four pre-existing tabs unchanged; no DOM-content claim |
| Graceful API/worker restart recovery | PASS for observed checks/cycle | Independent native and DB comparison; no crash claim |
| Unexpected crash recovery | NOT TESTED on this release | Still required after reliability correction |
| Readiness under real native workload | FAIL | Nine classified probe timeouts / HTTP 503s |
| Profile-status latency under workload | FAIL for observer deadline | One 12-second ReadTimeout; other samples passed |
| Awake, locked-screen DOM cycle | NOT TESTED | Must observe actual locked interval and task completion |
| Stop/Pause during new workload | NOT TESTED in this cycle | Final task Pause passed; concurrent Stop acceptance remains pending |
| Real field filling | NOT TESTED | Specific field/value/origin authorization still required |
| Employer submission / independent receipt | BLOCKED | No authorized supported channel established; zero submissions claimed |

## Follow-up correction and release gate

The development follow-up reserves one API-only readiness pool slot, with pool
size one and zero overflow. Concurrent readiness callers share only an in-flight
live observation; no successful result is cached across probes. The complete
startup audit and its exact database target pin remain required. Query timeouts,
TLS/grant/identity checks and unknown-command outcomes are unchanged.

This is isolation of probe traffic, not a general worker pool increase. Three
runtime session slots plus one dedicated probe slot total four, leaving one
operator/acceptance slot within the existing role limit of five. A disposable
five-slot-role test verifies that budget and explicitly rejects a sixth connection.
Monitoring during a cycle must remain HTTP-only; concurrent additional DB tools
would consume the reserved operator slot. Its actual production behavior still
requires exact-SHA review, approval and installed workload verification.

The first follow-up local regression run passed 344 backend tests in 36.13s.
The expanded disposable PostgreSQL run passed **7 tests in 2.44s**, including eight
concurrent successful readiness calls while an ordinary command connection was
occupied, plus the real five-slot role budget. A final safety subset passed
103 tests in 10.08s. Final candidate identity and consolidated counts will be
published in the reliability report before requesting another installation.
These are fixtures, not a new installed PASS.

Sanitized metrics:
[chrome-workload-metrics-20261030.json](chrome-workload-metrics-20261030.json).
Private evidence is in `reliability-upgrade-20261030T101237Z`: `cycle-1`, `restart`,
`verify-restart`, `native-health-restart`, `monitor-native`, URL-hash snapshots,
the scoped session audit, and the monitor stop receipt. No Gmail content, PII,
resume, raw private log, browser secret or screenshot is published here.

Reproduction uses the existing approved native command mailbox, not a direct
browser driver or private platform API. Review the [prior installation
commands](reliability-installation-20261030.md#validation-scope-and-reproduction)
and run only one bounded HTTP monitor alongside one authorized cycle. The new
regressions run with:

```sh
.venv/bin/python -m pytest backend/tests/test_reliability.py \
  backend/tests/test_operational_health.py backend/tests/test_live_prepare_recovery.py \
  backend/tests/test_database_safety.py -q
# Requires an explicitly selected disposable localhost PROFILE_TEST_DATABASE_URL.
.venv/bin/python -m pytest backend/tests/test_reliability_postgres.py -q -s
```

No additional source poller, employer action, merge, hosted CI, cleanup or new
production source installation was performed while investigating this failure.
