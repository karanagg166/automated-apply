# Real saved PDF verified; recurring discovery running; location correction ready

**Naukri remains OPEN. Zero new applications or receipts.** The owner requested
continuing real automatic filling/submission and continuous operation. This report
separates genuine progress from the remaining installed parser/submission gate.

- Branch/base: `fix/live-prepare-discovery-20261030` → `main`.
- [PR #48](https://github.com/karanagg166/automated-apply/pull/48).
- **Still installed services/frontend/native and extension 1.3.4:**
  [`fc91a219d5b824f934bb733eaf20166661e1f08b`](https://github.com/karanagg166/automated-apply/commit/fc91a219d5b824f934bb733eaf20166661e1f08b).
- **Extension-only correction candidate, 1.3.5, not installed:**
  [`3644b65aa7c2d3707a58b35f64df266807746a6d`](https://github.com/karanagg166/automated-apply/commit/3644b65aa7c2d3707a58b35f64df266807746a6d).
- [Previous actual installation/readiness/Stop evidence](naukri-fc91-installed-live-20261031.md).

## Actual account and saved-resume evidence

Profile 8 was now observed on a non-Naukri active tab. Without changing its active
tab or front window, the installed background worker resumed. A genuine
`PROFILE_OBSERVED` report passed the approved account-hash check and was persisted
as `COMPARED` at **14:34:28 UTC**. The stored account approval remains revision 1;
no canonical/platform email was revealed, changed or silently equated. The current
layout's other profile fields returned UNSUPPORTED; that report does not establish
successful full profile synchronization or a provider resume match.

A separately requested compare-only profile read used the existing native worker's
own inactive, durably bound `/mnjuser/profile` tab. An owner-invoked read-only
diagnostic rechecked the visible identity against the approved hash and clicked
the genuine `.section.resume .action-container .download` control once. It did not
click Apply, Update resume or a chooser, and did not activate any tab/window.

The asynchronous in-page checksum observation did not return before the worker
closed its tab; its result is **NOT OBSERVED**, not PASS. A scoped read of Chrome's
download-history SQLite file failed with OperationalError; no database or profile
file was modified and this failure was not used as evidence of a PDF match.

The existing background extension-setup tab was temporarily navigated to Chrome's
ordinary Downloads page filtered for Naukri. This left the active-tab/front-window
IDs unchanged. That UI showed a **Today** download with an explicit
`blob:https://www.naukri.com/…` source and a local PDF filename. The corresponding
downloaded file was found in Downloads, had a genuine `%PDF-` header and **100,198
bytes**, with file modification time **2026-10-31 14:37:22 UTC**. Its computed
SHA-256 matched the currently confirmed canonical PDF's checksum exactly, and its
byte count matched too. The setup tab was restored to Extensions without changing
the active tab/window. The downloaded file was preserved, not deleted.

This is actual provider-saved PDF byte evidence following the real Download UI,
not filename matching. **No resume replacement is needed for this observed file.**
It is a supervised diagnostic verification, not a claim that the unattended
MAIN-world capture path or future per-application freshness checks have passed.
No PDF contents, filename, checksum, signed URL or candidate identifiers are public.

## Actual repeated discovery and remaining parser failure

The installed extension/worker resumed genuine Naukri searches at the configured
**300-second interval**. A durable snapshot recorded **53 unique admitted URLs**
across cycles. The latest observed cycle started **14:39:40 UTC** and committed
at **14:39:56 UTC**, with **13** newly admitted URLs and no source error. These
are discovered URLs, not 53 eligible jobs. Earlier installed discovery had taken
about 76 seconds; the new roughly 16-second cycle is a single differently loaded
observation, not a controlled benchmark.

A later committed cycle started **14:45:10 UTC**, finished **14:45:24 UTC**, and
added **20** URLs, bringing the cumulative count to **73**. The corresponding
snapshot held **47 DISCOVERED**, **26 NEEDS_INPUT**, the same one historical
receipt and still zero READY_TO_APPLY. This is another actual recurring discovery
cycle, not application acceptance.

At that snapshot: **38 DISCOVERED**, **15 NEEDS_INPUT** with
`job_required_facts_unrecognized`, **1 SUBMITTED_RECORDED** historical receipt,
**0 READY_TO_APPLY**. Nine of the parser failures were newly observed after the
six retained earlier failures. No failed metadata was fabricated or treated as a
filter pass. PREPARE_ONLY remains active and submission authorization is false.

Two newly captured genuine inactive listing documents established the exact bug:
the real header puts `<i class="ni-icon-location"></i>` before
`<span class="styles_jhc__location__…"><a>…</a></span>`. The installed broad
`[class*="location"]` selector chooses the empty icon first. Both captures had
one header, a real title/employer, supported `0 - 2 years` / `0 - 1 years`,
descriptions of **2,372 / 1,640 characters**, and **10 / 28** skills, but an empty
location from the installed selector. This is a genuine DOM compatibility bug.

The correction selects the actual modern location text span, retains legacy
location containers and excludes icon-only matches. A location icon alone remains
unsupported. It changes no account, resume, quota, idempotency, eligibility, Apply
or receipt control. Extension version becomes 1.3.5; key/ID/permissions are identical.

The corrected **read-only** function was then evaluated diagnostically on **two
additional genuine worker-owned inactive listings**. Both returned `job_facts`
with a nonempty location, experience **0–1**, **10 / 21** skills, and applicant
bounds **100 / unknown**. Their actual structured posting dates were
**2025-10-16 / 2025-10-30**, outside the configured two-day limit on this Mac's
2026-10-31 date. They are not eligible applications. The diagnostic results were
saved privately; they were not injected into the production queue, used to bypass
the installed adapter or called submission receipts.

The actual observed facts were also evaluated locally by the existing eligibility
function against the current persisted policy revision **7** (age **2 days**,
minimum score **80**). Both returned **`posting_outside_age_limit`**; zero eligible
applications were manufactured from these pages.

## Acceptance matrix

| Check | Result | Evidence / remaining limit |
| --- | --- | --- |
| Approved platform identity on genuine profile | PASS one observation | Installed worker accepted actual account-bound profile report; no contact change |
| Canonical versus provider-saved resume | PASS supervised bytes | Genuine Download UI, Naukri blob source, 100,198-byte downloaded PDF, exact SHA-256 match |
| Resume replacement | NOT NEEDED for observed file | Saved PDF matches; no upload/replacement performed |
| Repeated genuine discovery | PASS bounded observations | Durable 53 then 73 unique URLs, recurring 300-second schedule, successive cycles +13 / +20 |
| Installed listing extraction | FAIL | Empty location icon selected; no eligible work prepared |
| Corrected read-only extraction on real pages | PASS 2 observations | Location/experience/skills/dates/applicant uncertainty extracted; pages correctly ineligible by age |
| Grounded matching / first eligible queue item | BLOCKED | Production extension correction not installed; current ready count zero |
| New fill/questionnaire/upload/Apply | NOT TESTED | Zero new employer actions; existing supported-flow/permission gates retained |
| Independent new receipt / notification | NOT TESTED | Zero new receipt or notification; QTrino never replayed |
| Bounded AUTOMATIC | NOT ACTIVATED | Requires first genuine new receipt and critical checks |
| Locked/restart recurring submissions | NOT TESTED | Earlier awake readiness passes do not establish locked browser operation |
| Unconditional 24/7 | NOT ESTABLISHED | Mac must remain awake, Chrome connected and provider flow supported/permitted |

## Targeted validation and exact extension-only cutover

- **16 targeted Node tests passed**, 6.172 s: observation and native protocol;
  includes one new empty-icon negative case and the real-layout structure in
  the existing modern-header case. These are isolated regressions, not live jobs.
- **4 isolated Chromium queue cases passed**, 7.392 s; modern fixture now includes
  the actual icon-before-location structure. **0** live provider requests,
  unexpected requests, chooser events or Apply clicks in these fixture tests.
- Prettier/diff checks and extension build passed. No backend/frontend/full suite
  was rerun for this extension-only change.
- Exact candidate was built in a registered immutable linked worktree, with
  **22/22** files matching Git. No venv/frontend/dependency installation was needed
  for the Node-only extension builder. RAM/CPU were not benchmarked.
- Private rollback inventory holds all **22/22** currently installed 1.3.4 files
  with hashes. Backend/frontend/native remain `fc91a21`; no service replacement,
  private configuration change or new permission is part of this proposal.

After owner approval of exact extension SHA
**`3644b65aa7c2d3707a58b35f64df266807746a6d`**: stop the read-only queue and verify
no active/uncertain action; revalidate installed hashes; deploy its exact 22-file
build to the existing stable directory; use ordinary same-ID Reload; verify
version/disk/heartbeat separately; resume PREPARE_ONLY and retry only proven
read-only parser failures. Existing/uncertain/historical submissions remain fenced.
Rollback restores all 22 exact 1.3.4 files, ordinary Reload, and verifies connection
before resuming read-only processing. Previous releases and evidence are retained.

```sh
pnpm -C extension exec node --test tests/naukri-observation.test.mjs tests/native-protocol.test.mjs
pnpm -C extension exec node tests/naukri-queue.browser.mjs
pnpm -C extension build
.venv/bin/python backend/scripts/verify_extension_cutover.py \
  --sha 3644b65aa7c2d3707a58b35f64df266807746a6d \
  --extension-dir "$HOME/Library/Application Support/Automated Apply/release-candidates/3644b65aa7c2d3707a58b35f64df266807746a6d/extension/dist"
```

Next: install the exact approved extension correction, verify real filtered/matched
work, then exercise the standing authorization for **one new eligible supported
application**, including independent receipt reconciliation. Do not weaken date,
applicant or matching filters to manufacture that result. No Gmail send, other
platform activation, hosted Actions, merge, cleanup or provider outreach occurred.
