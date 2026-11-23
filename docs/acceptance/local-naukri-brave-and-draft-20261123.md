# Local Naukri Brave and draft acceptance

`feat/rust-agent-runtime` release `0e095bda4702d9b15d7c81b3545d4302c081c188`
is installed locally under `rust-plan-iix3gl7r`. The source batches application
field writes and separates packet creation from retrieval of its full review
data. The saved-job draft retains its selected job, human approval checkpoint,
and disabled application dispatch.

| Check | Result | Evidence |
| --- | --- | --- |
| Exact fixture acceptance | PASS | Clean run `20261123T104844Z-5fbd175c23f94a5889f9a9fe37ed8a47` passed 37 of 37 stages. Stages totaled 2,938.800 seconds. Eight focused PostgreSQL checks also passed before the combined run. |
| Local installation | PASS | Exact runtime and dashboard took over their loopback listeners. The focus and retained data fingerprints matched. Rollback inventory `rust-preinstall-pqbxseh3` was verified. |
| Live new selected-job draft | PASS after readback | On a different saved Naukri job from the previously timed-out run, one new packet was created. The run reached `waiting_approval`, the inspected packet matched the selected job and revision, and it used zero model calls. All prior packet hashes matched independently. |
| Transient verification failure | FAIL, recovered | The scripted check returned HTTP 503 and left the review coordinator running. Independent readback found the exact admitted run waiting for approval with no lease. A revision-checked STOP restored the coordinator, and subsequent readback verified both controls stopped. The original run was reconciled without creating a second run. |
| Existing Brave tab and account | PASS | The signed-in account and portal résumé matched the approved account and canonical PDF. The new fixed Brave selection and archived Chrome pin were read back. The owner separately approved the Naukri account link, which was confirmed through the authenticated local API. |
| Live supervised submission | BLOCKED | Eight distinct readable listings had no applicant upper bound. The live junior search returned 20 links and supplied two of those eight observations. Two other pages redirected to search. The under-1,000 rule holds listings with an unknown upper bound for review. Three prior admissions remain quarantined and one supervised admission remains available. |
| LaunchAgent reboot persistence | NOT TESTED | The verified installation uses the local service pair. The separate macOS Desktop access and reboot check remain pending. |

The original timed-out draft remains recorded. This release created one
review packet, while the application queue stayed stopped and no Apply
admission or strict worker receipt was produced. Unattended submission and
a controlled end-to-end latency comparison remain untested.

```sh
uv run --no-project python scripts/run_acceptance.py --run --keep-going
git diff --check
```

Raw account, packet, verification, and browser evidence is retained in ignored
local storage. This report and the implementation remain local.
