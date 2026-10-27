# Phase 3 backend contract — v1.0 (2026-10-27)

Branch: `feat/phase3-codex-integrations`, based on Phase 2 `89e2a50`. Backend and extension ownership only. AGY can read this linked-worktree document; no frontend files are changed here. Contracts are additive. Mock transports/fixtures are not live verification.

All endpoints below require the existing owner bearer credential; mutation approvals additionally retain the existing owner-approval header. Private responses use `Cache-Control: no-store`. No provider execution, mailbox body access, email send, LinkedIn interaction or employer submission is enabled by this contract.

## Missing answers

`POST /api/v1/application-answers/generate` retains the existing request and response. A `needs_input` response now includes nullable `missing_input_id` and `missing_input_url`. The request persists even when `save_draft=false`; no candidate answer is invented. Sensitive questions are excluded from retention.

- `GET /api/v1/application-answers/missing?offset=0&limit=25`: `{requests,offset,limit}`.
- `POST /api/v1/application-answers/missing`: original `question`, optional `job_id`, `company_name`, `packet_id`, required `missing_fact`, optional `reason`, `required_input_type` (`text|number|choice|evidence|profile_edit`). Persists a request.
- `GET /api/v1/application-answers/missing/{id}`: original question/category, job/company/packet context, missing information, stopping reason, required input type, created timestamp, `status`, `effective_status`, `version`, `profile_version`, `stale`, `answer`, `evidence_note`, `draft_id`, `href`.
- `PATCH .../{id}`: `{expected_version,answer,evidence_note}`. Always saves a draft, clears approval, and preserves history.
- `POST .../{id}/approve`: `{expected_version,expected_profile_version,factual_confirmation:true}` plus existing owner-approval header. Requires nonempty answer/evidence note and current context. Approves only this exact question/job context; it does not update profile facts or opt into semantic answer reuse.
- `GET .../{id}/history?offset=0&limit=25`: `{history}` with prior revisions.

Versions are integers. Stale or concurrent writes return 409. Sensitive answers return `sensitive_answer_not_retained`. Profile, evidence, approved project or job changes make dependent answers stale. Approved exact-context answers can resolve the same question; stale approvals cannot. Candidate profile facts remain editable through existing profile APIs (`If-Match`) and reusable narrative approvals through existing explicit reuse APIs.

## Gmail read-only accounts

Existing legacy `/integrations/gmail/*` send/compose internals are preserved. New accounts use `/api/v1/integrations/gmail/accounts` exclusively:

- `GET /`: `{accounts,workflow:"readonly"}`. Account fields include ID, verified email/subject, status, scopes, timestamps, workflow, `permissions:{read_metadata,read_body,send:false,modify:false}` and `sync` state.
- `POST /connect/start`: `{expected_email,account_consent:true,read_body:false}`. Returns authorization URL/expiry. Uses the existing PKCE, browser-bound state and callback URI. Metadata is the default. No write scopes are accepted.
- `GET /{id}`: account, permissions, sync policy/status, `sync_enabled`, `body_access_reviewed`.
- `PUT /{id}/selection`: `{expected_version,enabled,sender_allowlist,label_allowlist,query_allowlist,read_body,body_purpose,backfill_days,retention_days,max_pages}`. Initial version is 0. Custom job labels only (`Label_*`); metadata requires labels and cannot use `q`. Body mode requires separate restricted-scope review, actual read grant and a reason headers are insufficient. Backfill 1–30 days, retention 1–90 days, pages 1–3, max 25 messages/page.
- `POST /{id}/sync`: bounded selected-message reads and atomic evidence/checkpoint persistence; no schedule.
- `GET /{id}/evidence?offset=0&limit=25`: extracted links/status signals, provider message/thread IDs, source timestamps and expiry. Evidence is `requires_review`; `submission_confirmed:false`. No raw MIME/body, access tokens or refresh tokens.
- `POST /{id}/verify`, `POST /{id}/disconnect`: account-scoped verification or revocation/local token deletion and selected evidence purge.

States: `selection_required|ready|disabled|partial|completed|failed|reauthorization_required`. Account OAuth states retain existing `connected|disconnected|reauthorization_required`. Gates default off: `GMAIL_READ_SYNC_ENABLED`, `GMAIL_READ_BODY_REVIEWED`. A staged schema change is required before deployment; no live DDL is authorized. Errors are fixed `gmail_*` codes, normally 409; malformed input 422, auth 401/503.

## Startup and people research

Existing `/api/v1/startups` and discovery/contact APIs remain the source of company/people records. Filters retain size ranges, exact-count requirement, location, remote preference, roles, skills, stage, hiring evidence and freshness. Additions: `country`, `industries`, `has_technical_staff`; reported `2-10` band accepted. Counts remain nullable and distinct from reported bands and conflicting evidence. Name-only companies are not merged without a reliable identity.

Public professional links are manual outreach destinations. Existing contact corrections, suppression, retention and evidence APIs remain authoritative. Provider-reported email is never promoted to verified solely on a provider claim. No automated outreach.

## Provider status

Typed Apify official API metadata is separate from paid Actor dispatch. ChatGPT's connector does not establish local CLI authorization. LinkedIn Actors may have public metadata inspected while collection remains disabled. Multiple routes share the existing `apify` account budget; no account rotation. Missing cost/rights/account-limit evidence means execution is blocked. No retry/failover after ambiguous dispatch.

Apollo auth health, endpoint rate limits, account eligibility and credits are separate facts. Unknown credit balance/access blocks enrichment; zero results is valid. Local budgets are reservations, not a claim about provider credits. Final provider endpoint schemas and validation results are recorded in `codex-final.md`.

## v1.1 implementation additions and clarification

The existing `connected_accounts` and `oauth_states` tables are unchanged. Read-only accounts and intents use staged `gmail_read_accounts` and `gmail_read_oauth_states` tables; both reuse the same OAuth/token service. The shared callback distinguishes a random read-intent state by its `read.` prefix and still verifies the browser-bound state, PKCE, expiry and exact scopes. Default account listing reports `schema_ready:false` with `gmail_readonly_schema_update_required` when the reviewed schema is absent.

Gmail synchronization claims a durable per-account lease, releases database connections before HTTP, checks account generation and policy version before reads, and commits evidence/checkpoint atomically. Disconnect or selection edits cancel persistence from an in-flight batch. Concurrent sync returns `gmail_sync_already_running`. A stopped process can resume after the bounded lease expires. Retention purges personal evidence into minimal deduplication tombstones using existing runtime UPDATE privileges; no DELETE grant is added.

- `GET /api/v1/integrations/gmail/accounts/{id}/leads`: account-scoped, deduplicated candidate URLs with evidence IDs; `confirmed_vacancy:false`.
- `POST .../{id}/evidence/{evidence_id}/import`: `{job_url,title,company_name?,company_domain?,reviewed_job_evidence:true}`. Only a retained selected-message URL may be imported; the owner supplies the actual title. Existing ingestion handles duplicates and preserves application state. Imported email evidence remains `requires_review`, never proof of current hiring or a submission.

Fill actions now include nullable `missing_input_id` and `missing_input_version`. The extension links to `http://127.0.0.1:3000/profile?missing_input={id}`; AGY owns that dashboard view. The protected API resource remains the authoritative saved request. Exact owner-approved answers reference `source_type:owner_answer`; edits invalidate prepared packets and fill plans. Initial unknown-question creation does not invalidate unchanged Phase 2 packets.

Apify metadata/status endpoints:

- `GET /api/v1/integrations/providers/apify`: local credential presence, transport, budget key, limits, disabled collection status, investigated Actor IDs and last account inspection.
- `POST .../apify/inspect`: free official account limits/monthly usage, paced independently of billable execution.
- `POST .../apify/actors/inspect`: `{actor_id}` restricted to the three investigated Actors or explicitly configured routes. Returns observed pricing, input schema/digest, source URL, timestamp, `collection_status:disabled_pending_review`.

`APIFY_SOURCE_ROUTES` maps existing portal IDs to up to five reviewed Actor configurations. Routes share exactly one credential, source and budget object. Local configuration rejection may select another route; an attempted external dispatch is never replayed through a fallback. Deduplication remains in existing normalized job ingestion. Actor review expiry must be within 24 hours; no discovered/current price is hardcoded as permanent configuration.

`POST /api/v1/contact-enrichment/providers/apollo/inspect?operation=enrich_person|search_people` uses documented zero-credit health, endpoint usage and credit usage endpoints. Auth, rate allowance, credit pool, free-account/work-email/endpoint eligibility and lookup authorization are separate fields. Unknown credit schema/access means no enrichment. Production enrichment preflights every operation and conservatively caps local reservations against current provider allowance. Configure reviewed eligibility via the documented private `APOLLO_*` settings; review expires after 24 hours. The inspector itself never authorizes a paid upgrade.

Contact output adds `email_evidence_status` (`provider_reported|verified_using_authorized_method|unverified|not_found|suppressed_or_stale`) without changing the existing stored enum. No publicly published email is fabricated merely to populate this status. Existing evidence APIs retain source URLs and observations.

Frontend contract generation is AGY-owned. The backend OpenAPI export was regenerated locally; Codex does not edit frontend generated types. Errors keep the existing HTTP auth, 409 conflict, 422 validation, 428 precondition, and 503 unavailable boundaries. The read workflow has no sending, mailbox mutation, LinkedIn action or employer submission operation.

## v1.2 evidence clarification (2026-10-28 IST)

Official person imports may include optional `business_email` and `email_publication_url` together. The email and publication URL must belong to the employer domain. Only explicit human-confirmed official-company evidence yields `published_source_supported`, with its source URL returned separately. This status does not establish mailbox verification or email-send readiness. Unrelated personal addresses are rejected. Unknown, stale and suppressed states remain explicit.

The shared OAuth callback uses the `read.` prefix, containing a character outside the legacy random-state alphabet, so a legacy intent cannot accidentally select the new storage tables. The two staged tables are additive: they neither alter legacy OAuth/account tables nor expand any existing table's runtime privileges. The optional schema overlay is pinned to a public reviewed SQL checksum and exact disposable-PostgreSQL catalog snapshots.

## v1.3 compatibility and freshness (2026-10-28 IST)

Read-only accounts requiring reauthorization may reconnect without losing their selected-message policy or durable checkpoint. The verified Google subject must still match the existing account. Disconnected accounts report no effective read/send permission; legacy send/compose scopes retain their metadata-read permission reporting.

Missing-answer APIs require the existing owner-preference storage. Historical partial migration schemas keep their previous answer/packet behavior; an unknown question remains unresolved and reports `missing_input_storage_schema_required` rather than inventing a fact or claiming persistence. The explicit missing-answer resource returns a conflict until storage is present. Production baseline storage and the full reviewed optional Gmail schema are independently validated.

Published-business-email evidence is bound to the actual observed address digest. Correcting an email clears its effective publication status unless matching source evidence is supplied; a previous address publication URL cannot verify the replacement. Industry filters match explicit terms/aliases: for example, `AI` does not match `retail`.
