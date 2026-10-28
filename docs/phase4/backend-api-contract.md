# Phase 4 backend contract for AGY

Baseline: integrated Phase 3.5 `d1c2f44`. Codex changes backend/extension only; AGY owns frontend. Existing response fields, routes, approval semantics and the manual-only submission boundary remain compatible.

The shared transaction-ordering fix is also incorporated into the same Phase 3.5 candidate and merged back here. Packet/browser database dependencies finish before response delivery, and database commit failure returns a sanitized 503. The runtime FastAPI minimum now matches the already locked/tested 0.143.1 interface; no installed package or lockfile was upgraded.

## Discovery

`GET /api/v1/discovery/sources` adds `smartrecruiters` (configured public read adapter), `simplify`, `workday` and `company_careers` (manual import only). SmartRecruiters requires `SMARTRECRUITERS_BOARDS`, a maximum of ten explicit company identifier/name pairs. With no boards it reports `configuration_required`. Metadata visibility never proves live connectivity or collection rights.

`POST /api/v1/discovery/runs` continues to use `RunRequest`. For SmartRecruiters set `source: "smartrecruiters"`, bounded `query.page/limit`, and a stable idempotency key. Only configured company feeds and constructed detail URLs on `api.smartrecruiters.com` are fetched, using GET without credentials. The untrusted `ref` is never followed. 403, 429, timeout and malformed/inconsistent evidence produce existing explicit result states. Records preserve source ID, employer configuration, publication basis and evidence URL. Unknown skills, precise remote policy and company size are not invented.

For Simplify, Workday or company career pages use `source` with `manual_jobs`, including factual title, `source_name` matching that source and the exact original URL. No page is fetched. Imported records remain `requires_review` and do not become confirmed current vacancies. An empty request reports `manual_input_required`. `JobIngestionService` and existing source observations preserve deduplication, idempotency and human application state across sources.

`GET /api/v1/jobs/search` adds these optional query parameters:

| Parameter | Meaning |
| --- | --- |
| `country` | Explicit job country evidence; IN/IND/India are equivalent. Unknown country does not pass. |
| `experience_level` | Case-insensitive exact source label, e.g. Junior or Entry Level. No title-to-years inference. |
| `published_within_days` | Actual publication timestamp within 1–3650 days. Unknown publication dates do not pass. Existing `max_age_days` still means last observed. |
| `company_size_band` | `2-10` or `11-50`, using current nonconflicting company observations. A broad 1–10 band cannot establish at least two employees. Unknown/stale/conflicting evidence does not pass. |
| `approved_experience_fit` | Default false. When true, requires current owner-approved profile experience or returns HTTP 409. Includes only explicit published numeric ranges containing those years. A categorical title alone remains unknown. |

`NormalizedJob` adds nullable strict numeric `experience_min_years` and `experience_max_years` (0–60; minimum cannot exceed maximum). These accept explicit source or owner-entered listing evidence only. SmartRecruiters' categorical experience label does not become a fabricated numeric range. They persist in existing discovery JSON; there is no schema migration. Reobserving the same exact primary posting refreshes the range; removing it invalidates numeric suitability. Secondary sources cannot overwrite the primary range.

Job search items add `experience_fit`. It is `unknown` without the approved-experience filter; included results under that filter report `within_published_range`. This compares only a published range and approved factual years. It does not certify employer eligibility or overall suitability. Existing skill, remote/hybrid/onsite, role, source and matching explanations still apply.

## Read-only Gmail

Existing account-specific consent/policy/sync/evidence endpoints remain unchanged. Metadata records have no subject-based status inference. Parsed selected bodies add tentative `possible_recruiter_response`, `possible_follow_up_request` and `possible_status_update` signals alongside existing job-alert/interview/rejection/acknowledgment signals.

Evidence adds `signal_basis` (`metadata_only_no_status_inference` or `selected_message_body_keywords`) and `status_confirmed: false`. These are keyword signals, not authenticated employer status or a confirmed submission. Raw message bodies, subjects and sender addresses are not added to retained evidence. Existing account/message/thread evidence, retention, independent OAuth scopes/cursors and no-mailbox-mutation checks remain in force.

Each lead from `GET .../accounts/{account_id}/leads` now includes `imported_job_ids` and `import_state`: `imported`, `not_imported` or `legacy_message_import_unknown`. Use these URL-specific fields for badges and duplicate decisions. The older message-wide `imported_job_ids` cannot establish which URL was imported in a multi-link message. Historical ambiguity must stay visible; do not disable every sibling link. Successful new imports retain a protected URL-to-job mapping in `imported_leads`. Failed persistence remains HTTP 409 and leaves the lead retryable. There is no new Gmail schema change; use the tested Phase 3.5 migration/operator procedure.

## Browser assistant

Existing packet, question, missing-input, review, action, step-preview and cancellation APIs remain unchanged. The reusable engine now accepts recognizable Ashby, EU Lever, SmartRecruiters and Workday applicant URLs in addition to Greenhouse, Lever and Google Forms. SmartRecruiters permits only its exact documented `oga=true` application query. Generic employer HTML/React forms require an exact configured `BROWSER_ALLOWED_ORIGINS` entry, using the existing `https://host:443` format, plus owner destination/asset review. URL eligibility does not grant automation rights or establish a real vacancy. Restricted portals, Gmail pages, private addresses and credential-bearing/other query URLs remain rejected.

The dedicated browser retains event delivery, stale DOM detection, value preservation, safe custom-dropdown review, conditional/multi-step handoff and canonical PDF validation. Submission, legal consent, sensitive self-identification and CAPTCHA remain manual. Extension React/custom widgets remain manual where safe event handling cannot be established; use the guarded dedicated browser when supported.

Generic remote sites use the dashboard's dedicated browser runner, which pins validated public DNS before launching Chromium. The separate command worker retains its fixed ATS-host boundary and hands unsupported generic sites back for dashboard/manual assistance. A configured origin alone does not widen that worker's network access.

The extension adds cancellation of prepared answers and in-flight authorization. A cancelled or superseded native response cannot restore a plan or trigger DOM filling. After refresh/popup restart/native reconnect, prepare and review again. No stale mutation is replayed from storage.

## Type regeneration and validation

The additive OpenAPI changes are exactly the five job-search parameters. The normalized experience fields are validated within `manual_jobs` records at runtime; the existing OpenAPI exposes those records as dictionaries and does not export a `NormalizedJob` component. Gmail lead/evidence additions likewise extend existing dictionary responses. Final verification compares the rest of the schema with the Phase 3.5 export and compiles generated TypeScript separately. Codex does not modify `frontend/**` during Phase 4. AGY should regenerate its owned types after integrating this branch:

```sh
python backend/scripts/export_openapi.py
pnpm -C frontend api:types
pnpm -C frontend typecheck
```

No hosted CI, deployment, live migration, provider spend or employer submission is part of this contract.
