# Local browser application assistant — assisted milestone

This feature adds working **Analyze → reviewed Fill → Review → Take Over** on
explicitly permitted employer forms. It reuses saved candidate profiles, confirmed
resources, encrypted private PDFs, packet answers, revisions, audit events,
readiness and owner-reported submission tracking. It does **not** enable automatic
real employer submission. A separately gated fictional submission extension is described below. The Submit control is disabled, its API returns 403, and the
existing PostgreSQL guard against provider-confirmed submission remains intact.

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
   consent, CAPTCHA, MFA, custom widgets and further steps yourself. Analyze again
   for an in-page step at the original URL. Redirected steps require manual work.
7. Submit manually on the employer website. A click, success text, or navigation
   never marks the packet submitted. Record your actual receipt using the existing
   explicit submission report. It remains `user_reported_submitted`, not provider
   verification. **Cancel** closes the browser session; packet history remains.

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
adds no company scraper, semantic approved-answer reuse or automatic research.

For a zero-subscription provider, install and run Ollama separately and select an
already installed local model:

```dotenv
LLM_PROVIDER=ollama
OLLAMA_ENABLED=true
OLLAMA_MODEL=your-installed-model
LLM_MONTHLY_MAX_REQUESTS=200
LLM_TIMEOUT_SECONDS=30
```

The adapter calls only `http://127.0.0.1:11434/api/generate`, disables environment
proxies and redirects, and asks for the existing grounded JSON schema. Missing
models, malformed output and timeout return a reviewable failure, never invented
answers. No model was downloaded or live generation verified during implementation.
Ollama is an explicit operating alternative, not an automatic fallback in this slice.

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
explicit-generation path with its existing durable budget; no paid provider is
required by browser analysis or filling.

## AGY orchestration

The installed AGY reports **1.4.4**. `agy --help` exposes shell-based agent operation
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
