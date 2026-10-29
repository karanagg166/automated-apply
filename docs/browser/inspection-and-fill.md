# Chrome inspection and fill

This milestone inspects and fills native controls. It cannot submit applications.
The feature is disabled by default. PR #22's preparation/executor history is the
base; this feature is stacked on `feat/agent-command-execution` at
`94fe1106528cde23bf30faf4e532c5d74d42ae8c`. Phase 1 and main are unchanged.

## Two modes

**Answer unanswered fields:** on a supported application form, right-click and
choose **Answer unanswered fields with Automated Apply**, or open the extension
and click **Prepare answers for this form**. The existing local answer engine uses
the current owner-reviewed profile, confirmed links and approved facts. Review the
answers, then click **I reviewed these answers — fill unanswered fields**. There is
no saved application ID to copy: the existing job/packet services persist the
owner-selected URL and return real IDs. A selected page is explicitly unverified
as an employer/vacancy; capturing it never asserts source verification or submission.

Already answered controls are excluded without exporting their values. A second
empty-field check immediately before each fill also preserves anything typed after
preparation. Unknown facts, unsupported questions and consent stay unanswered. The
same expiring, version-bound, single-use field authorization applies. This path
does not use a cloud model, enable a provider, upload a PDF, click Next or submit.

Manual answer preparation additionally recognizes tenant `zohorecruit.in` and
`zohorecruit.com` `/jobs/Careers/<numeric-id>/<slug>` pages, including bounded
`source`/`ref` tracking parameters. This is a manual-extension URL contract, not
live portal acceptance. The autonomous driver's URL restrictions are unchanged.
Custom widgets, cross-origin frames, challenges and framework-controlled inputs
can still require handoff. No live employer form was filled to test this change.

### Zoho Recruit manual form compatibility

In manual extension mode (`only_empty: true`), the inspector handles Zoho Recruit-style DOM layouts while keeping client-only diagnostics out of the native protocol payload:

- **Supported controls (filled only after owner review):**
  - Visible unanswered native `<input>` (`text`, `email`, `tel`, `url`, `number`) and `<textarea>`, including dynamically rendered controls present when **Prepare answers** is clicked.
  - Labels resolved from explicit `<label>`, `aria-labelledby`, `aria-label`, Zoho table cells (`<tr>/<td>`), `<dl>/<dt>/<dd>` rows, single-control field containers (`.zr-field-label`, `.cw-label`, `[class*='label']`), `data-label`/`title`, or meaningful placeholders, with mandatory markers (`*`, `(Required)`) normalized.
  - Native `<select>` dropdowns with up to 20 options when currently on an empty or placeholder selection (`-None-`, `--Select--`, `Select an option`, `Choose one`, disabled initial option).
  - Native radio and checkbox groups with a resolved group question label (`fieldset > legend`, `[role="radiogroup"]`, `[role="group"]`, or multi-option Zoho question container) and per-option label. If any option in a radio or checkbox group is already selected, the entire group is treated as answered and left untouched.
  - Required-field and validation-error indicators (`required`, `aria-required="true"`, `data-mandatory="true"`, asterisk markers, `aria-invalid="true"`, `aria-errormessage`, `.zr-error`/`.field-error`/`[role="alert"]`).
- **Manual-only controls (reported in the popup plan with explicit reasons, never auto-filled):**
  - Custom comboboxes and picklists (`[role="combobox"]`, `aria-haspopup="listbox"`, `lyte-dropdown`, `lyte-select`, `lyte-autocomplete`, `crux-picklist-component`, `[role="listbox"]`).
  - Date/time controls (`type="date"`, `dd/mm/yyyy` placeholders, datepicker widgets, or date-of-birth/start-date fields).
  - Framework-controlled inputs (`_valueTracker`, `__reactFiber$*`, `__reactProps$*`, `lyte-input`, `crux-text-component`, `ng-model`, `v-model`, `data-framework-controlled`) where silent native value assignment without synthetic events cannot be proven safe.
  - Rich-text / `[contenteditable="true"]` editors, multi-select dropdowns, and native `<select>` controls with more than 20 options.
  - Controls with missing or generic-only labels (`Enter here`, `Type here`, `-None-`) or radio groups missing a group question label.
  - File upload inputs (`type="file"`, manual PDF selection required).
  - Consent, privacy policy, terms, background-check, EEO, NDA, and legal declaration checkboxes/radios (never selected automatically).
  - Cross-origin iframes, CAPTCHA/security challenges, and sensitive controls (passwords, OTP/MFA codes, payment/card/bank details, SSN/Aadhaar/PAN/national IDs, tokens/secrets), which halt preparation and require manual completion.
- **Preservation and fresh-review guarantees:**
  - Pre-filled fields and controls edited by the user after preparation (tracked via initial value snapshots and trusted `input`/`change` listeners) are never overwritten.
  - Any DOM mutation affecting form controls/attributes, step transition, or expired plan timestamp (`expires_at`) invalidates the prepared plan and requires clicking **Prepare answers** again for a fresh review before filling.
  - Manual mode never clicks Next/Continue or Submit, never dispatches synthetic `input`/`change` events, and blocks accidental form submission after touching controls.

The installed runtime must support `prepare_form_answers`, and manual filling
requires separate owner authorization for `BROWSER_FILL_ENABLED=true`. Keep
`BROWSER_AUTOMATION_ENABLED`, `BROWSER_SUBMIT_ENABLED`, application submission,
email sending and Cohere disabled. A missing/unreviewed profile gives a specific
instruction to complete Profile before any answer or job is saved. Replacing the
installed extension/backend and changing private configuration remain explicit
owner upgrade checkpoints.

`pnpm -C extension test:answers:chrome` exercises the real inspector and popup in
isolated Chromium using intercepted fictional pages and mocked native replies.
It never connects to the owner's native host or employer servers.

**Manual extension:** open a supported application URL, invoke the extension,
paste the saved application packet ID, click **Inspect application form**, review
the field plan, and click **I reviewed these values — fill form**. These are
trusted popup click handlers. Inspection uses `scripting` in the isolated top
frame under the existing `activeTab` grant; it cannot obtain that grant silently.
There are no persistent host permissions or content scripts. The committed public
manifest key, stable ID `gdjbmkffcpicbpiikcohlmokkmcpipgp`, native origin check and
private native configuration are preserved. Native protocol v1 carries nested
inspection/plan v1 contracts. Failed or duplicate authorization never replays
executable values.

Manual mode sets ordinary native controls without firing input/change events.
Upload the canonical PDF manually. Framework-controlled widgets and further steps
can require manual handling. The extension has no network-observation permission;
it does not certify that arbitrary website scripts cannot send their own requests.
It never clicks submission controls or claims a submitted application.

**Local automation:** an authenticated deterministic owner command grants bounded
fill scope for saved prepared selections. The command worker only enqueues work.
A separate browser worker starts Chrome for Testing in a dedicated, private,
marked profile. It never connects to an existing browser debugging endpoint or
uses an everyday Chrome profile. Each application keeps its own tab for review.
Native inspection uses a CDP isolated world; website JavaScript cannot replace the
inspector's field-reference closure.

For interactive applications, use the [selected connected Chrome extension](../phase53/chrome-profile-reuse.md). The following browser is explicitly for isolated testing.

```sh
# Install with pnpm, using the repository's pinned versions.
pnpm -C frontend install --frozen-lockfile
pnpm -C frontend exec playwright install chromium

# In the owner's approved private configuration, opt in explicitly:
# BROWSER_FILL_ENABLED=true
# BROWSER_AUTOMATION_ENABLED=true
python backend/scripts/run_browser_worker.py --executor isolated_browser --profile-parent /absolute/private/directory
```

The existing operator configuration/startup database restrictions still apply.
Real candidate data must use the existing owner-approved online PostgreSQL.
Do not point a real profile at the SQLite fixture environment. No migration or
production schema/grant change is needed: private owner preferences store plans
and jobs, and append-only agent operations store audit receipts.

For sign-in, stop the browser worker first, then run:

```sh
python backend/scripts/run_browser_worker.py --executor isolated_browser --profile-parent /absolute/private/directory --sign-in https://jobs.lever.co/your-employer/your-job
```

This is an owner-operated, headed browser session with no agent inspection or
filling and no automation network guard. Sign in yourself, including MFA, and
press Enter in the terminal to close it before restarting the worker. Credentials
and cookies stay in that dedicated Chrome profile; the agent never extracts them.
The sign-in mode is a CLI operation, not a model/Telegram/browser tool. CAPTCHA,
MFA and expired-login forms always cause handoff; no bypass is implemented.

## Commands and review

- `Prepare the first two jobs.`
- `Fill the first application.`
- `What's missing from the second form?`
- `Use Quick-Clinic where the form asks about my best project.`
- `Stop filling applications.`
- `Find Python backend jobs, prepare applications for the best three, and fill their application forms using my verified resume and project details.`

Selections resolve to actual saved IDs. A model proposal cannot grant fill scope.
The deterministic compound command permits up to five preparations/fills within
the existing 16-step limit. Other fill commands require an explicit saved position.
`fill_application` has its own feature flag; `submit_application` stays disabled.

Agent shows private field plans with proposed values, evidence and versions. A
narrative waits for field selection/review before filling. For ordinary confirmed
facts, the explicit local fill command authorizes their mappings; the result still
requires inspection in Chrome. Use **Inspect next step** only after reviewing the
current page. Only an unambiguous native `button type=button` labelled Next or
Continue can progress; final submission controls never qualify. Each next step
requires a new inspection and field review. A campaign permits at most five steps,
24 fields per page, 20 options per field and ten application tabs.

Campaigns remain `waiting_browser` while browser work or narrative review is
pending. Results distinguish draft preparation, form inspection, form filling,
needs input, manual intervention, failure and cancellation. They always say
submission was not performed. The application tracking state is never changed to
applied by filling.

## Grounding and authorization

Both modes use `FormService` with the existing reviewed primary profile,
`ApplicationPacketService`, `AnswerBuilder`, deterministic application-answer
engine and approved project context service. Unconfirmed/environment-only links,
unknown salary, notice period, employment, authorization and achievements are
never invented. Consent checkboxes are not inferred. Dropdowns require an exact
verified option; radio/checkbox choices require a separate group question and a
grounded exact option. Missing fields remain untouched.

Narratives use deterministic grounded answers and remain reviewable. Inspection
never enables Cohere transmission or paid calls, even when other command AI is
configured. This milestone makes no live Cohere request. Existing separately
consented provider workflows remain available outside this inspection path.

Resume upload requires a confirmed primary private resource, its linked confirmed
private PDF, decryption and matching SHA-256. A Drive URL alone is not an upload.
Automation verifies the safe PDF reference again and briefly materializes bytes
in a mode-0600 temporary file inside the mode-0700 dedicated profile for Chrome's
file-control API, deleting it after the upload. No arbitrary path is accepted from
a page or model. Manual mode leaves upload to the owner.

Plans expire after ten minutes. They bind to the exact saved destination,
application packet revision, candidate context digest, approved project versions,
PDF reference and browser document ID. Profile/PDF/project/job/packet changes
require revalidation. Authorization is single-use, stored before browser actions.
Browser jobs have a 15-minute scope and a 90-second fenced lease. A field checks
freshness and fencing before mutation. Owner cancellation revokes queued work and
outstanding plans. Audit receipts contain field identifiers/statuses and references,
not values, PDF bytes, cookies or credentials. Plan values are private owner data.

The contract exports no existing input values or selectors. Passwords, OTP/MFA,
session/token, card and other sensitive controls are excluded, and their presence
causes handoff. Labels and option text are bounded untrusted data, never browser
instructions. Changed control identity/type/label/options/limits fail closed.
Native messages retain the 16-KiB frame cap. Browser routes have the owner auth,
body limit, no-store and BFF/CSRF boundaries.

## Network and recovery limits

The automation driver blocks service workers, WebSockets, popups, non-GET/HEAD
requests and unexpected top-level navigation. Only the exact application URL and
same-origin resources can load initially. Once filling/progression begins, all
subsequent page network requests are blocked. A blocked request stops the workflow
and requires manual handling, including portals that autosave or submit on change.
This conservatively excludes many live portal implementations. No live portal is
claimed accepted merely because its host is allowlisted.

A lost browser response, expired lease, browser crash or restart never replays a
fill. It becomes manual intervention/reinspection. The command queue remains
independent and durable. The browser heartbeat expires after 15 seconds; unavailable,
offline or sleeping workers are reported unavailable. Sleep stops local execution;
a powered-off Mac cannot work. Physical locked-screen operation is **unverified**.
No screen lock, sleep, runtime replacement, launchd modification or deployment was
performed on the owner's working Mac.

## Supported and unsupported forms

The URL allowlist is Greenhouse boards, Lever jobs and Google Forms paths. Supported
operations are bounded, visible native inputs, textareas, email/tel/url/number
controls, selects, grouped native radios/checkboxes, canonical PDF file inputs,
validation indicators and local native multi-step transitions. These are accepted
against local fictional pages, including a Google Forms-like page.

Custom ARIA-only controls, cross-origin frames, shadow DOM, sensitive fields,
CAPTCHA/MFA, login transitions during filling, query-bearing/redirected URLs,
unreviewed facts, arbitrary employer hosts and network-dependent upload/autosave/
step transitions require manual handling. Real Google Forms/ATS variants and owner
manual-toolbar acceptance require separate live verification. Final submission
and email sending are outside this milestone.

## Reproduce verification

Use the shared `/tmp/automated-apply-heavy-tests.lock` for heavy local suites.
`python backend/scripts/run_browser_acceptance.py` acquires it automatically.
The explicit browser suite uses actual Chrome for Testing, local HTTP fixtures,
the real backend preparation/grounding/queue services and fictional disposable
SQLite. Telegram transport is simulated; authenticated intake, planning, Chrome
operations and result persistence are real. Unit HTTP tests are in-process ASGI.
The retained Phase 1 lifecycle suite separately exercises actual native framing,
loopback FastAPI, MV3 and disposable restricted-role PostgreSQL with restart.

Full backend regression requires a newly provisioned disposable PostgreSQL 17
`PROFILE_TEST_DATABASE_URL`, following Backend CI. The extended command PostgreSQL
acceptance verifies browser queue concurrency, the locked-active-row case, single-use
plan consumption, append-only audit privileges, lost leases and no replay.
The local fixture server asserts zero application POSTs, and unit tests forbid live
provider HTTP. No test emails or external applications are sent.

See [verification evidence](verification.md) for final results and limitations.
