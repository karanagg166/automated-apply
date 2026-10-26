# Integrated live-readiness audit — 2026-10-26

Verdict: the reviewed fixture engine and its foundations are integrated. Owner
runtime upgrade, genuine Telegram-to-Chrome acceptance and real employer submission
are separate, incomplete gates. Real application submission remains disabled.

## Git and package manager

Integration branch: `integration/live-readiness-20261026`. Its implementation
descends from PR #24's verified `59a53c1b81737a58fef6e9b97b8141d742f5c25c`.
Resolve the final commit with `git rev-parse integration/live-readiness-20261026`;
the delivery message records the exact SHA and hosted checks. The intended target
is `feat/phase1-local-connections`, never `main`.

The stack is linear: #18 `7dfe694` → #22 `94fe110` → #23 `d73d9e3` → #24 `59a53c1`.
An isolated integration worktree was created and fast-forwarded to #24. There were
no cherry-picks, resets or duplicate merges. All original commits survive. The
occupied original checkout, untracked AGENTS.md and unfinished `agent/tools.py`,
six other worktree migrations and their parent branch heads were preserved. Stale
worktree registrations were inventoried without pruning. No additional agent was
delegated writing access to the integration worktree.

The consolidated frontend uses pnpm **12.15.0**, one committed pnpm lockfile and a
manager/alternate-lockfile install guard. Frozen install succeeds. CI, Docker and
installation scripts contain no npm/npx/yarn install steps. The audit also corrected
remaining executable npm documentation and misplaced pnpm `--prefix` commands;
historical reports retain the names of tools originally used. System npm was not changed.

Three example phrases needed small extensions to the existing deterministic
planner: startup-size follow-ups, `Prepare the first two applications`, and
`Use my Quick-Clinic project`. A regression journey preserves India/startup/size
filters and saved IDs, refuses a nonexistent second selection, refuses unapproved
project context and prepares only local drafts. This creates no alternative agent
or model provider and grants no submission authority.

## Actual installed services and owner data

The installation's Git head is **`b20902f7300edc9e6960fe3ed688bbb57028b0a5`**,
with **18 modified tracked files and 23 untracked files**. Ten modified files
match reviewed integration files; eight differ. The running process's complete
in-memory source cannot be inferred from this dirty Git head. API and dashboard
process paths point to that installation; no command or browser routes appear in
its served OpenAPI. Do not describe the reviewed submission engine as installed.

| Check | Actual evidence |
| --- | --- |
| FastAPI | Loopback `/health` and `/ready`: HTTP 200 |
| Dashboard | Loopback `/login`: HTTP 200; owner credentials not changed |
| Supabase | PostgreSQL 17.11; TLS and remote-only enabled; read-only transaction |
| Integrated DB preflight | Existing public bundle/restricted role and Gmail-compose follow-up pass; no DDL |
| Telegram authentication | Official `getMe`: HTTP 200, `ok=true`, bot identity valid |
| Telegram transport | Official `getWebhookInfo`: HTTP 200, no webhook, zero queued updates at observation |
| Poller | Real worker PID present; recent persisted poll and no last error |
| Command executor | New implementation absent from served installed API; no standalone worker observed |
| Dedicated Chrome worker | No active dedicated worker; browser automation disabled |
| Native bridge | Wrapper exists; manifest allows precisely the configured stable extension origin |
| Extension identity | Source, installed manifest and private setting agree: `gdjbmkffcpicbpiikcohlmokkmcpipgp` |

The audit did not independently establish the unpacked extension's currently loaded
Chrome UI path/version. Manifest identity and native-origin consistency are
configuration evidence, not a new owner gesture or successful end-to-end native
round trip in the everyday browser. The isolated native/Chrome suite is separate.

Private settings load successfully from a mode-0600 external file. Telegram owner
IDs, bot/API credentials and resume encryption key are populated; no values were
printed. Browser automation/submission, application submission, email sending,
discovery automation, local Telegram AI and all Cohere activation/data-consent flags
remain false. No owner service was restarted or replaced.

| Owner setup item | Current state and review needed |
| --- | --- |
| Profile and contacts | No saved primary profile; review name/email/phone and current version |
| Skills/experience | No saved profile; review actual skills, roles, dates/years and claims |
| Profile links | Review GitHub, LinkedIn and selected additional links; configuration is not approval |
| Canonical PDF | One encrypted PDF decrypts, has a PDF header and matches its checksum; **unconfirmed** |
| Primary resume resource | Zero resume resources; no confirmed primary PDF reference |
| Projects | Three configured projects; zero built candidate revisions and zero approved facts |
| Preferences | Saved preferences exist; the preferences contract records no separate review attestation |
| Jobs | Zero cached jobs at observation |

The existing dashboard wizard and project review panels provide these owner steps.
No data was approved, modified or uploaded. Existing profile/resource/PDF/project,
job/document and packet version bindings invalidate stale preparations and grants;
the regression suites exercise those failures.

## Genuine sources and real portal read-only checks

On 2026-10-26 the existing **ArbeitnowAdapter** and **GreenhouseAdapter** each
normalized five actual public records using unauthenticated GET requests. These
were source-reported vacancies, not a verified India/Python/startup shortlist and
not jobs saved through the installed owner's executor. The owner DB remained
unchanged. Examples: Greenhouse source ID `8126988`, Commercial Counsel, Eastern
Timezone; Arbeitnow slug `hosting-architekt-berlin-104581`, Hosting-Architekt, Berlin.
Zero eligible matches must remain a valid outcome for the owner's requested filters.

Sources: [Greenhouse public GET contract](https://docs.greenhouse.io/job-board.html),
[Arbeitnow free feed description](https://www.arbeitnow.com/blog/job-board-api).
One official Lever posting GET returned no jobs for Lever's own board; a subsequent
Palantir board GET returned one actual public posting. This is metadata verification;
Lever is not newly added as an executable job-source adapter.

Inspected application pages, after their robots rules permitted the read:

- [Greenhouse Commercial Counsel](https://job-boards.greenhouse.io/greenhouse/jobs/8126988?gh_jid=8126988).
- [Palantir on Lever](https://jobs.lever.co/palantir/6ed76ce8-4156-4b60-b120-403538bd66cd/apply).

Static HTTP inspection exposed actual form/control metadata, file inputs, required
questions and final submit controls. Greenhouse has custom `role=combobox` inputs
and a GET form whose dynamic JavaScript supplies application behavior. Lever has a
POST multipart form and multiple external scripts. This did not inspect input values,
click controls, fill fields, upload data or request an application receipt.

Actual Chrome 156 inspection through the **existing** guarded driver returned
`unsupported`, zero fields for both canonical pages, with 11 blocked network events
on Greenhouse and nine on Lever. The original Greenhouse `?gh_jid=8126988` URL is
rejected before navigation by the existing query-string prohibition. A separate
read-only visit to the same job's query-free canonical route still failed support.
The guard restricts requests to same-origin GET/HEAD and blocks other navigation,
WebSockets and writes. Native control/option limits and custom widgets also bound
the inspector. These observations establish current incompatibility, not successful
live autofill. No protections were weakened and no live adapter was enabled.

| Behavior | Acceptance boundary |
| --- | --- |
| URL handling/navigation | Actual query-bearing Greenhouse URL rejected; canonical Greenhouse/Lever visits made read-only |
| Form/required fields | Public static metadata visible; guarded live inspector returns unsupported |
| Resume input | Public file controls observed; no owner upload or employer upload endpoint exercised |
| Dropdowns/checkboxes | Static native controls observed; Greenhouse custom combobox behavior unaccepted |
| Login/CAPTCHA/MFA | Fixture handoff regressions pass; no real login, challenge handling or bypass attempted |
| Dynamic/autosave | Cross-origin requests blocked; live upload/autosave/transitions unaccepted |
| Receipt/confirmation | No authentic public success receipt observed; no submission to obtain one |

A safe live adapter needs reviewed portal-specific request types/origins, custom
field semantics, upload handling and authentic receipt/recovery contracts. GET-only
metadata does not establish those contracts, so inventing or enabling a network
adapter here would not be safe. This release's fixture-only submission guard cannot
be turned into real employer submission by a configuration flag.

## Telegram, Cohere and locked-Mac boundaries

Telegram connectivity is **genuine**; the new workflow on the installed runtime is
**blocked by the missing upgrade**, absent approved owner profile/context, empty
saved jobs and unavailable dedicated worker. No second poller consumed updates and
no test message impersonated the owner. Telegram intake → executor → actual Chrome
→ durable receipt is accepted only with simulated Telegram transport and localhost
fictional employer forms. The owner procedure distinguishes those results explicitly.

The existing Cohere Chat V2 provider supports `command-a-plus-05-2026` and explicitly
selected `command-a-03-2025`. Current official
[model](https://docs.cohere.com/docs/command-a-plus),
[Chat V2](https://docs.cohere.com/v2/reference/chat) and
[evaluation limits](https://docs.cohere.com/docs/rate-limits) documentation was checked
again. No key is configured and no live evaluation or owner-data transfer is
authorized. Tests of structured filters, context, strict tool proposals, invalid
JSON, hallucinations, quotas/rates and failures are **mocked**. Follow
[private setup instructions](../agent/cohere.md); no API key was generated.

Historical lock evidence belongs to earlier installations. No physical lock/sleep
test was performed on this integrated source, no owner power setting was changed
and no always-on deployment exists. Heartbeat/fencing/lease regressions and actual
fixture browser crash/restart tests are software evidence. Generally, display lock
leaves processes running while system sleep suspends local workers; this is an
expectation, not an observed integrated-release acceptance result.

## Operator handoff

Local acceptance on the consolidated implementation used
`/tmp/automated-apply-heavy-tests.lock` to serialize heavy runs on the 8 GB Mac:

| Verification | Result |
| --- | --- |
| Full backend, fresh disposable PostgreSQL 17 | **1,880 passed**, zero failed/skipped; two existing pypdf deprecation warnings |
| Actual Chrome, localhost fictional forms | **48 passed**, zero failed/skipped |
| PostgreSQL submission verifier | Actual Chrome POST/receipt, simulated Telegram intake, concurrent claims, locked lease, fencing, lost completion, restart and read-only reconciliation pass; one fixture POST |
| Command/planner regression suite | **45 passed**, including the new six-command follow-up journey |
| Frontend unit and browser tests | **56 unit tests**, **10 Chromium journeys** pass |
| Extension | **35 tests** and build pass |
| Frontend tools | Frozen install, typecheck, format and production build pass |
| Security | Ruff E9/F/I on integrated agent/browser/AI code, whole-backend Bandit, pip consistency and Python/pnpm audits pass; zero known dependency vulnerabilities |

Hosted acceptance must be associated with the final integration SHA, not inherited
from #24. The delivery message links the final GitHub Actions runs and distinguishes
their result from these local tests. Local test logs and JUnit reports are preserved
privately; the backend rerun follows the planner correction, rather than reusing the
earlier 1,879-test baseline.

Use [owner upgrade, rollback, profile and acceptance steps](owner-upgrade-and-acceptance.md).
The next authorization is a **local runtime upgrade/restart**, followed by owner
profile/PDF/project review and non-submitting Telegram acceptance. Chrome filling,
provider-data transfer, real portal acceptance, any future DDL/deployment and exact
real submission approval remain separate gates. No current test establishes production
readiness or grants permission to submit an employer application.

Detailed logs, source IDs, runtime inventories and browser metadata stay in ignored
`reports/live-readiness/`; no private environment, candidate data or secret is tracked.
