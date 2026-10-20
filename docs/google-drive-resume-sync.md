# Google Drive resume sync

Use **My Profile → Resume Sync → Sync Now** to download the exact saved Google Drive PDF. A source default is read from ignored `backend/.env`; configuration does not fetch, confirm facts or launch a job. The unresolved short URL is not used. A new upload to Drive normally has a new file ID: use **Change Resume Source / Settings**, save the explicit viewing URL, then sync. No Drive-wide search occurs. Replacing the contents of the same file preserves its stable ID.

## Download and storage

The public download path supports owner-approved files shared with anyone who has the link. It uses credential-free HTTPS requests to `drive.google.com/uc` and `drive.usercontent.google.com/download`. Viewing URLs are validated strictly and converted to a download request; arbitrary URLs, query credentials and non-Google redirects are rejected. Every redirect must retain the exact approved file ID. Public DNS results are validated at every connection, and TLS connects to a validated numeric address while checking the original hostname certificate. Cookies, bearer tokens, proxy configuration and environment credentials are not inherited by the worker. Redirects, per-socket timeouts, a total subprocess deadline and streaming byte limits bound the check.

PDFs must have a PDF signature, be at most 5 MiB and 20 pages, and pass the existing isolated local parser. Scripts, chained/unsafe actions, attachments, forms and encrypted files are rejected. Local page/view navigation is supported. Extracted text and annotation links remain untrusted data. No PDF or extracted text goes to an AI service. Private downloads require owner authentication and no-store responses; no public static file is created.

Every new byte version references the existing Fernet-encrypted `private_resumes` row. Review text, detection-time profile snapshot and differences are also encrypted with the same dedicated `RESUME_ENCRYPTION_KEY`. Preserve that key and encrypted backups; neither sync nor source changes replace it. A missing or invalid key fails closed.

Versions retain Drive file ID, canonical source URL, reported filename, Last-Modified, ETag, optional Drive revision, SHA-256 and download time. Public downloads do not always expose a Drive revision or ETag: unavailable metadata stays null and the UI states the limitation. Unlike the authenticated [Drive API files metadata](https://developers.google.com/workspace/drive/api/reference/rest/v3/files), this path requires no new OAuth consent. It never reuses Gmail scopes or credentials. If sharing is revoked or Google requires authentication/interstitial confirmation, the check reports failure; it does not bypass access controls.

Each check reads response metadata and downloads bounded bytes to verify SHA-256 even when metadata is unchanged. Identical SHA-256 bytes reuse the existing version without reparsing or duplicating encrypted storage, including when an explicitly changed source contains the same PDF. Reverting to previously seen bytes reopens a review cycle and notifies the owner if that version differs from the active resume; previous approval timestamps/profile versions remain in encrypted history. Original version provenance stays immutable. The source record separately retains the latest filename, download time and response metadata, including across source changes; `last_checked_at` records subsequent checks. PostgreSQL row locks serialize concurrent checks; a database unique constraint protects byte identity. The download, encrypted record, review, pointers and notification commit together. Cancellation/crash rolls back partial state; retry is safe.

## Review and activation

Changed bytes create a pending `resume_profile_reviews` record and an in-app review event. Notification opt-in, pause and quiet hours are respected; deferred events are picked up by **Check saved activity**. Only in-app delivery exists. The old approved resume remains active until approval.

Review displays verbatim section differences for skills, experience, employment dates, education, projects, links, achievements and other claims. Name/email and recognized skills are conservative suggestions, not semantic parsing of arbitrary career history. Dates, employers, qualifications and achievements are never invented. Scanned/unstructured PDFs require manual review and fact entry. The editable form starts with current verified facts, retains every confirmed skill, and allows structured corrections to experience, education, projects and professional links. Optional achievements and other claims enter the existing candidate-evidence table only when explicitly reviewed. Existing evidence is preserved.

Approval requires the exact latest version, current source generation, current candidate profile version and explicit owner confirmation. Removing a previously confirmed skill requires a separate confirmation. Stale reviews return 409 for re-review. Approval atomically saves the reviewed facts/evidence, advances the candidate version even for a resume-only change, switches the unique primary private resume resource, and records the approved profile version. Existing packet/answer freshness checks detect the profile change. Packet snapshots, field answers, approved revisions, prior encrypted PDFs and application/outreach history are preserved. Approval never sends, submits or silently rewrites a packet. A lost-response retry cannot apply facts twice. The legacy PDF-confirm route cannot bypass Drive review.

## Owner settings and scheduler

The typed defaults are `CANDIDATE_RESUME_DRIVE_URL`, optional matching `CANDIDATE_RESUME_DRIVE_FILE_ID`, `RESUME_DRIVE_SYNC_ENABLED=false`, `RESUME_DRIVE_SYNC_INTERVAL_HOURS=24` (1–168 hours), and `RESUME_DRIVE_SYNC_REQUIRES_REVIEW=true` (cannot be disabled). Once saved, database source settings are authoritative; environment defaults do not overwrite them.

No scheduler is installed or started by this feature. To deploy periodic checking, first provision the existing backend runtime against an explicitly authorized migrated database, preserve its encryption key, save the source and opt in through My Profile, then supervise this command from the existing runtime image:

```sh
python -m backend.scripts.sync_drive_resume --serve
```

The loop checks at most one explicit source, observes the saved interval, and polls every 60 seconds. Its committed heartbeat expires after 150 seconds. The dashboard reports active only while a real loop heartbeat is current; a stale/crashed loop becomes inactive. The enabled checkbox alone does not imply scheduling. No paid provider, application submission, outbound message or other external operation is scheduled. A one-shot external scheduler can invoke `--scheduled`; it respects owner opt-in/due time but does not claim a continuously active worker. Prefer `--serve` when dashboard liveness is required.

For an explicit manual check from the local virtual environment:

```sh
backend/venv/bin/python -m backend.scripts.sync_drive_resume
```

The command performs no schema creation/migration or approval. It prints only sanitized outcome flags, never resume content, credentials or raw external errors. Errors and access revocation preserve the approved resource. The dashboard owner login and backend bearer must be configured separately to use the UI.

## Schema and verification

Migration **011 follows 001–010**. It adds three private tables and an additive profile/resume relationship used by the existing profile version trigger. It also narrowly extends original candidate-resource PostgreSQL constraints to accept internal `private-resume:UUID` references only for private resume uploads; other resources retain HTTPS restrictions. RLS, client revocations and existing service-role boundaries match Phase 7. It is never applied at startup. No production/staging migration is authorized by this implementation.

```sh
PROFILE_TEST_DATABASE_URL=postgresql://postgres:<test-password>@127.0.0.1:<test-port>/candidate_profile_test \
  backend/venv/bin/pytest backend/tests -q
npm run typecheck --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
PYTHON=../backend/venv/bin/python npm run e2e --prefix frontend
```

The suite mocks Drive transport and generates fictional PDFs in memory. PostgreSQL tests create/drop isolated child databases and exercise migration grants, concurrent same-byte sync, concurrent approval, version advancement, preservation and interrupted-transaction recovery. No real candidate PDF is a fixture. Frontend API types are regenerated with the existing OpenAPI export workflow.
