# Local supervised queue priority acceptance

Release `258be9cab6b23104b4a4e38c931ce9aca7912a3e` is installed on the Mac under
`rust-plan-tnjvlg1e`. In supervised mode the worker claims existing application
reads before routine profile sync and search. The MCP browser status now
reports whether the selected Brave profile is connected, account-bound, and
accepting commands.

| Check | Result | Evidence |
| --- | --- | --- |
| Combined local acceptance | PASS | Clean run `20261123T142042Z-ea73156ed0ab409c93e281571ec969f8` passed all 37 stages. This includes 31 Brave dashboard cases and 48 backend browser cases. The recorded Brave stage duration includes the wait for the unlocked Mac. |
| Native queue priority | PASS, fixture | All 13 focused PostgreSQL cases passed. The new regression confirms that a saved listing receives the lane while profile sync and search are due. The original-form lease, quota, quarantine, and first strict receipt checks also passed. |
| Installation preflight | PASS after correction | A stale queue revision assertion stopped the first cutover before service replacement. The corrected guard compared the current STOP revisions against retained state before the restart and verified them again while the services were quiesced. |
| Guarded local restart | PASS, live | Queue revision 166, legacy preparation revision 102, 3,094 jobs, 36 packets, three reservations, and three quarantines matched before and after. The rollback inventory and macOS focus guards passed. |
| Brave readiness and account | PASS, live | The installed MCP read reported the selected Brave profile connected and account-bound. The exact portal account and current uploaded résumé matched the saved identity and canonical version 5 PDF. The existing tab was reused. |
| Fresh listing availability | BLOCKED, live | The previous Backend Developer listing no longer shows an applicant upper bound. In 18 distinct reviews, 17 lacked a reliable upper bound and the remaining bounded result was titled as an internship. The existing rule still requires an upper bound below 1,000. |
| Supervised worker eligibility | PASS, live | The installed broker claimed application inspections ahead of routine profile sync and search. After read-lease expirations it completed inspection of the saved Backend Developer listing and put it in Needs Input with `applicant_count_requires_review`. |
| Supervised application receipt | BLOCKED, live | The supervised window returned to `STOPPED` revision 168 with zero Apply admissions, three reservations and three historical quarantines. The first strict worker receipt and unattended operation remain pending. The temporary browser command setting was restored to disabled and the existing tab returned to the candidate profile. |
| macOS LaunchAgent Desktop access | PASS, live | Four one-shot probes ran the previous and current runtime and dashboard definitions through launchd. Both runtime probes matched stopped queue revision 168 and legacy preparation revision 103. |
| macOS LaunchAgent startup | PASS, partial live check | Both managed processes started and authenticated runtime health, readiness, and the dashboard login returned HTTP 200. A stale queue revision assertion in the standalone smoke check caused rollback and was corrected. |
| macOS LaunchAgent persistence | BLOCKED, live | Subsequent guarded adoptions detected visible window changes during shutdown or activation and restored the same release in direct-process mode. Exact retained application fingerprints matched before and after both rollbacks. Managed startup at login still needs a complete cutover. |
| PostgreSQL capacity after rollback | BLOCKED, live | Initial rollback readiness returned HTTP 200. A later probe returned HTTP 503 and a direct read-only PostgreSQL connection was refused with SQLSTATE `53300`. The local listeners remain available. An inventory found two connections from the current runtime to the configured database and no other local process connected to that peer. Server-side session ownership could not be verified during the capacity failure. |

The combined gate and local installation used the exact accepted commit. The
raw browser and runtime observations are stored privately on the Mac.
A temporary extension diagnostic was attached during the live inspection and
detached afterward. It captured no read error, and its presence limits this
observation to the eligibility decision. The next managed cutover requires
healthy database readiness and a stable macOS window snapshot.
