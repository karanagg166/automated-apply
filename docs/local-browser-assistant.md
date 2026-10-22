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

Use Python 3.11+, Node 22+, local Chrome, and a separately authorized database.
The feature does not change the existing database safety checks or configure a
production database. Develop and test using disposable PostgreSQL 17 as below.

```sh
backend/venv/bin/pip install -r backend/requirements-browser.txt
npm ci --prefix frontend
```

Put configuration/API secrets in an ignored private environment file; keep career
facts in the protected profile/resource APIs. Never commit cookies or browser data.
With the existing owner token and frontend login configured, add:

```dotenv
BROWSER_ASSISTANT_ENABLED=true
BROWSER_ALLOWED_ORIGINS=["https://careers.example.com:443"]
BROWSER_CHANNEL=chrome
BROWSER_HEADLESS=false
BROWSER_PROFILE_ROOT=reports/browser-profiles
APPLICATION_SUBMISSION_ENABLED=false
```

The example hostname is a placeholder, not verified permission. Review the actual
employer's access rules before configuring its exact origin. Known restricted
portals (LinkedIn, Naukri, Wellfound, Instahyre, Internshala) remain manual-only,
even if added to this list. Cross-origin assets and embedded application frames
are unsupported in this milestone. No API key establishes an account connection.

Run the existing FastAPI backend with **one worker**, bound to `127.0.0.1`, and the
existing Next.js dashboard. Browser commands require loopback plus the existing
owner bearer; the dashboard uses its server-side BFF token and session/CSRF checks.
Do not expose the local browser API through public ingress.

```sh
backend/venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
npm run dev --prefix frontend
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
   **Open dedicated browser**. This launches a new app-owned Chrome profile. It
   never attaches to your default Chrome, unrelated tabs or an exposed CDP port.
   You can navigate manually after Take Over; assistance resumes only on the exact
   original URL. Pasting a URL is the supported entry point in this milestone.
4. Click **Analyze Application**. Visible native controls and unsupported custom
   controls appear in the browser panel and in the existing Application fields.
   Inspect each proposed answer and source; edit using the existing answer editor.
   Generate narrative drafts explicitly using the configured provider, then review.
5. Confirm the current answers/resume and that the observed page belongs to this
   company/job. Click **Fill supported fields**. Missing/invalid/unreviewed answers
   remain incomplete. A changing form interrupts filling and requires reanalysis.
6. Review the actual website, including its validation errors. **Take Over** permits
   manual actions on that origin and suspends automated filling. Complete required
   consent, CAPTCHA, MFA and unsupported controls yourself. Analyze again
   for an in-page step at the original URL. Redirected steps require manual work.
7. Submit manually on the employer website. A click, success text, or navigation
   never marks the packet submitted. Record your actual receipt using the existing
   explicit submission report. It remains `user_reported_submitted`, not provider
   verification. **Cancel** closes the browser session; packet history remains.

Labelled native radio groups and bounded ARIA radiogroups can use reviewed answers.
Custom comboboxes are supported when a unique `aria-controls` relationship points to
one single-select listbox with known, distinct choices. The engine selects only an
exact displayed option and checks the resulting browser value. Unlabelled/ambiguous
groups, missing or remotely loaded dropdown options, rich text editors and consent
or attestation choices stay manual. Native consent checkboxes still use the direct
owner control; no answer model or fill plan grants consent.

For a supported client-only multi-step form, use **Review next application step →
Preview next step** after filling. The preview shows actual browser values and
validation, including selected consents. Review these, then explicitly authorize
the displayed Next/Continue action. Only a single visible `button[type=button]`
labelled Next, Next step or Continue is eligible; submit controls, embedded forms
and ambiguous buttons require manual navigation. This operation needs the separate
dashboard owner signature and cannot be authorized by AGY's bearer alone.
Configuration rejects reusing the delegated API token as the owner signing key.

Filling and step review isolate **all page network requests**, including GET, until explicit
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
safeguards rather than proof. This milestone uses saved company/job context; it
adds no company scraper or automatic research. A conflicting company name or
description for a saved job is rejected before any model call.

With `OPPORTUNITY_CONTEXT_ENABLED=true`, an open dedicated session offers
**Company and job evidence for AI answers → Capture job context**. Only explicit,
visible public job/company description sections are captured (for example
`#job-description`, `[itemprop="description"]`, `#company-description`). There is
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

For a zero-subscription provider, install and run Ollama separately and select an
already installed local model:

```dotenv
LLM_PROVIDER=ollama
OLLAMA_ENABLED=true
OLLAMA_MODEL=your-installed-model
LLM_MONTHLY_MAX_REQUESTS=200
LLM_TIMEOUT_SECONDS=30
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
answers. No model was downloaded or live generation verified during implementation.
With `LLM_LOCAL_FALLBACK_ENABLED=true`, an explicitly configured remote primary can
fall back only to this verified local Ollama service after a provider/quota failure.
Both attempts share one deadline and retain separate durable usage budgets. No
local-to-remote fallback or model download is automatic. Results identify the actual
model used; validation failures never relax grounding to obtain an answer.

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

## AGY orchestration

The installed AGY reports **1.4.5** on the latest local check (the initial audit saw
1.4.4). `agy --help` exposes shell-based agent operation
and `agy mcp --help` exposes MCP configuration. This audit did not establish a direct
Chrome-control capability or modify AGY's configuration. Use its shell integration
with our narrow CLI; no browser MCP or unrestricted filesystem/cookie tools are
required. AGY must use the same application authorization and revisions as the UI.

```sh
# Existing API token supplied in the private process environment, never on argv.
backend/venv/bin/python -m backend.scripts.browser_assistant get_application_status --packet-id UUID
backend/venv/bin/python -m backend.scripts.browser_assistant analyze_application --packet-id UUID --revision N
backend/venv/bin/python -m backend.scripts.browser_assistant fill_application --packet-id UUID --revision N --reviewed-values --confirmed-page-context
backend/venv/bin/python -m backend.scripts.browser_assistant cancel_application --packet-id UUID --revision N
```

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
  --env POSTGRES_DB=candidate_profile_test postgres:17-alpine
backend/venv/bin/python -m playwright install chromium
export PROFILE_TEST_DATABASE_URL=postgresql://postgres:browser_test_only@127.0.0.1:55447/candidate_profile_test # pragma: allowlist secret — fictional local test value # pragma: allowlist secret — fictional local test value
backend/venv/bin/python backend/scripts/browser_mock_demo.py
backend/venv/bin/pytest backend/tests -q
npm run build --prefix frontend
npm run e2e:browser --prefix frontend
```

The demo refuses non-loopback/non-test databases and non-PG17 servers, creates a
uniquely named child database, applies historical migrations there, and deletes it
afterward. It tests the actual TCP FastAPI, real Chromium, approved PDF filling,
concurrent revision admission, concurrent optional-model budget reservations,
manual mock submission, receipt `MOCK-ONLY-123`, owner reporting, and persistence
after closing the browser/database engine. It checks anonymous/client access is
absent. The dashboard journey uses the same fictional PG fixture and real Next.js
production server/BFF. No CI test submits a real job application.

Other fixtures exercise changing questions, native choices/date inputs, custom
widgets, multi-step handoff, consent, CAPTCHA/password pages, resume accept rules,
unsafe destinations, wrong context, disconnected browsers, expired authorization,
replays, prompt injection, POST exfiltration and misleading confirmation text.
See [delivery status and next tasks](browser-assistant-delivery.md) for exact results
and the unfinished phases. Local verification is not Supabase or account activation.

## Authorized mock submission extension

The next milestone adds a complete authorized submission lifecycle **only for the
fictional loopback employer fixture**. Real employer adapters remain disabled.
The base Phase 9 catalog, migrations 001–011 and pinned R1/R2 SQL are unchanged.
A separate proposal at `backend/app/browser/migrations/001_mock_submission.sql`
adds execution grants/attempts and extends the existing packet lifecycle/evidence
constraints. It is deliberately outside the automatic migration inventory. The
local verifier applies it only in a newly created disposable PG17 child database.
Installing it in a real database or accepting its runtime ACL/catalog would require
separate review/authorization; current production readiness rejects that drift.

Run the fully integrated fictional lifecycle, including wrong-receipt recovery:

```sh
PROFILE_TEST_DATABASE_URL="$PROFILE_TEST_DATABASE_URL" \
  backend/venv/bin/python backend/scripts/verify_browser_submission.py --receipt-mode wrong
# Two dashboard journeys: assisted handoff, then exact authorization and mock receipt.
PROFILE_TEST_DATABASE_URL="$PROFILE_TEST_DATABASE_URL" \
  npm run e2e:browser --prefix frontend
```

`BROWSER_MOCK_SUBMISSION_ENABLED` defaults off. Even when true, it works only in
`ENVIRONMENT=testing`, on an explicitly allowed literal `127.0.0.1` origin, at the
exact `/mock/apply` route with the documented mock form and receipt protocol.
No environment flag enables a real employer destination.

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
