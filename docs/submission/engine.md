# Verified fixture submission engine

This milestone executes genuine application POSTs against disposable numeric-loopback fixtures. It does not enable real employer submissions. Keep #18, #22 and #23 unmerged; this change stacks on #23 at `d73d9e371bc99d7dfb065781da31691d25172bcb`.

## Authorization and review

`submit_application` is a separate capability, controlled by `BROWSER_SUBMIT_ENABLED=false` by default. Execution additionally requires `BROWSER_AUTOMATION_ENABLED`, `ENVIRONMENT=testing`, an exact `BROWSER_FIXTURE_ORIGIN=http://127.0.0.1:<port>`, and a recognized `/fixtures/{greenhouse|lever|google}/{company}/jobs/{job}/apply` contract. A capability flag cannot enable live destinations. No deployment or production DDL is part of this change.

The existing preparation, grounding, profile confirmation, project review, canonical PDF verification and field-fill services are reused. After successful filling, the browser seals the inspected form, exact final control, native values and canonical PDF checksum in its isolated world. Only a complete, unchanged supported document with a confirmed private PDF and known employer produces a submission review.

Agent → Submission review shows the employer, job, exact application and POST URLs, selected application ID, candidate and packet versions, document/project/PDF digests and expiry. Review the visible values/narratives in Chrome and the adjacent field plan. Check the review acknowledgment and choose **Authorize this one application**. This authenticated owner interaction issues a backend authorization; it does not click Submit. Choose **Submit this approved application**, or use the exact Telegram command for the saved search position.

Each grant binds the singleton authenticated owner, issuing actor, employer ID/name, job ID/title, packet ID/revision, profile ID/version, candidate context digest, approved project digest, PDF checksum, filled document ID/digest, adapter, exact origin/URLs, source campaign ID/revision, scope `submit_application`, maximum count **one**, expiry, nonce, review digest and single-use idempotency/correlation key. Approving another selection requires another exact interaction. Neither “yes” nor a Cohere interpretation can issue a grant. Model tool proposals cannot execute submission.

Only the dedicated Chrome worker has a submission transport. MV3/manual extension and the native protocol acquire no submission authority. The extension public key, stable ID and permissions remain unchanged. LinkedIn remains discovery-only; Gmail send approval is unchanged. No login, CAPTCHA, MFA or sensitive-attestation bypass is supported.

## Execution and evidence

The durable application state is:

`prepared → form_inspected → form_filled → awaiting_submission_approval → submitting → submitted | submission_uncertain | manual_required | failed`

The first three events reference work already completed by the existing packet/form services. Each transition adds an insert-only `agent_operations` entry. One stable private `owner_preferences` record per application packet prevents new Telegram deliveries, plans or workers from resetting an attempt. Approval is bound to its review digest and cannot broaden its count or application selection.

Claims serialize through the owner memory row and PostgreSQL row locks. An MVCC check sees active leases even when `SKIP LOCKED` excludes their rows. A fenced 45-second dispatch intent commits before browser IO. A bounded transaction linearizes owner cancellation with the final browser RPC; an already dispatched request cannot be recalled. Lease expiry or process loss invalidates the fence and records uncertainty without another POST.

Immediately before clicking, the worker revalidates candidate/profile/project/packet/PDF versions, employer, destination, campaign revision/cancellation, expiry and the owner grant. The isolated browser code checks native validity, required fields, reviewed values, exact document/control identity, control metadata and PDF bytes again. Missing/changed/custom/sensitive flows require manual action. There are no client- or model-supplied selectors, scripts or navigation commands.

Network access remains default-deny. Chromium can internally replay a continued POST after an empty socket response. The gate therefore performs the intercepted native request through a single `route.fetch(maxRetries=0, maxRedirects=0)` and fulfills the original navigation; a transport error aborts it. No continued browser POST can silently bypass the single-use gate. The short-lived gate permits one main-frame POST to the exact fixture action with the reviewed successful controls, plus at most one exact same-origin GET confirmation redirect from that POST. Redirected writes, unrelated GET navigation, popups, sockets, autosave and external writes remain blocked. CDP omits multipart file contents from intercepted request metadata. For multipart forms the gate checks native field/file metadata and rebuilds the outgoing body from the retained, checksum-verified private canonical PDF. It never forwards unknown page-supplied binary. Temporary PDFs remain private until Chrome closes; task-named orphan uploads are removed on next dedicated-profile startup.

Supported fixture semantics:

| Adapter | Final control | Authoritative acknowledgment |
| --- | --- | --- |
| Greenhouse-like | `form#application_form`, native `button#submit_app` | Exact POST JSON response: received status, application ID and matching correlation |
| Lever-like | `form#lever-application`, native `button#lever-submit` | Exact 303 confirmation destination; validated accepted response, application ID and matching correlation |
| Google Forms-like | Native fixture form `#google-form` with role=form, final role/button `#google-submit` | Exact known confirmation page body with receipt ID and matching correlation |

These contracts describe controlled structures, not independently accepted live portal behavior. An HTTP 200, arbitrary success text, a click, a generic thank-you page or a model completion message cannot mark an application submitted. Known correlated validation/rejection responses produce `failed`. Navigation/connection failure, timeout, process crash, unexpected network activity or ambiguous acknowledgment produces `submission_uncertain`.

Sanitized receipts contain evidence type, exact destination, timestamp, employer application ID and correlation ID. Raw HTML/JSON responses, field values, candidate data and request bodies do not enter audit receipts. The private reviewed field plan continues to hold its existing owner-visible values.

Fixture receipts use the existing append-only private operation ledger. The preexisting packet-table prohibition on provider-confirmed submissions remains intact: no fixture receipt is mislabelled as a live provider acceptance. The separate submission dashboard/Telegram status is authoritative. Fictional successfully submitted jobs are excluded from new discovery/preparation through saved job status.

## Recovery and Telegram

- “Show applications ready to submit.” lists persisted submission reviews/outcomes.
- “Submit the approved application for job 2.” resolves position 2 from saved search IDs and releases only an already-authorized exact application. It cannot authorize a new selection.
- “Did my application get submitted?” reads the persisted result/evidence.
- “Stop the remaining submissions.” revokes pending authorization, fences active attempts and preserves uncertainty for requests that may already have crossed the network.

The dashboard's **Check receipt without resubmitting** performs a bounded, no-proxy, no-redirect GET to the contract's exact loopback receipt endpoint. A correlated authoritative accepted receipt can resolve uncertainty to submitted, even after cancellation. A missing/rejected/ambiguous receipt leaves uncertainty and requests manual verification. No automatic second attempt exists, including after an inconclusive 404. A new authorization cannot reset a terminal or uncertain application record.

Result notifications are generated from persisted submission states and carry evidence only after verification. A stable per-outcome outbox identity deduplicates repeated completion publication across source and command campaigns. Actual Telegram network delivery still has its existing ambiguous-send handling; fictional tests exercise intake and the durable notification outbox without contacting Telegram.

## Verification commands

All data is fictional. Never aim these commands at a real database or employer.

```sh
PYTHON=<repository-python> pnpm -C extension test
pnpm -C extension build
python backend/scripts/run_browser_acceptance.py
PROFILE_TEST_DATABASE_URL=postgresql://...@127.0.0.1:<port>/candidate_profile_test python backend/scripts/verify_submission_postgres.py
pytest backend/tests -v
pnpm -C frontend test
pnpm -C frontend typecheck
pnpm -C frontend format:check
pnpm -C frontend build
PYTHON=<repository-python> pnpm -C frontend e2e
```

The Chrome runner and restricted PostgreSQL submission verifier use `/tmp/automated-apply-heavy-tests.lock`. Full backend/frontend heavy runs must acquire that lock too. The PostgreSQL verifier creates a task-named child database, applies the unchanged existing bootstrap only there, uses its restricted runtime role, and drops the child database afterward. No production migration, expanded grant or hosted rollout is required or performed.
