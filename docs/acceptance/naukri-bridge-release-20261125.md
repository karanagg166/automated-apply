# Naukri bridge release acceptance

## Prepared application continuation cutover

Combined run `20261124T235750Z-6697db7e6f57426688ffb70c5084b74a` passed
all 37 stages on clean branch `feat/rust-agent-runtime` at
`cd3f7d16b7beaadea978663ffc25358d49aa881b`. This includes 1,105 PostgreSQL
cases, 444 Rust workspace cases, 3,433 Python backend passes with one skip,
422 frontend unit tests, 421 extension unit tests, 26 extension browser
fixture groups and 48 backend browser cases. The prepared-resume regression
passed on the corrected fixture. All provider interactions in this gate
used fixtures.

| Check | Status | Actual Mac evidence |
| --- | --- | --- |
| Managed runtime, dashboard and native-host cutover | PASS | Plan `rust-plan-m6op23mi` passed all four Desktop access probes. Startup reached exact listener and HTTP readiness in 12.346 seconds. All 16 readback checks returned their expected status. Focus was preserved and rollback inventory `rust-preinstall-ytkfvy8r` was retained. |
| Stop controls and retained data | PASS | The queue and preparation stayed stopped at revisions 174 and 106. The cutover retained 3,096 jobs, 38 packets, three previous reservations, three quarantines and zero work in flight. |
| Exact Brave package and profile restoration | PASS | Developer mode and the project extension were re-enabled before cutover. The launcher restored the dedicated profile and one inactive Naukri tab. All six packaged modules match the release. |
| Exact running Brave modules | BLOCKED | Five of six running modules match after restart. The running `naukri-queue.js` still differs. The console reported a locked session during the stopped reload preflight, so no reload was dispatched. |
| Fresh canonical PDF check | PENDING | The previous release verified the account but timed out observing the expected PDF from the Download control. Repeat the read using the restored exact candidate worker before considering Apply. |
| Live supervised application and strict receipt | PENDING | The selected work remains paused at revision 36 with its existing packet, zero new admission and no live form or dispatch evidence. The selected scope and recurring submission remain off. |

The private recovery waits for an unlocked session, checks STOP and the
dedicated profile again, requests at most one ordinary extension reload, and
verifies the running modules independently afterward. Reproduce the combined
gate with `uv run --no-project python scripts/run_acceptance.py --run --keep-going`.

## Earlier bridge release and incident

The combined fixture gate passed for all 37 stages on clean branch `feat/rust-agent-runtime` at `0b3fd4087b7d460520c8b520a80afdc1036d8303`. The managed Mac installation activated that runtime and native bridge. Brave's configured bundle and its packaged resources matched the release. Subsequent inspection found five loaded service-worker modules executing older code. The release closes timed-out native heartbeat ports and retries Naukri polls after confirmed rollback of a pre-dispatch lock or serialization failure. [Reliability changes and prior live evidence](naukri-always-on-20261124.md)

| Check | Status | Evidence |
| --- | --- | --- |
| Combined fixture gate | PASS | Backend 3,433 passed and 1 skipped. Rust workspace 444 passed, and Rust PostgreSQL 1,102 passed. Frontend unit tests 422 passed. Extension unit tests 410 passed. |
| Browser and stack fixtures | PASS | Frontend core E2E 22 passed, browser E2E 31, cutover E2E 1, extension E2E 1, and Naukri E2E 2. Backend browser E2E 48 passed. The extension browser gate passed 26 fixture groups, and the extension stack passed 23 named cases. |
| Managed launchd startup | PASS | Readiness took 12.379 seconds after activation. Health, authenticated readiness, and frontend login returned HTTP 200. Unauthenticated protected reads returned HTTP 401. Local plan `rust-plan-m9dktwyz` used rollback snapshot `rust-preinstall-2w4ap86t` and passed all four macOS access probes. |
| Dedicated Brave restoration | PASS | Brave restored three tabs, including exactly one Naukri tab. Readback showed one ordinary dedicated window with a neutral active tab and the previous profile binding. The refresh preserved other desktop windows. |
| STOP and data retention | PASS | The execution queue stayed STOPPED at revision 170, preparation at revision 104, and Rust control at revision 9. Readback retained 3,095 jobs, 37 packets, three historical reservations, and three quarantines, with zero in flight. |
| 24-hour read-only observation | INCOMPLETE | The release was replaced after 8.49 hours and 148 samples. The worker was online in 145 samples. Through 04:31 IST, 112 of 114 samples returned HTTP 200 for all six local checks. |
| Live supervised inspection | PASS | The broker rejected the Python Developer listing at the saved title gate and restored STOP at revision 172. A second one-listing window at revision 173 passed eligibility and prepared a Backend Developer application packet. |
| Live Naukri submission | PENDING | The read-only résumé step lost its lease. The operator stopped the scope at revision 174 after detecting older loaded Brave modules. The run admitted zero Apply actions and recorded zero strict receipts. Three historical reservations and quarantines remain. One admission is still available. |
| Recurring live submission | BLOCKED | A strict worker receipt and verified provider permission remain pending. |

Run the local fixture gate from the repository root with `uv run --no-project python scripts/run_acceptance.py --run`. The measured backend, Rust PostgreSQL, and extension browser stages took 766.429, 268.223, and 494.477 seconds respectively. The browser fixtures used isolated profiles and fictional provider pages. The managed installation and observation used the actual Mac and dedicated profile.

The post-STOP read confirmed zero active writes and cleared the one-listing
scope. Browser commands were disabled and the existing profile tab was
returned to Naukri. The verifier compared the six exact executing modules
through the dedicated worker with the immutable local artifacts. All six
packaged URLs returned correct bytes. The five older executing modules
included the heartbeat bridge, the queue, and questionnaire handling. The
initial launcher had compared a packaged URL and process flag. Require this
executing-module check at release acceptance and before the next supervised
window. The browser read failure's precise error code was unconfirmed.

The stopped-profile reload returned an acknowledgement and Brave recorded
disable reason `16777216` for the unpacked extension. Chromium assigns that
reason to a developer extension when Developer mode is off. This fault is
visible through the ordinary extension settings. The guarded browser-control
attempts left Developer mode off, with the project card disabled. The existing
neutral tab was reused for the Extensions page so the owner can use its
visible Developer mode switch. The queue remains stopped during recovery.
[Chromium disable reason](https://chromium.googlesource.com/chromium/src.git/+/HEAD/extensions/browser/disable_reason.h#64)

Local source `a42a9de` adds an explicit revision-checked continuation for
prepared work interrupted during profile inspection. It reuses the same
packet, checks for an empty admission ledger and absence of form or submission
evidence, and returns to fresh account and résumé inspection followed by fresh
listing and application-status checks. Scoped polling leaves unrelated
quarantines and expired leases untouched. A disposable PostgreSQL regression
fixture covers that path.

Combined run `20261124T230657Z-2117d6fd6d4d4fdfacafa6837bef4b18` finished on
clean commit `057b33e03870359557f1f58336ed02754c5a75cb` with 36 of 37 stages
passing. The PostgreSQL run passed 1,104 tests. The new regression passed
through CLI resume and failed at the native poll because its disposable
schema lacked `agent_policies`. With the fixture table present, the targeted
test passed the poll, read-only profile claim, and checks that all three
quarantines, reservations, and an unrelated lease were untouched. The saved
release is still active. The corrected revision requires a clean combined
pass and the dedicated Brave worker before local activation.

## Application execution rules

The workflow discovers, ranks, and prepares a job against verified candidate
facts. The broker is the single authority for Apply. It checks the saved
policy, exact listing, profile, résumé, queue revision, and browser lease, then
records the admission and quota reservation before a provider write. A
receipt must bind the exact admitted requisition to durable provider evidence.
Ambiguous outcomes remain quarantined for read-only reconciliation.

For an early browser failure, cleanup requires a confirmed broker response
showing that the exact leased attempt ended before admission. An unavailable
response preserves the tab and evidence. Additional portal adapters can use
the same broker rule and supply their own provider permission, form, and
receipt checks.

Local source commit `3d77ee1de6b0b54e514ef9ba327f541d2ca0b986` adds that
confirmed pre-admission cleanup. The broker attests that the exact apply lease
ended with zero admissions and no form, then the extension checks the tab and
lease identity before cleanup. All 421 extension tests and four targeted
disposable PostgreSQL cases passed. This change awaits the combined gate and
local installation.

Local source commit `b8d1dc0` extends the existing native retry to finish
and abandon reports after a confirmed pre-dispatch fence rollback. A lost
response or unconfirmed commit stays fenced. Two disposable PostgreSQL tests
and all 16 native transport tests passed. This change also awaits combined
validation and installation.

The inspected Python Developer role met the saved experience band and the
listing had five exact verified skills. The score exceeded the threshold.
The admission policy still requires the advertised title to match a saved
target role. This listing's title lacked that match, and the durable broker
record used the combined preference and skills reason. The saved role list
also lacks the owner's stated agentic AI and GenAI titles. Keep role intent
separate from verified past experience.

For a supervised listing preview, use the same eligibility evaluator and
effective policy as the broker. The selected requisition, trusted listing
observation, and confirmed profile and policy revisions must correspond.
Report the role, skill, employment, remote, and experience checks separately.
When trusted listing facts are missing or stale, report the evidence needed.
The current Jobs preview shows relevance only. A preview result cannot grant
admission, and live inspection and pre-dispatch checks still apply.
