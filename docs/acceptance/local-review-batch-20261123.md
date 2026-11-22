# Local review fixes and release acceptance

The `feat/rust-agent-runtime` release `e04e8ac1b8bad0298a867a31dcb41bb5a3ae9ed4`
is running on the owner’s Mac. The local installer switched the direct
runtime and dashboard from `4dab75e` under plan `rust-plan-f096rp_a`. The
reviewed rollback is `rust-preinstall-pqbxseh3`. The running processes were
identified as `81154` and `81155` and the replacement observer recorded its
first sample as process `81331`.

## Changes

- Discovery intake, post-fetch commit, schedule, and owner HTTP reuse the
  retained connection recovery path. A failed operation remains a failed or
  ambiguous operation. The next request can establish a healthy connection.
- Discovery reads saved references across platforms. Matching ranks a balanced
  set across sources and filters prior and uncertain application evidence
  before limiting candidates. Distinct roles at the same company remain
  eligible. Mailbox expiry comparisons use offset-aware timestamps.
- The extension uses one portal domain list for its session and generic form
  boundaries. YC portal pages are rejected before the generic form bridge
  sends any native message.
- The private login uses native form elements and the existing styles. It
  keeps the owner passphrase flow, error state, and busy indicator.

## Acceptance matrix

| Check | Result | Evidence |
| --- | --- | --- |
| Exact source and release artifacts | PASS | Clean combined run `20261122T205620Z-b724480d1bfe4ff1be2885424fb5f6c7` passed 37 of 37 stages in 2,999.375 seconds. The before and after source stamps matched the installed commit. |
| PostgreSQL application logic | PASS | All 1,098 fixture cases passed, including schedule reconnect after a dead connection, older eligible jobs behind 105 blocked jobs, multi-source ranking, and mailbox expiry offsets. |
| Backend and browser | PASS | 3,433 backend tests passed with one reported skip. All 48 backend browser cases passed. Frontend, Brave extension, and Edge build checks passed in their fixture scopes. |
| Local service cutover | PASS | The exact staged release owned both loopback listeners. Health, authenticated readiness, discovery schedule, worker control, capabilities, Telegram status, and dashboard login returned HTTP 200. Anonymous readiness returned 401 and anonymous dashboard access redirected to login. |
| Retained data and focus | PASS | Before and after fingerprints matched for 3,092 jobs, 35 packets, zero in-flight work, three quarantines, and three budget reservations. Both controls were stopped. macOS focus snapshots matched. |
| Live saved catalog read | PASS | A read-only execution of the final ranking SQL returned 100 candidates across 10 saved sources in 2.79 seconds. No admissions were created. |
| Mobile performance target | FAIL | One headless Edge Lighthouse sample against the running local `/login` measured performance 80, accessibility 100, best practices 100, LCP 776 ms, CLS 0, and total blocking time 876 ms. Login-specific chunks fell from 23,041 to 7,851 gzip bytes against staged `12923ba`. |
| Reboot persistence | PENDING | The active release uses direct local processes. The exact launchd Desktop access probe still needs operator confirmation. |
| First supervised Naukri receipt | BLOCKED | The dedicated profile had zero open tabs at readback. The live saved Naukri catalog had zero unapplied postings from the previous 14 days. Fresh identity, resume, focus, matching, and strict worker receipt evidence remain required. |
| Multi-platform application dispatch | NOT TESTED | The saved review graph reads and ranks multiple sources. Its application-action adapters and live provider receipts remain open acceptance work. |

The first review run failed to compile because it used an unavailable SQLx
derive. A tuple decoder corrected that failure. A subsequent live read-only
probe exposed a repeated scan of application work under a five-second SQL
timeout. The final commit classifies normalized evidence once and was
validated as a separate clean release. The earlier run records are retained.

## Reproduction

From the repository root, run the combined gate on the exact implementation
commit. The gate uses disposable fixtures. The local readiness and browser
checks below read installed state.

```sh
uv run --no-project --python .venv/bin/python python scripts/run_acceptance.py --run --keep-going
.local/browser-profiles/open-brave-naukri-automation.command --check
```

The current owner step is to open the dedicated Naukri window once if it is
closed and leave the existing Naukri tab available for live readback. The
reserve remains one supervised admission at a lifetime cap of four and an
hourly cap of one. Recurring application execution requires the first strict
worker receipt.
