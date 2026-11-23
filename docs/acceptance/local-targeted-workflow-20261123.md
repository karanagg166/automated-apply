# Local selected-job workflow acceptance

The selected-job review release `85aa361af99636f18f6bc67cd0719b5b58224ca1`
is installed on the Mac under `rust-plan-b4d8atfr`. The owner job preview
links to a draft review whose search, matching, preparation, and approval
are bound to the selected saved job. The general saved-job workflow remains
available.

| Check | Result | Evidence |
| --- | --- | --- |
| Exact acceptance | PASS, fixture | Powered retry `20261123T092437Z-5a176413d76149a09e9584f90548b80a` passed all 37 stages. The source was clean at both ends and stage durations totaled 2,398.453 seconds. |
| Exact job selection | PASS, fixture | Tests verified request-key conflicts when the selected job changes, packet creation for the selected job, and an empty result when the selection is unavailable. The frontend requires a deliberate click before creating the run. |
| Initial installation attempt | BLOCKED | The single console user's session lock and global console lock disagreed. The focus guard stopped before service replacement. |
| Reviewed local installation | PASS, live | After the owner unlocked the Mac, the exact staged runtime and dashboard took the loopback listeners. Focus and retained data checks passed. The rollback is `rust-preinstall-pqbxseh3`. |
| Live selected Naukri draft | FAIL, live | The original owner-selected run reached `prepare_application` and exceeded the tool deadline. Reconciliation found an `outcome_unknown` run with its lease released, zero packets by its effect key, zero packets for the target, and zero target receipts. The coordinator and application queue were stopped on readback. |
| Retained application state | PASS, live | The running release preserved 3,092 jobs, 35 packets, no application work in flight, three quarantines, and three quota reservations at cutover. |
| First supervised Naukri receipt | BLOCKED, live | The dedicated Brave profile still had zero Naukri tabs on the post-installation read. The fresh account, resume, listing, and receipt checks remain pending. |
| Reboot persistence | PENDING | The release runs as the verified local service pair. The owner-run Desktop access check and LaunchAgent acceptance remain pending. |

The earlier run `20261122T230911Z-ea3f3bbdb6df40bcaec38099e73ed8fd`
passed 32 of 37 stages during repeated battery sleep. The five failed
stages all passed during the powered run. The two reports remain separate.

The factual preview endpoint returned seven fields for the selected job in
11.69 seconds. The live timeout remains recorded against its original run.
The next draft validation will use a separately selected saved job and
confirm its own effect, packet, and protected-state evidence.
