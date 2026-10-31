# Approved fc91 installation and genuine Mac checks — Naukri OPEN

**No new application or receipt.** This report records an actual installed release
and actual service/database/browser checks. It is not recurring-application
acceptance. No fictional test suite was run during this installation continuation.

- Branch/base: `fix/live-prepare-discovery-20261030` → `main`.
- [PR #48](https://github.com/karanagg166/automated-apply/pull/48).
- Exact owner-approved and now installed implementation:
  [`fc91a219d5b824f934bb733eaf20166661e1f08b`](https://github.com/karanagg166/automated-apply/commit/fc91a219d5b824f934bb733eaf20166661e1f08b).
- Installed services/API/frontend/Telegram/execution/native all reference this
  SHA. Profile 8 now displays extension **1.3.4**, stable ID
  `gdjbmkffcpicbpiikcohlmokkmcpipgp`.
- [Candidate validation and complete rollback plan](naukri-account-resume-candidate-20261031.md).
- Previous installed source `ee8c591b382626f657f3e99f2e757c303ec217b0`
  remains intact for rollback. No previous release was deleted.

## Owner authorization and cutover

The owner explicitly approved exact `fc91a219d5b824f934bb733eaf20166661e1f08b`,
same-ID extension 1.3.4 and the prepared local cutover/rollback plan. The queue
was verified **STOPPED revision 4**, with no leased/executing application work or
active Chrome command before stopping services. Four original service PIDs were
verified exited **before any** reference replacement.

The first cutover attempt used an incorrectly short **18-second installer startup
wait**, received connection refusals while API initialization was still in
progress, and rolled back the six references before installing extension files.
The rollback's same short startup observer also expired before the restored API
was available. Subsequent checks proved the restored `ee8c591` API healthy:
health 200 **0.025 s**, readiness 200 **4.044 s**, queue 200 **3.702 s**, STOPPED;
all four plists referenced `ee8c591`. These failed startup observations remain
failures; they are not successful candidate readiness results.

The installer was corrected to allow the existing startup/audit sequence to finish
before readiness evaluation, then retried the **same approved SHA**. No runtime
HTTP/native/database timeout, pool size or role limit was increased. Again all
four original PIDs exited before replacement. Six reviewed references were
installed at **14:16:27 UTC**. API readiness passed at **14:16:47 UTC**, **3.671 s**,
before execution/Telegram/frontend were started. A further ready check passed in
**3.139 s**. The stopped queue and binding revision were verified after cutover.

All **22/22** candidate extension files were deployed to the existing stable
directory; Profile 8's saved path, manifest key, ID, permissions and native allowed
origin were preserved. Chrome's existing Extensions page's ordinary Reload control
was clicked for this exact ID. The page subsequently displayed **1.3.4**, and
the selected authenticated profile heartbeat advanced after reload. A disk
comparison alone is not used as the runtime proof. A full extension Errors-panel
audit was not obtained; no empty-panel claim is made.

A temporary inspection reused only the existing extension setup tab in a
background window, preserving the active tab and front-window IDs, then restored
the Extensions page. Chrome did not expose executable JavaScript on its extension
settings page through AppleScript; that diagnostic returned `missing value` and
was not treated as provider acceptance. No personal tab, clipboard or keyboard
was changed. No new browser/OS permission was granted.

## Actual installed verification

| Check | Result | Genuine evidence / limit |
| --- | --- | --- |
| Six installed references / private configuration | PASS | All match the approved plan; private-env/native-manifest hashes unchanged |
| Four LaunchAgent services | PASS process/startup | API, execution, Telegram and frontend running with no recorded exit in their new launch instances |
| API health | PASS | HTTP 200, **0.027 s** |
| Database readiness | PASS awake samples | Initial 200 **2.321 s**, then **3/3** 200 in **2.606 / 2.356 / 2.313 s** |
| Frontend | PASS login only | Actual `http://127.0.0.1:3000/login` HTTP 200; no full dashboard acceptance claim |
| Native host | PASS | Actual installed wrapper, valid Chrome origin, framed health request exit 0/ok true/correlation matched |
| Selected Profile 8 | PASS connection | CONNECTED, commands enabled, fresh authenticated native heartbeat after Reload |
| Approved account binding | PASS persisted | Revision **1** retained; selected Chrome/candidate binding verified; neither email modified |
| Current canonical PDF | PASS local bytes | Existing confirmed primary PDF decrypted in memory; `%PDF-`, SHA-256 and size verified: **100,198 bytes** |
| Current provider account/PDF | BLOCKED pending background read | Active Naukri owner tab makes worker yield; no fresh portal-email or saved-PDF verification claimed |
| Genuine discovery/matching this release | BLOCKED at browser yield | Queue started PREPARE_ONLY; no fresh candidate cycle yet, historical 20 URLs retained |
| First new real application / independent receipt | NOT TESTED | **0** new submissions, receipts or QTrino replays |
| Bounded AUTOMATIC mode | NOT ACTIVATED | Prerequisites and first genuine success still required |
| Locked browser/restart journey | NOT TESTED | All three new readiness samples were **UNLOCKED**; no locked-screen inference |

The actual database inventory after installation showed **4** same-role sessions
including the temporary operator: one API idle, one execution idle in transaction,
one Telegram idle, one active operator. **No retained readiness session** appeared.
The operator used NullPool and closed after the check. This contrasts with the
previous snapshot's **5** sessions including an idle readiness session and two
API-labelled sessions; these are bounded snapshots, not a long-run capacity test.
The execution transaction's wait type was Client; a prolonged contention diagnosis
was not inferred from this one sample. The earlier locked 3/3 connection-limit
failures remain retained in the previous report.

## Live background handoff

After successful installation checks, the existing queue was started at
**14:20:43 UTC** using the authenticated owner control; HTTP 200 in **2.679 s**.
Naukri remains **PREPARE_ONLY**, `owner_submission_authorized=false`, 300-second
discovery interval; no other platform was activated. The legacy scheduler remains
STOPPED. Starting the queue resumed its prior read-only items: snapshot counts
**14 DISCOVERED, 6 NEEDS_INPUT, 1 SUBMITTED_RECORDED**. The six parser failures and
one historical receipt predate this candidate and were not relabelled as new
observations.

Profile 8 currently has Naukri active in its window. Actual read-only DOM inspection
found `/mnjuser/homepage`, the ordinary Complete profile link to `/mnjuser/profile`,
no visible email node or resume Download control, and no visible challenge. This
is **not** a wrong-account finding and **not** a resume verification. The worker
intentionally yields whenever an owner tab is active on Naukri, so its consumer
poll and profile-sync records have not advanced. No tab was activated or closed
to defeat that boundary. The owner was asked once to switch that window to a
non-Naukri tab; no popup or repeated setup is required.

One actual Stop/Start exercise at **14:25:57 UTC** kept the same PREPARE_ONLY
policy and historical receipt. Stop returned HTTP 200 in **5.992 s**, STOPPED
revision **6**; Start returned HTTP 200 in **4.208 s**, RUNNING revision **7**.
Counts remained 14 DISCOVERED, 6 NEEDS_INPUT and 1 SUBMITTED_RECORDED, with no
leased/executing browser work at admission. The previous installed Stop took
26.05 s under a different workload; the new single sample is an observed
improvement, not a controlled throughput benchmark or a complete responsiveness
PASS. The accompanying slow control trace recorded **8 SQL writes, 15 SQL reads**,
**5.515 s** connection occupancy and **0.146 s** acquisition. A contemporaneous
native request spent **3.773 s** acquiring the API pool. This identifies remaining
remote round trips and serialized API-pool occupancy; no timeout/limit was raised.

Next: once the owner switches tabs, observe the actual background profile read and
Download bytes, run genuine discovery/filter/match, and enable only the already
authorized one-application supervised path after prerequisites pass. Any ambiguous
Apply remains reconciliation-only; QTrino cannot be replayed. Only after a new
independently confirmed receipt and critical checks may bounded AUTOMATIC begin.
Questionnaires, replacement upload and awake/locked/restart acceptance remain open.

## Evidence, reproduction and rollback

Private installation ledgers retain both failed first attempt and successful retry,
original PIDs, queue/profile snapshots, framed native result, post-install readiness
samples and canonical verification. Public evidence contains no account identifiers,
contact details, tokens, resume bytes or private logs. **New fictional test count:
0**; the pinned candidate's earlier exact test counts are in its linked report.
No controlled installed throughput/CPU/RAM or equivalent-workload Stop benchmark
is claimed.

```sh
# Non-mutating installed-source/disk checks:
git -C "$HOME/Library/Application Support/Automated Apply/release-candidates/fc91a219d5b824f934bb733eaf20166661e1f08b" rev-parse HEAD
.venv/bin/python backend/scripts/verify_extension_cutover.py \
  --sha fc91a219d5b824f934bb733eaf20166661e1f08b \
  --extension-dir "$HOME/Library/Application Support/Automated Apply/chrome-extension" \
  --profile-dir "$HOME/Library/Application Support/Google/Chrome/Profile 8"
```

The prepared rollback inventory remains under
`~/Library/Application Support/Automated Apply/installation-plans/naukri-fc91a219d5b824f934bb733eaf20166661e1f08b/`.
Stop/verify candidate process exits before restoring the six previous references
and 21 previous extension files, ordinary same-ID Reload, then start `ee8c591` and
verify STOPPED queue/health/native identity/history. Preserve the sole added
extension file privately if removing it from deployment; do not erase historical
releases, account approval, job records or uncertain-action fences. The first
attempt exercised reference rollback before extension deployment; it did not prove
the full post-extension rollback path.

No merge, release cleanup, Gmail send, other-platform activation, provider outreach
or hosted GitHub Actions was performed. **Naukri remains OPEN.**
