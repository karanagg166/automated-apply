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
| macOS LaunchAgent deployment | PASS, live | After two guarded rollbacks for visible window changes, launchd started the exact release with no detected focus change. Health, readiness, login, all 10 dashboard reads, Jobs, and Startup Explorer returned HTTP 200. Exact retained fingerprints matched for 3,094 jobs, 36 packets, three reservations, three quarantines, and both STOP controls. Both definitions have `RunAtLoad` enabled. A separate login or reboot was not exercised. |
| PostgreSQL capacity after rollback | RECOVERED, live | Initial rollback readiness returned HTTP 200. A later probe returned HTTP 503 and PostgreSQL refused an extra connection with SQLSTATE `53300`. The later read-only cutover preflight succeeded with three existing sessions against a role limit of five. Queue and legacy preparation revisions remained 168 and 103. |
| Fresh Naukri recheck after recovery | PASS, live read | The runtime readiness and worker recovered. The fresh-search helper reused the authenticated local API connection after the role rejected an extra session. In the same inactive Brave tab, eight further Software Engineer and DevOps listings showed `100+` without an upper bound. The Site Reliability Engineer and AI Engineer searches yielded no additional matching links for readback. None of 26 paused items had a recent usable upper bound. The stopped queue and approved account/browser binding revisions matched before and after each search. |
| Brave after managed cutover | PASS, live | The MCP read independently reported the selected profile connected and account-bound with commands disabled. The stopped Naukri preflight passed at revision 168. |

The combined gate and local installation used the exact accepted commit. The
raw browser and runtime observations are stored privately on the Mac.
A temporary extension diagnostic was attached during the live inspection and
detached afterward. It captured no read error, and its presence limits this
observation to the eligibility decision. The first strict receipt is still the
gate for recurring application submission.
