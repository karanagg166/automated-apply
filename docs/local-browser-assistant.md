# Local browser application assistant — assisted milestone

This feature adds working **Analyze → reviewed Fill → Review → Take Over** on
explicitly permitted employer forms. It reuses saved candidate profiles, confirmed
resources, encrypted private PDFs, packet answers, revisions, audit events,
readiness and owner-reported submission tracking. It does **not** enable automatic
real employer submission. A separately gated fictional submission extension is described below. For real employers the Submit control is disabled and its API returns 403. Historical PostgreSQL safety guards and the R1/R2 gates remain intact.

## Checkout and integration audit

Development branch: `feat/local-browser-assistant-20261023`, in an isolated worktree
at `/private/tmp/automated-apply-browser`. The original checkout and its staged
`supabase/.temp/` files were preserved. No private environment files were copied.

- PR [#15](https://github.com/karanagg166/automated-apply/pull/15), head `ac265d3`,
  remains unmerged: durable discovery worker/scheduling, migration 012 and separate
  runtime ACL addendum. This feature creates no replacement discovery scheduler.
- PR [#16](https://github.com/karanagg166/automated-apply/pull/16), head `f4d7d4c`,
  remains unmerged: audited roadmap. This feature branches from that head.
- Unpublished Phase 9 fix `edb59c5` was reused as `a941bb1`: preserve private resume
  references when validating PostgreSQL packet approval. Its tests are retained.
- Local Phase 10 completion work `2cd672e` and Phase 11 release candidate
  `51082fb` were inspected, along with the separate real-account branch `a339188`.
  Their discovery/account/deployment changes were not imported into this feature.
- Existing FastAPI owner authentication, Next.js BFF/session/CSRF, profile/evidence
  retrieval, answer builder, encrypted resumes and application packet repository
  provide the shared implementation. No parallel application status table exists.
- Phase 9 R1 recovery prerequisites remain unresolved; R2 is unauthorized. No
  migration, grant, role change or write was performed on a remote database.
  Historical migrations 001–011, their manifest and pinned Phase 9 SQL are unchanged.

## Local setup

Use Python 3.11+, Node 22+, pnpm 12.15.0, local Chrome, and a separately authorized database.
The feature does not change the existing database safety checks or configure a
production database. Develop and test using disposable PostgreSQL 17 as below.

```sh
uv pip install --python backend/venv/bin/python -r backend/requirements-browser.txt
pnpm --dir frontend install --frozen-lockfile
```

The frontend pins pnpm 12.15.0 in `package.json` and commits only
`pnpm-lock.yaml`. Install that pnpm version using your local package manager or
the [official standalone installer](https://pnpm.io/installation). Use pnpm for
installation, scripts, browser tools and dependency audits. CI uses the same
version and frozen lockfile; the Docker build copies the pinned official pnpm
image. Only the existing esbuild/sharp dependency build scripts are allowed.

Put configuration/API secrets in an ignored private environment file; keep career
facts in the protected profile/resource APIs. Never commit cookies or browser data.
With the existing owner token and frontend login configured, add:

```dotenv
BROWSER_ASSISTANT_ENABLED=true
BROWSER_ALLOWED_ORIGINS=["https://careers.example.com:443"]
BROWSER_ASSET_ORIGINS=[]
BROWSER_CHANNEL=brave
BROWSER_HEADLESS=false
BROWSER_PROFILE_ROOT=reports/browser-profiles
APPLICATION_SUBMISSION_ENABLED=false
```

The example hostname is a placeholder, not verified permission. Review the actual
employer's access rules before configuring its exact origin. Known restricted
portals (LinkedIn, Naukri, Wellfound, Instahyre, Internshala) remain manual-only,
even if added to this list. Public static assets can be separately approved as
described below. Embedded application frames and third-party APIs still require
manual handoff. No API key establishes an account connection.

Run the existing FastAPI backend with **one worker**, bound to `127.0.0.1`, and the
existing Next.js dashboard. Browser commands require loopback plus the existing
owner bearer; the dashboard uses its server-side BFF token and session/CSRF checks.
Do not expose the local browser API through public ingress.

```sh
backend/venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
pnpm --dir frontend run dev
```

## Operating the assistant

1. Save and review your candidate profile. Unknown values remain absent. Confirm
   the intended resume in My Profile; PDFs stay encrypted in database storage.
   **Private application facts** stores current/expected compensation with explicit
   currency, period and type, actual availability, current location, approved
   relocation destinations and country-specific authorization/sponsorship. Blank
   means unknown; salary search minimums never supply current or expected pay.
   Saving checks the profile version and makes old drafts/packets require review.
2. In Applications, paste the employer application URL and identify the company
   and job. Prepare the packet and open its detail page. Existing saved-job packets
   can also use the assistant when their destination has explicit permission.
3. Approve the dedicated browser profile and permitted destination, then click
   **Open dedicated browser**. If public asset origins are configured, inspect the
   displayed list and explicitly approve their limited loading policy as well.
   This launches a new app-owned Chrome profile. It
   never attaches to your default Chrome, unrelated tabs or an exposed CDP port.
   You can navigate manually after Take Over, then explicitly review and authorize
   a supported page on the same permitted origin to resume assistance. Pasting a
   URL is the supported entry point in this milestone.
4. Click **Analyze Application**. Visible native controls and unsupported custom
   controls appear in the browser panel and in the existing Application fields.
   Inspect each proposed answer and source; edit using the existing answer editor.
   Generate narrative drafts explicitly using the configured provider, then review.
5. Confirm the current answers/resume and that the observed page belongs to this
   company/job. Click **Fill supported fields**. Missing/invalid/unreviewed answers
   remain incomplete. A changing form interrupts filling and requires reanalysis.
6. Review the actual website, including its validation errors. **Take Over** permits
   manual actions on that origin and suspends automated filling. Complete required
   consent, CAPTCHA, MFA and unsupported controls yourself. Analyze again for
   changes within the same document. After navigation or a reload, use **Resume
   after manual navigation → Preview current page → Authorize page and analyze**.
   Review fresh answers before filling the next step. Server saves remain manual.
7. Submit manually on the employer website. A click, success text, or navigation
   never marks the packet submitted. Record your actual receipt using the existing
   explicit submission report. It remains `user_reported_submitted`, not provider
   verification. **Cancel** closes the browser session; packet history remains.

**Cancel remains available while a browser command is running**, including opening,
filling, a reviewed step or an authorized mock dispatch. The dashboard reads the
current operation ID through an authenticated endpoint, stops only that operation,
closes the app-owned browser resources and reconciles saved state. Commands already
queued before cancellation are discarded. A stale operation ID cannot stop a newer
command. Earlier responses cannot overwrite the dashboard's cancellation result.

If a mock dispatch was reserved, cancellation preserves `submission_unknown` until
independent receipt recovery proves acceptance. It never grants another dispatch;
existing verified receipts remain verified. Cancelling browser work preserves the
application packet for review. If shutdown or reconciliation exceeds 20 seconds,
the current runner refuses new browser commands. Inspect saved status and restart
the local runner; restarting never replays a command. The runner requires one worker.

Labelled native radio groups and bounded ARIA radiogroups can use reviewed answers.
Custom comboboxes are supported when a unique `aria-controls` relationship points to
one single-select listbox with known, distinct choices. The engine selects only an
exact displayed option and checks the resulting browser value. For a bounded class
of native input/button comboboxes whose list is created only when opened, analysis
can briefly open the control, inspect the choices and close it with Escape. It
selects no answer. It checks a hash of application values, hidden fields, selections,
consents, bounded uploaded file contents and document context before/after, without invoking FormData or persisting
those raw values. A changed value, blocked request, navigation or failure to close
stops inspection for manual review. No automatic rollback is attempted on a page
that changed its values. Review the actual website before continuing.

Inspection is limited to three such dropdowns per scan, at most 50 visible, enabled,
distinct choices per list, bounded rendering waits and the existing operation
deadline. Lists with ambiguous ownership, disabled/duplicate choices, multiple
selection, frames, access challenges or unrecognized controls stay manual. Every
fresh scan inspects the current catalog; reopening immediately before filling
checks it again. Changed choices invalidate the saved analysis/review. The dashboard
answer editor displays the exact available options.

If choices need an employer server request, analysis blocks that request. Use
**Take Over**, load and close the dropdown yourself without selecting an answer,
then click **Analyze Application** again. A cached list that can now open without
networking can be inspected and filled after answer review. There is no automatic
choice API access or replay of the blocked request. Choices that fetch again or
need searches/pagination still require manual completion. Unlabelled/ambiguous
groups, rich text editors and consent or attestation choices stay manual. Native
consent checkboxes still use the direct
owner control; no answer model or fill plan grants consent.

Multiple selections are an **opt-in local development capability**. The existing
packet type `multi_select` stores a JSON array of exact option labels, such as
`["Python","FastAPI"]`, through the same answer, review, revision and tracking APIs.
It supports native `select multiple` and bounded labelled native/ARIA checkbox
groups. Checkbox groups need distinct labels, unambiguous membership and enabled
controls; native members must share a name/form and have distinct values. Groups
with consent/attestation language or individually required checkboxes remain manual.
Other custom multiple-choice widgets still require manual completion.

`MULTI_SELECT_FIELDS_ENABLED` defaults to false. PostgreSQL additionally requires
the separately reviewed capability constraint and execution permission on its
validator. The flag alone grants neither. The local-only proposal
[`003_multi_select.sql`](../backend/app/browser/migrations/003_multi_select.sql)
extends fresh disposable fixtures; it is outside production migration/ACL inventory
and supplies no runtime grant. Its validator is not executable by public/client
roles. Installing it in an application database requires a separate migration and
runtime-permission review; this task does not authorize that installation or R1/R2
activation. Existing packet reads remain available when the feature is disabled.

For plain technical-skill questions, proposals use only exact matches from saved
verified skills. They never infer years, proficiency or certifications, and invoke
no model. Other questions or unknown skills require human selections. Every set
requires explicit answer review, including proposals derived from profile facts.
Unchecked options remain unknown facts. Filling replaces the existing selection
set only after review; an explicit empty set is allowed only for optional fields.
The editor prevents filling/reviewing unsaved changes and resets global review
confirmation when the packet revision changes. Save edits, review the stored answer,
then confirm the actual page before filling.

The runner binds underlying choice values as well as labels, rechecks the form
between checkbox changes, pauses networking and validates the final browser state.
Changed codes/questions, revoked capability and invalid controls stop or remain
incomplete. Reviewed Next previews include actual multiple values and native/ARIA
validation; a stale set cannot authorize a step. Unknown outcomes never authorize
submission or replay. Real employer submission remains manual.

The actual PG17/TCP/FastAPI/Chromium demonstration checks all three control types,
review-before-fill, durable tracking, invalid direct SQL answers and denied client
access. It also verifies that an enablement flag without the schema stays manual:

```sh
backend/venv/bin/python backend/scripts/verify_browser_multiple.py
backend/venv/bin/python backend/scripts/verify_browser_multiple.py --without-schema
```

Use only the disposable `PROFILE_TEST_DATABASE_URL` described below. The fixture
installs the proposal in its own child database and removes that database afterward.
No real account, model request or employer submission occurs.

For a supported client-only multi-step form, use **Review next application step →
Preview next step** after filling. The preview shows actual browser values and
validation, including selected consents. Review these, then explicitly authorize
the displayed Next/Continue action. Only a single visible `button[type=button]`
labelled Next, Next step or Continue is eligible; submit controls, embedded forms
and ambiguous buttons require manual navigation. This operation needs the separate
dashboard owner signature and cannot be authorized by AGY's bearer alone.
Configuration rejects reusing the delegated API token as the owner signing key.

Analysis, filling and step review isolate **all page network requests**, including GET, until explicit
Take Over. This prevents a client step from silently saving or submitting through
another HTTP method or delayed callback. Steps needing server saves or navigation
require manual work. A changed form is reanalyzed after an observed stable in-page
transition; the next answers are not automatically filled. No final submission is
authorized by a step approval.

The exact preview, values, form structure and revision bind each step action. Intent
and an idempotency record are committed before the click; a repeated request or a
restart never clicks again. Unchanged, interrupted, unstable or network-dependent
steps show manual handoff. Inspect with Take Over and analyze again before a fresh
review. Automatic progression is limited to 20 reviewed steps per application.

To verify this path with fictional forms and disposable local PG17, run
`backend/venv/bin/python backend/scripts/verify_browser_steps.py` with
`PROFILE_TEST_DATABASE_URL` configured as in the demonstration section. It checks
native radios → signed Next → custom dropdown/date filling and durable step history;
it performs no application submission or model call.

`backend/venv/bin/python backend/scripts/verify_browser_dropdowns.py` checks a
transient server-loaded list against PG17, actual TCP FastAPI and Chromium. It
simulates the owner's one explicit source load, rejects unreviewed choice filling,
fills the reviewed option and reads durable answer/review/manual-handoff state
after closing the browser and database engine. Its fixed fictional manual action
is absent from the normal application; no real employer, model or production SQL
is used. The dashboard suite exercises the same owner handoff through Next.js.

For a server-dependent step, **Take Over** lets you perform the website's save or
navigation yourself. The runner does not choose or click that action. Then open
**Resume after manual navigation** and preview the page you reached. Preview pauses
all page networking and checks the saved company and role against the page title
and heading. It shows the destination without its query string and the detected
questions. Confirm this is the same application, then authorize fresh analysis.
The separate owner signature binds the packet revision, full current URL, form
structure and current document. Changed questions, URLs and same-URL reloads
invalidate old previews. AGY's delegated bearer alone cannot resume a new page.

New documents start with submission guards enabled. During explicit manual takeover
the runner's main-frame-only mode binding restores owner control after loading;
older replies cannot undo a newer review pause. Approval enables analysis of that
page, leaves networking isolated and requires an explicit answer review before
filling. It never infers that the previous step was saved or the application was
submitted. Cross-origin pages, embedded forms, missing company/role context and
CAPTCHA/authentication challenges still require manual handoff. Cancel closes the
dedicated resources as usual.

The canonical job/application URL remains unchanged. Protected analysis stores a
bounded resumption history with capture/URL hashes and revisions, without saving
browser actions or form values. After a process restart, opening the browser starts
at the canonical URL; no prior server save, navigation or submission is replayed.
Navigate to your saved step manually and review it again. At most 20 page resumptions
are accepted per packet. Submitted and unknown-outcome packets remain locked.

`backend/venv/bin/python backend/scripts/verify_browser_navigation.py` demonstrates
this with the actual local API, disposable PG17 and Chromium. Its fictional owner
performs one server save; signed resumption analyzes and fills step two while final
submission remains blocked. The dashboard test uses a fixed fixture-only action
to simulate that owner save. That test route accepts no browser/script/selector
input and is never installed by the normal application.


Analysis stores a sanitized structural inventory, observed URL/title/heading,
field-to-packet links and validation diagnostics in protected `owner_preferences`.
It does not store raw HTML, website scripts, form values, cookies or screenshots.
Source questions and candidate answers stay in the existing protected packet rows.
Browser profile directories are app-owned (0700); existing unmarked roots and
symlink roots are rejected. Do not point the profile root at personal Chrome.

During automation, native submit/Enter handlers and network writes/navigation are
blocked, WebSockets and service workers are blocked, downloads are disabled, and
only the configured origin is reachable. The browser pins the approved hostname
to a validated address and disables proxies to prevent DNS rebinding. This can break sites with autosave or
third-party form dependencies; use manual handoff. Browser automation is not a
sandbox for a compromised employer or browser. Allow only reviewed destinations.

A disconnect or restart retains packet/analysis data but does not replay any action.
Reopen and reanalyze. An interrupted fill records its intent and diagnostic; values
may already be present on the website. No automatic submission or retry occurs.
The runner is single-process, capped at two open sessions; PostgreSQL packet locks
and revision checks serialize edits. It is not a distributed browser worker.

## Optional AI and privacy

Factual fields use approved saved facts and never need a model. Existing grounded
answer generation validates citations, quoted claims, names, numbers, output size,
and unsupported accomplishments. Website/job strings are untrusted data, never
instructions or tools. Review remains mandatory; grounding checks are conservative
safeguards rather than proof. Generation uses saved or separately reviewed
company/job context. External source reading requires its own explicit approval.
A conflicting company name or
description for a saved job is rejected before any model call.

With `OPPORTUNITY_CONTEXT_ENABLED=true`, an open dedicated session offers
**Company and job evidence for AI answers → Capture job context**. Only explicit,
visible public job/company description sections are captured (for example
`#job-description`, `[itemprop="description"]`, `#company-description`) or bounded
sections under known headings such as “About the role” and “About us”. Repeated
heading labels and conflicting explicit descriptions require manual review. There is
no whole-page fallback, off-site crawler, private form-value collection or automatic
account access. Multiple conflicting sections or missing company/role identity in
the page heading/title require manual preparation.

Check the source and excerpts, shorten them if necessary, and approve them using
the dashboard's separate owner-signing key. New text cannot be attributed to the
website. The server recaptures the page and compares the exact digest before
saving; changed content requires fresh review. This updates protected existing
job metadata, preserves a protected evidence snapshot for saved answers, refreshes
the packet revision and invalidates old answer approvals. It does not overwrite
the discovery description or create candidate facts. Evidence expires after 14 days
and becomes unusable when the saved company, domain, role, URL or description changes.

Company-specific generation retrieves relevant verified candidate projects plus
this separately typed opportunity evidence. Applicant claims are validated against
candidate evidence only. Employer claims currently require complete verbatim source
sentences without first/second-person pronouns, in separate sentences with their own
references; mixed clauses or employer paraphrases require manual editing. Known
instruction-like text is rejected, all website text remains untrusted, and the model
has no browser tools or secret access. Source URLs (which may contain invitation tokens) remain local and are omitted
from provider prompts; opaque evidence IDs link proposals back to saved sources.
These checks are conservative safeguards; the owner must review the answer. Saved answer drafts expose their source excerpts
under **View employer evidence**. Existing general answer generation remains usable
when this opt-in feature is disabled; it cannot cite employer evidence as applicant history.

For manually entered browser destinations, use **Save field review** before filling
review-required answers. Capturing source text does not upgrade source confidence
or authorize the stricter packet handoff/submission gate. The existing database
guard for independently consistent posting sources remains unchanged.

The complete fictional context/fill proof can be run against disposable PG17 with
`backend/venv/bin/python backend/scripts/verify_browser_opportunity.py` and the
`PROFILE_TEST_DATABASE_URL` shown below. It uses an injected fictional provider,
not live Ollama or a paid service. It verifies signed context approval, generation,
field review, the actual filled browser value and durable source evidence.

For an official company page separate from the application, explicitly configure
up to eight exact public URLs after reviewing their access rules:

```dotenv
COMPANY_SOURCE_FETCH_ENABLED=true
COMPANY_SOURCE_URLS=["https://official-employer.example/about"]
```

Keep `OPPORTUNITY_CONTEXT_ENABLED=true`. In the same evidence panel, select the
configured page, confirm that it belongs to this employer and permits automated
reading, and click **Read approved company source**. This requires a separate
single-use owner signature; the delegated AGY/API bearer cannot authorize it.
Then review the company excerpt alongside the application-page job excerpt and
save them. The saved notice appears after the packet refresh completes; generating
immediately afterward uses the current revision. A company source never establishes
candidate experience or an account connection. Unknown employer domains stay unknown.

The reader sends at most two credential-free GETs: `/robots.txt` and the exact
configured document. It forwards no Chrome cookies, authorization, referrer, resume
or candidate facts. All DNS answers must be public and the connection stays pinned
to a validated address with hostname/TLS checking. Production sources require HTTPS;
literal loopback HTTP is reserved for testing. Query strings, fragments, credentials,
account/API paths and restricted portals are rejected. Redirects, authentication,
CAPTCHA/MFA markers, rate-limit responses, unsupported encodings/types and dynamic
descriptions pause for manual reading. There is no script execution or link following.

Robots rules do not grant access permission ([RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html#section-1)).
The implementation is deliberately stricter: it applies disallow rules from every
group, never overrides them with allow rules, and hands off when rate directives or
unsupported rule syntax occur. A missing robots file still requires the configured
operator permission and the explicit owner confirmation. It is not a general crawler.

Responses are bounded to 64 KiB for robots and 512 KiB for UTF-8 HTML, with bounded
worker lifetime, element/depth limits and at most 4,000 characters of extracted
company text. Forms, scripts and inline-hidden content are excluded. External CSS
and JavaScript are not rendered; unsupported layouts remain manual. The worker
inherits no application secrets. Cancellation closes and reaps it, including a
process that finishes starting after cancellation.

The current preview is reusable for ten minutes only while the packet revision,
application capture, browser instance/document and configured URL still match.
Identical preview retries do not fetch again. A protected database reservation
limits new reads to four per saved job per hour, at least sixty seconds apart;
restarting the browser does not reset this limit. Interrupted reads are never
replayed. Only final owner review saves the excerpt in existing protected job and
answer-evidence storage, with a distinct company-source URL and timestamp. No schema,
runtime grant or production migration was added. Disabling source fetching does not
erase already reviewed evidence; normal expiry/context checks continue to apply.

`backend/venv/bin/python backend/scripts/verify_company_source.py` demonstrates the
actual PG17/TCP/FastAPI/Chromium path from a fictional public source through signed
review, a grounded answer, PDF filling, one authorized mock application POST and an
independently verified V2 receipt with durable source attribution. It uses the same
disposable `PROFILE_TEST_DATABASE_URL` below and an injected fictional provider,
with no real account, model request or employer submission.

**Reviewed application answers** in My Profile lists saved drafts and supports
review, explicit reuse approval and revocation. Enable `APPROVED_ANSWER_REUSE_ENABLED`
only with the existing protected owner-preferences storage available. Approval
requires the same separate server-only owner key used by the dashboard consent
bridge; ordinary AGY/API bearer access cannot approve reuse. The bank uses bounded,
conservative intent matching for supported paraphrases with explicit skill/project
anchors, not general embeddings. Unknown wording falls through to normal grounded
generation. Factual answers and consent never use it. Reuse checks the current
profile version, all saved evidence, answer digest, style and output limits.
Company motivation is restricted to the exact saved job/company/description;
general profile narratives require an explicit general scope. A reused proposal
still requires review for every new application. Approvals do not authorize submission.

Common full-question paraphrases also share those existing intents: for example,
“Walk us through a project you built” can retrieve an approved project overview,
and “What attracts you to this role?” can retrieve motivation approved for that
exact saved job. Short professional introductions and challenging-project questions
have separate intents. This is a closed local grammar, with no embedding download,
network research or model call for a reuse hit. Extra employer names, dates,
experience qualifications, negation, salary questions or website instructions are
not stripped to make a match. Unrecognized wording follows normal grounding and
provider gates, or stays unanswered. Original questions and approval records remain
unchanged; factual questions continue to use structured facts.

Review/context checkboxes stay disabled while a browser operation refreshes its
packet and while answers have unsaved edits. Revision and dirty-state changes reset
these confirmations before the updated controls are displayed. Wait for an
operation to finish before confirming the current answers and company/job.

For a zero-subscription provider, install and run Ollama separately and select an
already installed local model:

```dotenv
LLM_PROVIDER=ollama
OLLAMA_ENABLED=true
OLLAMA_MODEL=qwen3:4b-instruct
LLM_MONTHLY_MAX_REQUESTS=200
LLM_TIMEOUT_SECONDS=80
```

Start the Ollama **daemon** with `OLLAMA_NO_CLOUD=1` and restart it after changing
that setting; putting it in this application's environment alone cannot configure
the daemon. See [Ollama's local-only instructions](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features).
Before sending a prompt the adapter queries loopback `/api/status` and `/api/show`:
cloud features must be explicitly disabled, local model metadata must exist and
remote model/host fields must be absent. Older daemons lacking the status endpoint
fail closed. Ollama's [official API types](https://github.com/ollama/ollama/blob/main/api/types.go)
describe those fields. Loopback alone does not prove local inference. Generation
calls only `http://127.0.0.1:11434/api/generate`, disables environment proxies and
redirects, and asks for the existing grounded JSON schema. Missing
models, malformed output and timeout return a reviewable failure, never invented
answers. The local adapter plans cited sentences before composing prose, constrains
reference IDs to the supplied candidate/employer evidence domains, and includes the
same schema in its prompt. Applicant/employer grounding checks still validate the
complete answer after generation. Input limits count the planning/schema overhead.
With `LLM_LOCAL_FALLBACK_ENABLED=true`, an explicitly configured remote primary can
fall back only to this verified local Ollama service after a provider/quota failure.
Both attempts share one deadline and retain separate durable usage budgets. No
local-to-remote fallback or model download is automatic. Results identify the actual
model used; validation failures never relax grounding to obtain an answer.

Live local acceptance was verified with **Ollama 0.40.9 and
`qwen3:4b-instruct` on an 8 GB Apple M1**. The model is separately downloaded;
see its [official model page](https://ollama.com/library/qwen3:4b-instruct) and
[Ollama download](https://ollama.com/download). Start the daemon explicitly with
cloud inference disabled, then pull the model in another terminal:

```sh
OLLAMA_NO_CLOUD=1 OLLAMA_HOST=127.0.0.1:11434 OLLAMA_CONTEXT_LENGTH=4096 OLLAMA_NUM_PARALLEL=1 OLLAMA_MAX_LOADED_MODELS=1 ollama serve
# In another terminal, while the daemon is running:
ollama pull qwen3:4b-instruct
```

On the implementation machine, the verified standalone binary and model cache are
in ignored `reports/local-ollama/v0.40.9/bin/` and `reports/local-ollama/models/`.
They are not included in Git. To use that cache from this worktree, invoke the
standalone binary's `serve` command with `OLLAMA_MODELS="$PWD/reports/local-ollama/models"`
and the same daemon settings above. No personal Chrome or AGY configuration is used.

With disposable local PG17 available, run:

```sh
backend/venv/bin/python backend/scripts/verify_live_ollama.py --model qwen3:4b-instruct
```

This opt-in command uses fictional candidate facts, a fresh child database, actual
TCP FastAPI and Chromium, and the real local model. It verifies source capture and
signed review, a grounded company draft, explicit field review/filling, persisted
draft/evidence/provider identity, a separate project answer, unknown compensation
and factual notice-period bypass. Two model requests are recorded durably; draft
reuse/submission approval is not automatic. The observed run took 73.7 seconds in
total with an 80-second limit per model call. Other hardware/models need their own
verification. The test-owned daemon was stopped after acceptance; there is no
automatic service/account activation. CI continues to use injected fictional models.

The complete generation-to-submission path has a separate explicit opt-in:

```sh
backend/venv/bin/python backend/scripts/verify_live_ollama.py --model qwen3:4b-instruct --complete-mock-application
```

This submits **one fictional application to the local V2 mock employer**, using
the actual local model and application services. It captures and approves the mock
company/job source, generates a grounded answer, verifies that unreviewed output
cannot fill the textarea, explicitly reviews the answer/PDF, selects consent through
the signed owner operation, authorizes the exact application and verifies the
independent server receipt. Repeated commands do not dispatch again; the saved draft,
source evidence, selected PDF digest and `applied_verified` packet survive browser
closure. The local usage ledger records exactly one model request. On the same
Ollama/model/M1 configuration, the observed total was **71.9 seconds**. Review is
simulated explicitly by the fixture API; no real candidate/account was activated.
The test-owned daemon was stopped afterward. The default command without this flag
retains its generation-only, no-submission behavior.

Ollama's [structured-output guide](https://docs.ollama.com/capabilities/structured-outputs)
describes supplying the schema in both prompt and format. Unaccepted local drafts
remain validation failures; earlier free-prose probes were rejected rather than filled.

Cohere is **evaluation-only in ENVIRONMENT=testing**. Its factory and transport both
require `COHERE_EVALUATION_ENABLED`, `COHERE_TRIAL_KEY_CONFIRMED`,
`COHERE_DATA_SHARING_APPROVED`, an explicit `COHERE_MODEL`, and `COHERE_API_KEY`.
Keep all off until the owner approves both provider and data sharing. Only selected
approved evidence is sent, never raw PDFs, cookies or full browser pages. The code
cannot determine an account's key entitlement; the trial-key attestation must be
verified by the owner. No upgrade or paid mode is implemented.

As checked on 2026-10-23, Cohere documents trial keys as limited to **1,000 calls per
month**, with listed Chat models at **20 requests/minute**; production keys are
paid. Trial keys are not permitted for production/commercial use. See official
[rate limits](https://docs.cohere.com/docs/rate-limits),
[pricing](https://cohere.com/pricing) and
[Chat API](https://docs.cohere.com/reference/chat). Recheck before enabling any
account. A 429 persists a cooldown and never retries automatically; request budgets
reserve before transport in protected owner storage. All optional models retain the
existing concurrency/deadline controls. Gemini remains the independent existing
explicit-generation path. It now additionally requires `GEMINI_ENABLED=true` and
`GEMINI_APPROVED_MONTHLY_REQUESTS` greater than zero. Its request budget is capped
at the smaller of that approval and `LLM_MONTHLY_MAX_REQUESTS`. No paid provider is
required by browser analysis or filling.

## Public assets needed to render a form

Some permitted employer pages render their form using public scripts, stylesheets
or fonts served from a separate origin. After checking those origins' access rules,
the operator can configure at most eight exact HTTPS origins:

```dotenv
BROWSER_ASSET_ORIGINS=["https://static.example.com:443"]
```

The placeholder above establishes no permission. The default is an empty list;
website text cannot extend it. The authenticated local policy endpoint exposes the
configured origins and bounds without opening Chrome. The dashboard requires a
separate owner checkbox before opening, and sends the current policy digest.
Changing the policy invalidates that approval. CLI clients first retrieve the
policy and include `confirm_asset_permissions: true` and `asset_policy_digest` in
the reviewed `open_application` JSON. Neither approval enables submission.

During initial loading only, a separate subprocess retrieves permitted main-frame
GET requests for `.js`/`.mjs`, `.css`, or `.woff`/`.woff2`/`.ttf`/`.otf` files with
matching MIME types. It receives no browser cookies, authentication or referrer;
it inherits no application secrets. It connects to a validated public numeric IP
while retaining hostname/TLS verification. Only the public application Origin is
forwarded when needed for native CORS. The browser must still honor the server's
CORS/resource policies; the relay never invents permission headers. Cookies and
redirect/authentication headers from asset responses are discarded.

Bounds are 4 MiB per asset, 32 MiB and 128 attempts per session, four concurrent
fetches and a ten-second parent deadline. Queries, redirects, private/mixed DNS,
authenticated responses, compressed bodies, unsupported MIME types, fetch/XHR,
images, workers and embedded documents are blocked. Literal loopback HTTP is
accepted only by testing fixtures. Relay failures expose fixed categories and
numeric counters, without remote bodies or private URL/header diagnostics.

Analysis, filling, review and Take Over permanently close this asset-loading
phase for the session. Closing/cancelling also kills and reaps admitted workers,
including workers still spawning. Later external dependencies remain blocked;
Take Over does not reopen their access. Use the normal employer page manually
outside the runner if it requires these dependencies. This supports a bounded
class of public asset-loaded forms, not arbitrary ATS integrations.

The PG17/TCP/FastAPI/Chromium demonstration uses fictional separate-origin JS/CSS,
checks absent outbound credentials and rejected response cookies, fills approved
facts/PDF, and verifies durable manual-handoff tracking. It also invokes the real
policy CLI without an owner-signing key:

```sh
backend/venv/bin/python backend/scripts/verify_browser_assets.py
```

Set the disposable `PROFILE_TEST_DATABASE_URL` described below. No real employer
submission or model request occurs. The Next.js browser suite includes the owner
policy approval and actual rendered-form filling path.

## AGY orchestration

The installed AGY reports **1.4.5** on the latest local check (the initial audit saw
1.4.4). `agy --help` exposes shell-based agent operation
and `agy mcp --help` exposes MCP configuration. This audit did not establish a direct
Chrome-control capability or modify AGY's configuration. Use its shell integration
with our narrow CLI; no browser MCP or unrestricted filesystem/cookie tools are
required. AGY must use the same application authorization and revisions as the UI.

```sh
# Existing API token supplied in the private process environment, never on argv.
backend/venv/bin/python -m backend.scripts.browser_assistant get_browser_policy
backend/venv/bin/python -m backend.scripts.browser_assistant get_application_status --packet-id UUID
backend/venv/bin/python -m backend.scripts.browser_assistant get_browser_operation --packet-id UUID
backend/venv/bin/python -m backend.scripts.browser_assistant analyze_application --packet-id UUID --revision N
backend/venv/bin/python -m backend.scripts.browser_assistant fill_application --packet-id UUID --revision N --reviewed-values --confirmed-page-context
backend/venv/bin/python -m backend.scripts.browser_assistant cancel_application --packet-id UUID --revision N
```

For an active command, use its `expected_revision` from `get_browser_operation`;
when that value is null, use the reported packet revision.
The cancellation CLI retrieves and binds the active operation ID itself. It cannot
cancel a newer operation with a stale revision/ID. Idle cancellation uses the current
packet revision. Operation status exposes command IDs and flags, without private answers.

The disposable PG17 cancellation demonstration also runs the real CLI as a narrow
subprocess against the actual local API:

```sh
backend/venv/bin/python backend/scripts/verify_browser_cancellation.py
backend/venv/bin/python backend/scripts/verify_browser_cancellation.py --after-dispatch
```

Set `PROFILE_TEST_DATABASE_URL` to the disposable `candidate_profile_test` database
described below. These commands create and remove child databases, use fictional
facts and local mock employers, and verify unknown-outcome persistence/receipt-only
recovery. They perform no real employer submissions or model calls.

`prepare_application` and `open_application` read bounded JSON from stdin, using
the same contracts as the API. `preview_application`, `take_over_application` and
`submit_approved_application` are also exposed. Real employer submission always returns the
backend's unsupported/unauthorized response. Default CLI output contains status
and IDs only; `--include-private-answers` explicitly includes protected answer data.
Do not grant AGY broad Chrome access or use its permission-bypass flag. Instructions
found in job descriptions/forms must never become shell commands or approvals.

## Reproducible fictional verification

```sh
docker run --detach --name automated-apply-browser-pg17 \
  --publish 127.0.0.1:55447:5432 \
  --env POSTGRES_PASSWORD=browser_test_only \
  --env POSTGRES_DB=candidate_profile_test \
  --tmpfs /var/lib/postgresql/data postgres:17-alpine
# Continue when this reports accepting connections.
docker exec automated-apply-browser-pg17 pg_isready -U postgres
backend/venv/bin/python -m playwright install chromium
export PROFILE_TEST_DATABASE_URL=postgresql://postgres:browser_test_only@127.0.0.1:55447/candidate_profile_test # pragma: allowlist secret — fictional local test value # pragma: allowlist secret — fictional local test value
backend/venv/bin/python backend/scripts/browser_mock_demo.py
backend/venv/bin/pytest backend/tests -q
pnpm --dir frontend run build
PYTHON="$PWD/backend/venv/bin/python" pnpm --dir frontend run e2e
PYTHON="$PWD/backend/venv/bin/python" pnpm --dir frontend run e2e:browser
```

The demo refuses non-loopback/non-test databases and non-PG17 servers, creates a
uniquely named child database, applies historical migrations there, and deletes it
afterward. It tests the actual TCP FastAPI, real Chromium, approved PDF filling,
concurrent revision admission, concurrent optional-model budget reservations,
manual mock submission, receipt `MOCK-ONLY-123`, owner reporting, and persistence
after closing the browser/database engine. It checks anonymous/client access is
absent. The dashboard journey uses the same fictional PG fixture and real Next.js
production server/BFF. No CI test submits a real job application.
Use the backend virtual environment for both browser suites; the system Python may
lack the application's dependencies. Run browser groups sequentially. After all
commands stop, remove only the disposable container created above with
`docker rm --force automated-apply-browser-pg17`.

Other fixtures exercise changing questions, native choices/date inputs, custom
widgets, multi-step handoff, consent, CAPTCHA/password pages, resume accept rules,
unsafe destinations, wrong context, disconnected browsers, expired authorization,
replays, prompt injection, POST exfiltration and misleading confirmation text.
See [delivery status and next tasks](browser-assistant-delivery.md) for exact results
and the unfinished phases. Local verification is not Supabase or account activation.

## Authorized mock submission extension

This extension provides an authorized submission lifecycle **only for the
fictional loopback employer fixture**. Real employer adapters remain disabled.
The base Phase 9 catalog, migrations 001–011 and pinned R1/R2 SQL are unchanged.
A separate proposal at `backend/app/browser/migrations/001_mock_submission.sql`
adds execution grants/attempts and extends the existing packet lifecycle/evidence
constraints. It is deliberately outside the automatic migration inventory. The
local verifier applies it only in a newly created disposable PG17 child database.
Installing it in a real database or accepting its runtime ACL/catalog would require
separate review/authorization; current production readiness rejects that drift.

The separate local proposal `backend/app/browser/migrations/002_mock_narrative.sql`
adds V2 alongside V1 only in fresh disposable fixtures. It preserves the original
V1 proposal, binds the signed grant's adapter to the execution record, and requires
the corresponding receipt version in both execution and packet guards. It adds no
roles, grants or policies and is also outside the production migration inventory.

Run the fully integrated fictional lifecycle, including wrong-receipt recovery:

```sh
PROFILE_TEST_DATABASE_URL="$PROFILE_TEST_DATABASE_URL" \
  backend/venv/bin/python backend/scripts/verify_browser_submission.py --receipt-mode wrong
# Twelve dashboard journeys, including grounded generation through a verified V2 receipt.
PROFILE_TEST_DATABASE_URL="$PROFILE_TEST_DATABASE_URL" \
  pnpm --dir frontend run e2e:browser
```

`BROWSER_MOCK_SUBMISSION_ENABLED` defaults off. Even when true, it works only in
`ENVIRONMENT=testing`, on an explicitly allowed literal `127.0.0.1` origin, at the
exact `/mock/apply` or `/mock/v2/apply` route with its documented form and receipt protocol.
No environment flag enables a real employer destination.

| Protocol | Controls in exact order | POST path | Receipt fixture |
|---|---|---|---|
| V1 | name, email, approved PDF, consent | `/mock/applications` | `automated-apply-employer-v1` |
| V2 | name, email, company-specific narrative (maximum 1,000 characters), approved PDF, consent | `/mock/v2/applications` | `automated-apply-employer-v2` |

Only the two reserved attempt/digest identifiers are additional hidden fields. V1
does not accept a narrative or V2 receipt. V2 does not accept missing/extra controls
or a V1 receipt. The fictional receiver independently validates its V2 field set,
required narrative/consent and PDF content/type before recording a receipt.

The combined deterministic proof uses an explicitly injected fictional provider:

```sh
backend/venv/bin/python backend/scripts/verify_complete_application.py
backend/venv/bin/python backend/scripts/verify_complete_application.py --receipt-mode wrong
backend/venv/bin/python backend/scripts/verify_complete_application.py --multiline-answer
backend/venv/bin/python backend/scripts/verify_complete_application.py --receiver-contract
```

The first three commands use `PROFILE_TEST_DATABASE_URL`, actual TCP FastAPI,
dedicated Chromium and a fresh PG17 child. They cover source approval, grounded
generation, answer review, selected encrypted PDF, signed consent/grant, concurrent
idempotent requests, one actual mock POST, receipt verification and persisted
tracking/drafts/evidence. The wrong-receipt case remains unknown, rejects resubmission
and verifies receipt-only recovery in a new interpreter. Direct SQL negative checks
prove adapter/grant and cross-version receipt guards reject substitutions. The last
command exercises only the independent loopback receiver and needs no database.

The workflow is Analyze → Fill → explicit owner consent → Review exact submission
→ Authorize mock submission → Submit → Verify independent receipt. Consent is
never inferred by Fill. A direct owner action can select/clear a detected native
checkbox through the dashboard; this updates the existing packet answer/revision
and audit history. Each selected consent/radio answer is reviewed again in the
exact submission preview. Missing required consent or browser validation blocks
submission. Other unsupported controls require manual handoff.

A two-minute, single-use grant binds the packet revision, saved candidate/job
context, exact destination, form structure, actual values, resume SHA256 and selected
consents. The outgoing multipart body is independently checked against that digest
before the runner permits its one allowed POST. Changed values, a wrong resume,
expired/revoked grants or mismatched proof never authorize a different application.
No raw resume bytes, hidden form tokens or grant tokens are retained in evidence.

Payload hashing follows the browser's [native multipart newline normalization](https://html.spec.whatwg.org/multipage/form-control-infrastructure.html#multipart/form-data-encoding-algorithm)
so multi-paragraph answers match the outgoing bytes. Submitted text and consent
values must also match their visible reviewed controls: a `formdata` listener cannot
replace an answer, email or checkbox value invisibly before authorization. After
submission or an unknown outcome, preparation/filling controls remain disabled;
status, receipt-only recovery and cancellation retain their existing roles.

### Owner review and delegated AGY access

The application bearer is insufficient to mint a grant or select consent. These
operations additionally require a fresh single-use proof from the authenticated,
CSRF-protected Next.js gateway, using a separate server-only
`BROWSER_OWNER_APPROVAL_KEY` (at least 32 characters). Configure the same secret
in the backend and frontend processes when activating owner consent controls;
never export it to the AGY process or a client bundle. Keep keys in ignored private
configuration, not candidate facts. The fictional fixture supplies its own test key.

The gateway signs the exact operation, body digest, timestamp and random nonce.
The backend rejects changed bodies, expired signatures and consumed nonces. The
CLI can prepare/fill/preview and execute an already approved grant supplied through
bounded stdin; it cannot authorize a submission. Neither AGY nor a website string
may turn its normal API bearer into owner approval.

```sh
# Read-only exact preview: JSON with expected_revision and confirm_page_context on stdin.
backend/venv/bin/python -m backend.scripts.browser_assistant review_submission --packet-id UUID
# Owner-approved expected_revision/grant_id/grant_token/idempotency_key JSON on stdin.
backend/venv/bin/python -m backend.scripts.browser_assistant submit_approved_application --packet-id UUID
backend/venv/bin/python -m backend.scripts.browser_assistant recover_submission --packet-id UUID
```

### Durable outcomes and recovery

Dispatch is committed before browser I/O. A unique packet/attempt/grant constraint
plus PostgreSQL locks prevents duplicate dispatch, including requests with different
idempotency keys. A successful click or receipt-looking page is insufficient: the
adapter queries an independent server receipt and matches its attempt ID and digest.
The mock server computes that digest from the actual uploaded multipart contents.

The existing packet transitions through `submitting` to
`provider_confirmed_submitted` or `submission_unknown`. Verified mock evidence is
explicitly `mock_employer` / `mock_receipt_verified`, distinct from the historical
`user_reported` / `self_reported_unverified` evidence. It does not imply a real
employer application. Unknown submissions cannot be edited, reauthorized or replayed.
Receipt recovery can promote unknown → verified without opening a browser or clicking
again. At startup, expired dispatch leases become unknown; no submission is resumed.
Cancelling before dispatch revokes unused grants. Cancelling after dispatch retains
an unknown/verified outcome rather than pretending an external action was undone.
