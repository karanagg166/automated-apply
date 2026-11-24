# One approved Naukri listing

The owner approved one remaining supervised Apply for an otherwise eligible
Naukri listing showing `100+` applicants. Release
`1afc1b4cfd64c249a048a666805832f8ffb9bdb5` binds the exception to one queue
item, expires it after 15 minutes, and clears it on Stop, Pause, or a policy
change. The existing under-1,000 rule remains saved. The broker checks the
exact applicant observation again during dispatch and retains the existing
identity, résumé, eligibility, quota, history, and receipt checks.

| Check | Result | Evidence |
| --- | --- | --- |
| Rust and isolated PostgreSQL | PASS | The unit test verified range, target, and expiry. All 1,101 PostgreSQL tests passed. The new native test started the scope through the local CLI, verified only the selected listing was claimed, verified the unrelated item was untouched, and confirmed Stop cleared the scope and revoked the lease. |
| Combined fixture coverage | PASS after targeted retry | The original run `20261123T232856Z-63b284c7e426443d92c89f41e5771843` passed 36 stages. A Brave worker closed during the last case group. The isolated retry passed 32 Naukri queue cases. Record `20261124T012118Z-579b8a9be5754f5d84c5b81916cf4e02` includes all 37 passing stages on the same clean commit, the original failure, the retry output, and the identical artifact inventory. |
| Managed activation during screen lock | FAIL, recovered | The candidate processes did not bind their listeners before the deadline. The managed rollback encountered the same startup condition. The reviewed previous release was restored in direct mode, with exact retained fingerprints and local readiness verified. |
| Guarded direct upgrade | PASS, live | Plan `rust-plan-e_zgm9qh` then installed the validated candidate in direct mode. Exact retained fingerprints matched for 3,094 jobs, 36 packets, three reservations, three quarantines, no in-flight applications, queue STOP revision 168, and legacy STOP revision 103. Dashboard and authenticated readiness passed. |
| Scoped production submission | BLOCKED, live | The Mac was subsequently unlocked. The single existing Naukri tab remained inactive in the selected Brave profile. The native profile stayed offline with `backend_timeout`. macOS logged Desktop-folder access checks for the bridge executables, and a process sample showed the bridge waiting in the dynamic loader before startup. The queue remained stopped at revision 168. Fresh account and résumé verification could not complete, and zero new applications were admitted. |
| Managed startup for this release | NOT TESTED, unlocked | The release is active in direct mode. The reviewed LaunchAgent definitions and previous rollback archive are retained locally. |

All test listings used fictional fixtures. The live check verified release,
readiness, and retained state. A strict worker receipt is still required for
recurring submissions.

The next readback found the dedicated Brave process running without windows
or tabs. The launcher preflight passed on the active runtime and verified the
windowless browser. The live queue readback confirmed STOP revision 168,
three reservations, three quarantines, no leases, and zero worker receipts.
The owner can open the existing profile with
`.local/browser-profiles/open-brave-naukri-automation.command` before the
connector, account, and résumé are verified again.
