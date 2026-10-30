# Naukri worker: canonical PDF preflight integrated

**Implemented and tested; NOT INSTALLED. The full unattended application executor
is still incomplete.** This changes actual worker preparation code, rather than
promoting the earlier browser-only experiment to a production upload capability.
No new application or provider upload occurred. No provider outreach is planned
or requested.

Branch `fix/live-prepare-discovery-20261030`, base `main`,
[PR #48](https://github.com/karanagg166/automated-apply/pull/48).
Exact implementation:
[`8df57ce79b36f4986af1a06016bc9027abc8ac85`](https://github.com/karanagg166/automated-apply/commit/8df57ce79b36f4986af1a06016bc9027abc8ac85).
Baseline report:
[`c7df79afd3399b16bc0c3e21f22e87c283916b03`](https://github.com/karanagg166/automated-apply/commit/c7df79afd3399b16bc0c3e21f22e87c283916b03).
[Sanitized metrics](naukri-worker-resume-preflight-metrics-20261031.json).

## Actual integration gap and resulting behavior

The installed execution worker prepares packets and queues review/questions. It
does **not** execute the complete Naukri Apply/questionnaire/resume/submission
sequence. The earlier chooser-free helper is test-only and excluded from the
extension distribution. Browser experiment success therefore did not make the
worker capable of unattended application submission.

This increment connects canonical resume verification to the existing worker's
PREPARING path, under its current committed claim and owner/cancellation fence:

- `backend/app/execution/naukri_upload.py` checks the fresh packet, standing
  preparation-policy resume binding when present, resource ownership, unique
  confirmed primary selection, current resource revision, private-upload source,
  encryption-key availability, decrypted PDF header and stored byte checksum.
  It never fetches a linked resume, opens a file path or contacts a provider.
- It applies a conservative **2,000,000-byte** preparation limit. The observed
  Naukri UI said 2 MB, not an exact byte contract; this is deliberately a local
  conservative bound, not a claim about Naukri accepting boundary-sized files.
- `backend/app/execution/worker.py` now invokes that preflight after reading or
  creating the packet and persists `upload_preflight` on the existing execution
  record. Only versioned metadata is saved: packet/job/profile revision binding,
  resource revision, check time, size and checksum. No decrypted file bytes or
  candidate answers are stored in the execution journal.
- `backend/app/execution/recurring.py` exposes counts for recorded successful and
  input-required local preflights. They are observations at the recorded versions
  and time, not proof that the file is attached or that those versions remain
  current later. A future upload admission must revalidate all current bindings.
- `backend/app/execution/naukri.py` reports that canonical-PDF preflight is
  integrated with packet preparation. Unattended browser upload remains unverified.
- `backend/tests/test_naukri_upload_preflight.py` adds 16 regression cases using
  encrypted fictional PDFs, actual repositories/services, real worker preparation,
  committed leases and fresh sessions.

The preflight returns `PDF_VERIFIED_LOCAL` or `NEEDS_INPUT` with a fixed reason.
`browser_action_admitted` remains false. Existing manual review/handoff behavior
is preserved: an owner-approved URL can remain useful to its manual workflow,
but it is not silently downloaded or mislabeled as an unattended upload file.
This metadata grants no Apply, upload, submission or standing policy authority.

## Exact verification

Final focused backend run: **234 passed, 0 failed, 0 skipped, 22.61 seconds**
across the ten files in the reproduction command. This includes **16 new cases**
and 218 existing cases. They exercise correct bytes, stale packets, a foreign
profile context, changed resume and policy revisions, missing decryption key,
invalid encryption/header/checksum, unconfirmed private storage, excessive size,
the exact local size boundary, removed primary selection, approved links, worker
persistence through fresh sessions, and Pause fencing before PDF access.

The fresh-session worker case verifies persisted preflight metadata and checks
that no raw `%PDF` data or invented standing submission policy appears. It does
not simulate a provider receipt. External HTTP is denied by the test fixtures.

One added fixture initially attempted to create two primary resume resources and
failed the database's existing uniqueness constraint: **15 passed / 1 failed,
2.21 seconds**. The test was corrected to remove the primary selection through a
valid record change. The database constraint was not relaxed. The final 234-case
run includes the corrected case. A Ruff test-import ordering issue was fixed.

Ruff E9/F/I and `git diff --check` passed. OpenAPI/API types were regenerated and
frontend typechecking passed; regeneration produced no tracked API type change.
No frontend/extension source, permission, dependency or migration changed in this
increment. No frontend/extension suite, production build or hosted CI was rerun.
The prior 26 Chromium probe cases and earlier backend/frontend counts are retained
in their own reports and are not additional test counts for this milestone.

## Actual private-data-safe Mac observations

Two bounded read-only checks used the existing approved online PostgreSQL target
and installed localhost owner API. Operator engines used NullPool and one
connection at a time, closing before the next operation. No runtime pool or role
limit changed. No private UUID, PDF digest, profile facts, token or resume contents
are published.

1. Reading the existing QTrino packet through the installed API returned HTTP 200.
   The new preflight, evaluated as an operator read-only projection, returned
   **NEEDS_INPUT / packet_context_stale**, with no file read admitted by that
   preflight and no browser action. Packet GET plus evaluation took **6.484s**.
   This is a correct refusal to treat the historical packet as current. The
   exact cause of its changed context was not separately isolated, and its
   stale flag was not overridden to manufacture a passing result. QTrino's
   genuine receipt and applied status were not modified or replayed.
2. Independently select the current confirmed primary private resource using
   existing owner records, then use its normal authenticated resume-download
   route. It returned **HTTP 200**, `application/pdf`, a PDF header and **100,198
   bytes**, with a checksum equal to the confirmed private record. It is under
   the conservative preparation bound. The download took **1.465s**. Bytes were
   held in memory only, never written to disk or supplied to a provider.

These observations establish current canonical-file availability and refusal of
a stale historical packet. They do **not** establish a new eligible opportunity,
an installed-worker preflight run, genuine questionnaire/attachment retention,
Naukri submission, employer acknowledgment or locked-screen execution.

Installed services remain the previously verified approved
`90f2f2ade50a1c31b26ca85cc7fdf5e93bb67c20`; this implementation was not installed
and no service/native-host reference was changed or restarted. The last fresh
Profile 8 inventory in the preceding probe report still referenced historical
`b06909293b1866e8191277d17fc284c398b4307b`, matching 15/18 current files. No Chrome
restart, profile change, permissions change or desktop operation occurred here.
Locked-screen behavior and extended uptime remain **NOT TESTED**.

No new discovery cycle or candidate import was performed in this milestone.
Current real discovery count is **NOT MEASURED HERE**; the last published bounded
approved-source cycle returned zero. New real application attempts, provider
uploads, submissions, unknown/failed submission outcomes and operator-initiated
Telegram sends are all **zero**. The known prior genuine count is one supervised
QTrino Naukri record, with zero installed recurring-worker submissions. No fresh
provider status reconciliation is claimed.

The two read-only timings cover different operations and are not a before/after
performance comparison. Production resource/timing comparisons and sustained
five-connection acceptance are **NOT TESTED** in this increment.

## Reproduction

```sh
backend/venv/bin/python -m pytest \
  backend/tests/test_naukri_upload_preflight.py \
  backend/tests/test_naukri_receipts.py \
  backend/tests/test_local_gmail_discovery.py \
  backend/tests/test_naukri_recurring.py \
  backend/tests/test_execution_naukri.py \
  backend/tests/test_naukri_ready_workflow.py \
  backend/tests/test_naukri_reviewed_facts.py \
  backend/tests/test_application_handoff.py \
  backend/tests/test_application_packet_review.py \
  backend/tests/test_browser_forms.py -q
backend/venv/bin/python -m ruff check --isolated --select E9,F,I \
  backend/app/execution/naukri_upload.py backend/app/execution/worker.py \
  backend/app/execution/recurring.py backend/app/execution/naukri.py \
  backend/tests/test_naukri_upload_preflight.py
backend/venv/bin/python backend/scripts/export_openapi.py
pnpm -C frontend api:types
pnpm -C frontend typecheck
git diff --check
```

Read-only owner inspection uses `GET /api/v1/application-packets/{existing_id}`
and `GET /api/v1/dashboard/resumes/{confirmed_private_id}` with existing local
authentication. Do not publish those IDs or authentication, raw responses, PDF
bytes, profile data or private digests. Never reconstruct this check by clicking
Apply or uploading a resume to the already-applied QTrino requisition.

## Acceptance and unresolved boundaries

| Check / completion gate | Verdict | Exact limit |
| --- | --- | --- |
| Canonical-PDF checks integrated into worker preparation | PASS implementation/fixtures | Fresh persisted workflow; source uninstalled |
| Current real confirmed primary file available | PASS read-only | 100,198 bytes; matching private-record checksum; no provider upload |
| Historical stale QTrino packet fenced | PASS read-only | NEEDS_INPUT; no stale flag override or reapplication |
| Receipt/provenance preservation and no replay | PASS relevant regressions | No genuine receipt changed; no new application |
| Platform route/permission (A) | UNRESOLVED | Original gate remains unless explicitly changed; no provider outreach requested |
| Complete installed recurring application executor (B) | NOT IMPLEMENTED / NOT INSTALLED | Apply, live UI variant handling and upload dispatch remain pending |
| Real Naukri retained attachment/questions while locked (C) | NOT TESTED | File availability and browser primitives are separate prerequisites |
| Multiple distinct worker-recorded applications (D) | NOT MET | Zero new real applications |
| Stop/Pause, crash recovery, history/outbox (E) | PASS relevant fixtures; live incomplete | Pause and fresh-session checks; no new genuine notification/locked Stop evidence |
| Extended awake/locked operation (F) | NOT TESTED | No uptime claim |
| Production install, merge, hosted Action, cleanup | NOT PERFORMED | Existing releases and manual-only workflow policy preserved |

The remaining technical work is the Naukri UI adapter, durable upload admission
and receipt-reconciliation loop in the installed worker. The original task also
requires a permitted Naukri route before recurring submissions. The owner has
declined outreach; a clarification about retaining or changing that original
condition is pending, and no response is assumed. Changing an owner requirement
would not itself establish Naukri's permission. Challenges, rate limits and
provider access controls must still be respected.

For source rollback, use an ordinary reviewed Git revert of the implementation;
do not reset dirty worktrees, remove receipts, delete runtime folders or modify
historical releases. There is no new installed runtime to roll back. A future
production replacement still requires a fully prepared candidate and owner review
of its exact SHA under the existing release policy.
