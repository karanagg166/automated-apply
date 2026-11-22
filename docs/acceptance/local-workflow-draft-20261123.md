# Local workflow draft acceptance

The owner-selected **Prepare draft and review** workflow is installed on the
Mac under `rust-plan-h0penzuv`. Release
`1302a549cc2658a2b8d60046012ccbd5a26d5f29` replaced `e04e8ac` on the
loopback listeners. The observed runtime and dashboard PIDs were `96711`
and `96712`. The reviewed rollback is `rust-preinstall-pqbxseh3`.

The workflow ranks saved jobs across sources and prepares or reuses one
application packet with the existing packet service. It binds the packet
review to the run and its verified profile. The dashboard links to the
packet from the approval checkpoint. Ordinary saved review remains a
separate choice. The draft workflow uses deterministic decisions and the
application submission controls retain their own authority.

| Check | Result | Evidence |
| --- | --- | --- |
| Exact combined acceptance | PASS | Clean run `20261122T220420Z-75cdd24b26ce42ed9be4e97348200220` passed 37 of 37 stages. Stage durations totaled 2,982.461 seconds. Both source stamps matched the installed commit. |
| Packet creation and reuse | PASS, fixture | The PostgreSQL regression created one Greenhouse draft, reached approval, reused the same draft on another run, and created zero browser commands, reservations, or submission evidence. All 1,099 PostgreSQL cases passed. |
| Backend, frontend, and browser | PASS, fixture | 3,433 backend tests passed with one skip, all 48 backend browser cases passed, and all 420 frontend unit tests passed. The Brave browser and extension-stack stages passed. |
| Runtime and dashboard | PASS, live | The exact staged release replied on both loopback listeners. The dashboard login, runtime health, authenticated worker status, and Telegram status returned HTTP 200. The worker was online. |
| Owner-selected workflow | PASS, live reuse | One live run inspected an existing Greenhouse packet at its retained revision and reached `waiting_approval`. The draft used zero model calls. The packet remained saved for owner review. |
| Retained state and focus | PASS, live | The cutover focus check passed. Protected fingerprints matched after the live run. The catalog held 3,092 jobs and 35 packets, with zero in-flight application work, three reservations, and three quarantined jobs. Both controls were stopped. |
| Naukri supervised receipt | BLOCKED, live | The dedicated Brave profile had zero Naukri tabs. A date-aware catalog check found 908 unapplied jobs with recent browser-recorded calendar dates. Two of eight sampled listings scored at least 50 and matched a verified skill. Account, resume, current listings, applicant counts, and the receipt still need the existing live checks. |
| macOS reboot persistence | PENDING | The exact running release has valid staged access-probe definitions. The owner-run macOS Desktop consent probe and LaunchAgent acceptance are pending. |

The earlier date check counted the SQL timestamp column. The follow-up
included dates captured from the provider as calendar days and used the
worker's conservative day boundary. The shortlisted Naukri records remain
private and require current portal verification before consideration for the
one remaining supervised admission.

The account-independent continuity archive now also holds 347 recovered
user prompts from 91 older project threads. There are nine full local
transcripts. Seven missing indexed threads yielded no local prompt record.

## Reproduction

```sh
uv run --no-project --python .venv/bin/python python scripts/run_acceptance.py --run --keep-going
.local/browser-profiles/open-brave-naukri-automation.command --check
.local/runtime-recovery-20261120.RyE1Do/check-catalog-desktop-access.command --check
```
