# Naukri bridge release acceptance

The combined fixture gate passed for all 37 stages on clean branch `feat/rust-agent-runtime` at `0b3fd4087b7d460520c8b520a80afdc1036d8303`. The managed Mac installation activated that runtime and native bridge. Brave's configured bundle and its packaged resources matched the release. Subsequent inspection found five loaded service-worker modules executing older code. The release closes timed-out native heartbeat ports and retries Naukri polls after confirmed rollback of a pre-dispatch lock or serialization failure. [Reliability changes and prior live evidence](naukri-always-on-20261124.md)

| Check | Status | Evidence |
| --- | --- | --- |
| Combined fixture gate | PASS | Backend 3,433 passed and 1 skipped. Rust workspace 444 passed, and Rust PostgreSQL 1,102 passed. Frontend unit tests 422 passed. Extension unit tests 410 passed. |
| Browser and stack fixtures | PASS | Frontend core E2E 22 passed, browser E2E 31, cutover E2E 1, extension E2E 1, and Naukri E2E 2. Backend browser E2E 48 passed. The extension browser gate passed 26 fixture groups, and the extension stack passed 23 named cases. |
| Managed launchd startup | PASS | Readiness took 12.379 seconds after activation. Health, authenticated readiness, and frontend login returned HTTP 200. Unauthenticated protected reads returned HTTP 401. Local plan `rust-plan-m9dktwyz` used rollback snapshot `rust-preinstall-2w4ap86t` and passed all four macOS access probes. |
| Dedicated Brave restoration | PASS | Brave restored three tabs, including exactly one Naukri tab. Readback showed one ordinary dedicated window with a neutral active tab and the previous profile binding. The refresh preserved other desktop windows. |
| STOP and data retention | PASS | The execution queue stayed STOPPED at revision 170, preparation at revision 104, and Rust control at revision 9. Readback retained 3,095 jobs, 37 packets, three historical reservations, and three quarantines, with zero in flight. |
| 24-hour read-only observation | IN PROGRESS | Through 04:31 IST on November 25, 112 of 114 samples returned HTTP 200 for all six local checks. Health, readiness, and frontend returned HTTP 200 throughout. One sample had no HTTP result for control, and another had control, browser, and queue HTTP 503s. |
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
fixture covers that path. Combined validation and installation are pending.

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
