# Naukri bridge release acceptance

The combined fixture gate passed for all 37 stages on clean branch `feat/rust-agent-runtime` at `0b3fd4087b7d460520c8b520a80afdc1036d8303`. The managed Mac installation activated that exact release and verified that the runtime, native bridge, and resident Brave extension matched. The release closes timed-out native heartbeat ports and retries Naukri polls only after confirmed rollback of a pre-dispatch lock or serialization failure. [Reliability changes and prior live evidence](naukri-always-on-20261124.md)

| Check | Status | Evidence |
| --- | --- | --- |
| Combined fixture gate | PASS | Backend 3,433 passed and 1 skipped. Rust workspace 444 passed, and Rust PostgreSQL 1,102 passed. Frontend unit tests 422 passed. Extension unit tests 410 passed. |
| Browser and stack fixtures | PASS | Frontend core E2E 22 passed, browser E2E 31, cutover E2E 1, extension E2E 1, and Naukri E2E 2. Backend browser E2E 48 passed. The extension browser gate passed 26 fixture groups, and the extension stack passed 23 named cases. |
| Managed launchd startup | PASS | Readiness took 12.379 seconds after activation. Health, authenticated readiness, and frontend login returned HTTP 200. Unauthenticated protected reads returned HTTP 401. Local plan `rust-plan-m9dktwyz` used rollback snapshot `rust-preinstall-2w4ap86t` and passed all four macOS access probes. |
| Dedicated Brave restoration | PASS | Brave restored three tabs, including exactly one Naukri tab. Readback showed one ordinary dedicated window with a neutral active tab and the previous profile binding. The refresh preserved other desktop windows. |
| STOP and data retention | PASS | The execution queue stayed STOPPED at revision 170, preparation at revision 104, and Rust control at revision 9. Readback retained 3,095 jobs, 37 packets, three historical reservations, and three quarantines, with zero in flight. |
| 24-hour read-only observation | IN PROGRESS | All 93 samples through 03:27 IST on November 25 returned HTTP 200 for six local checks. Every sample recorded zero helpers from the current release. Four samples recorded one helper from another release. The longest sampling interval was about 243 seconds. |
| Live Naukri submission | NOT TESTED | The observation recorded zero confirmed submissions. The queue stayed STOPPED with browser commands disabled and no supervised scope active. The new helper also navigated the retained inactive listing tab to the profile with zero new portal tabs. A strict worker receipt remains pending. |
| Recurring live submission | BLOCKED | A strict worker receipt and verified provider permission remain pending. |

Run the local fixture gate from the repository root with `uv run --no-project python scripts/run_acceptance.py --run`. The measured backend, Rust PostgreSQL, and extension browser stages took 766.429, 268.223, and 494.477 seconds respectively. The browser fixtures used isolated profiles and fictional provider pages. The managed installation and observation used the actual Mac and dedicated profile.

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
