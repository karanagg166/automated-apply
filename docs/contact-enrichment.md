# Phase 3: professional contact enrichment

Phase 3 adds local-first professional contact research to the existing contacts table. It does not send messages, create drafts, submit applications, fetch social profiles, crawl websites or connect Gmail. LinkedIn URLs are manual-action links. A returned address is never evidence of consent.

## Provider readiness and official references

Documentation checked on 2026-10-19. Both adapters are **mock-tested**. No Apollo or SignalHire credentials were available, no authenticated provider connection was checked, and no real enrichment was executed. Enabling an adapter means configured, not live verified. The providers endpoint always reports `live_verification: not_checked`; connection methods return the outcome of an actual read-only request only when explicitly invoked by trusted server code.

| Capability | Apollo adapter | SignalHire adapter |
| --- | --- | --- |
| Known-person enrichment | `POST https://api.apollo.io/api/v1/people/match` | `POST https://www.signalhire.com/api/v1/candidate/search` |
| Authentication | `x-api-key` | `apikey` |
| Person search | One bounded page via `/mixed_people/api_search`; documented zero credits | Explicitly unsupported by this adapter (provider offers a separate Search API) |
| Identifiers used | Public LinkedIn URL, provider person ID, name plus employer domain | Public LinkedIn URL or SignalHire UID |
| Execution | Synchronous; reveal and both waterfall flags false | `withoutWaterfall: true`, no callback URL |
| Credit balance | Unsupported; local cap shown separately | Read-only `GET /credits` with documented `credits` response |
| Connection test | Read-only `GET /auth/health` | Read-only credit query |
| Verification | Claim retained; email remains `provider_reported` | Rating retained; email remains `provider_reported` |
| Bulk, phone, personal email | Not requested or retained | Bulk not implemented; private fields discarded |

Apollo sources: [authentication](https://docs.apollo.io/reference/authentication), [people search](https://docs.apollo.io/reference/people-api-search), [matching fields and response](https://docs.apollo.io/reference/people-enrichment), [account access/scopes](https://docs.apollo.io/docs/create-api-key), [credits](https://docs.apollo.io/docs/api-pricing), [terms](https://www.apollo.io/terms).

Apollo's current reference requires a work-email account for free-account search/enrichment and the relevant endpoint key permissions (or master key). Additional account eligibility can apply. Use a scoped key when possible. Access is decided by the provider, including 401/403 outcomes; this application does not claim a particular plan is sufficient. Ordinary matching may charge for qualifying demographics/email. Costs differ for legacy plans and waterfall configurations; this adapter explicitly disables phone/personal reveal and waterfall. Operator-confirmed cost estimates are required and are not a provider price guarantee.

SignalHire sources: [authentication](https://docs.signalhire.com/authentication), [Person API](https://docs.signalhire.com/person-api/retrieve-person), [synchronous mode](https://docs.signalhire.com/person-api/without-waterfall), [candidate structure](https://docs.signalhire.com/person-api/candidate-object), [credits](https://docs.signalhire.com/person-api/credits), [pricing and quotas](https://docs.signalhire.com/api-pricing), [rate limits](https://docs.signalhire.com/person-api/rate-limits), [response codes](https://docs.signalhire.com/response-codes), [terms](https://www.signalhire.com/terms).

SignalHire standard person credits are shared with its website/extension. Search has separate daily quotas, and without-contacts uses a separate credit type. This adapter only implements standard synchronous Person lookups and credit monitoring. Its documented synchronous mode has lower coverage and potentially older data than asynchronous waterfall. If a 201/requestId arrives unexpectedly, the adapter returns `queued` with that ID and never pretends results are complete. Callback ingestion/polling is unavailable here; reconcile queued/running attempts manually before any further lookup.

Before enabling either provider, the operator must establish account access, permitted purpose, data-use rights and applicable privacy obligations under the linked provider terms. Configuration does not establish those rights. In particular, SignalHire describes account use in a business capacity; this repository does not assume every personal job-seeking account is eligible. Do not share or resell restricted data or use multiple accounts to bypass quotas.

## Configuration and cost preview

Keep keys server-side. Copy settings from `backend/.env.example`:

```dotenv
APOLLO_API_KEY=
APOLLO_ENRICHMENT_ENABLED=false
APOLLO_MONTHLY_LIMIT=50
APOLLO_PER_RUN_LIMIT=5
APOLLO_CREDITS_PER_LOOKUP=0
SIGNALHIRE_API_KEY=
SIGNALHIRE_ENRICHMENT_ENABLED=false
SIGNALHIRE_MONTHLY_LIMIT=5
SIGNALHIRE_PER_RUN_LIMIT=2
SIGNALHIRE_CREDITS_PER_LOOKUP=0
CONTACT_ENRICHMENT_MAX_PEOPLE_PER_RUN=10
CONTACT_ENRICHMENT_MAX_CONCURRENCY=2
CONTACT_CACHE_TTL_DAYS=30
CONTACT_RETENTION_DAYS=90
CONTACT_PROVIDER_TIMEOUT_SECONDS=20
```

Monthly and per-run limits are local **credit estimates**, not dollars or provider balances. Set a conservative account-confirmed maximum `*_CREDITS_PER_LOOKUP` before paid execution; zero fails closed. Unknown actual cost is stored as null, not fabricated as zero. `ProviderUsageLog.credits_consumed=0` with a null confirmed value in run usage means no provider usage figure was supplied. Reserved estimates remain in the shared discovery ledger even on failures, cancellation or uncertain billing. No pool of synthetic remaining credits is created, and ApiKeyPool keys are never rotated by this service.

`POST .../contacts/preview` reads only local data and reports bounded potential targets and reserved credit estimates. A fallback estimate is an upper bound and requires separate opt-in. A new company may first use Apollo's zero-credit search and then require up to `max_people` enrichments. Search results with obfuscated names or without confirmed current employer domains are excluded; partial names are never invented. Preview cannot know provider data availability or guarantee final provider charges.

The shared DiscoveryBudget uses independent commits and atomic upserts. Each lookup also has a unique durable company/provider/operation/identity claim, committed before remote execution. This prevents duplicate paid requests across retries, concurrent processes and restarts, even if the surrounding run later fails. The budget provider namespace is shared with any other discovery reservations for the same provider. Application concurrency is bounded per process; durable monthly caps and lookup uniqueness apply across processes.

Completed and not-found claims expire after the cache TTL. Other outcomes, including transport uncertainty, running, queued, auth errors, malformed responses and failures, remain blocked until operator investigation. There is deliberately no automatic replay/reset endpoint. Read-only database investigation may be necessary to reconcile a crashed run; reservations must not be deleted just to retry. Failed preflight budget claims also require review. 429 cooldowns use Retry-After (seconds or HTTP date) with a bounded default. No HTTP request retries automatically.

## Workflow and identity

1. Load existing contacts for the employer, including suppressed records.
2. Bridge named, unambiguous Phase 2B `DiscoveredPerson` records; preserve their observed dates and evidence URL.
3. Consume existing, user-confirmed `public_business_contact` evidence with person-specific employer-domain email attribution. Evidence URLs are stored, never fetched. Generic company inboxes remain company-level evidence.
4. Skip paid lookups for fresh supported contact data, human-corrected records, suppressed records or unresolved identity conflicts.
5. Execute the explicitly selected primary provider only with `allow_paid=true`, an enabled adapter, credentials, confirmed cost configuration and a durable reservation.
6. A separately authorized fallback (`allow_fallback=true`) is considered only after a successful identity result lacking business email. Empty, unauthorized, failed, timed-out, rate-limited or pending results never cause a paid fallback.
7. Persist observations separately; rank contacts with explanations. Optionally return pattern candidates as research data, never as confirmed contact addresses.

Company-row locks serialize short reconciliation transactions. HTTP requests never run under those locks. Unique `(company_id, namespace, identity_key)` mappings identify canonical LinkedIn URLs, discovered-person IDs and provider-specific IDs. Legacy contacts are matched by normalized URL or compatible person-specific email before mappings are created. Provider identity mappings are scoped to the provider and employer.

Names alone, partial names and titles alone never merge people. Moderate matches require full name, compatible role and an exact human-confirmed supporting evidence URL. Conflicting identity keys produce unassigned company evidence and review errors; conflicting addresses on a strongly matched contact preserve the original email and both observations, with an identity-review flag. Two identically named people at different employers or distinct profiles stay distinct. Role changes append evidence. Human-corrected contact fields are protected from provider updates.

Name-only existing contacts remain useful research records, but orchestration requires a returned supporting LinkedIn identifier before attaching paid results to an existing person. Adapters can normalize known-provider-ID results directly; the HTTP orchestration intentionally takes the more conservative URL route. Historical evidence is never treated as a newly observed role simply because a run rereads it.

`careers@`, `jobs@`, `hr@`, `info@` and other known role/general addresses are not person identity keys. They are stored as evidence with a null contact ID. Only employer-domain work email is accepted from these adapters. Phone numbers, private addresses, birth dates, personal email, gender and unrelated profile fields are discarded.

## Email status and confidence

| State | Meaning |
| --- | --- |
| `unknown` | No usable mailbox evidence |
| `candidate` | Inferred or guessed address |
| `provider_reported` | Provider or reviewed public source supplied it; no established mailbox verification |
| `verified` | Supported documented mailbox verification or owner confirmation |
| `invalid` | Evidence/human review indicates unusable address |

Regex/domain/MX checks never verify a mailbox. Apollo `email_status` and SignalHire `rating` are evidence claims, not independent verification. Existing verified/invalid records are not silently downgraded or reinterpreted. An inferred candidate can become provider-reported only when supported by a new provider observation.

PATCH cannot arbitrarily set `verified`. It requires a current, user-confirmed `mailbox_verification` evidence record for this contact and exact email, with result `deliverable` and method `authorized_mailbox_verifier` or `owner_confirmation`. These records must come from a trusted verification/review process; Phase 3 does not introduce a verifier or an unrestricted verification-record API.

The canonical persisted contact confidence scale stays **0–100**; old records remain unchanged. `EmailCandidate.confidence_score` stays **0–1** for compatibility; `candidate_confidence_percent` is the explicit conversion boundary. New enrichment does not invent a calibrated probability: it reports `supported`, `limited`, or `requires_review`, identity/evidence strength and reasons. A new record's legacy numeric score starts at zero (uncalibrated). Ranking weights are ordering heuristics, not probability estimates.

## Ranking and review

Ranking uses reported role, known company employee count, known job association, human-confirmed hiring responsibility, evidence strength, freshness and available professional links. Technical leaders can rank highly at a known small company. Recruiters/managers rank above executives at a known large company; campus recruiters gain relevance for internships. Unknown company size stays unknown. Sharing an employer is distinguished from explicit job association.

Responses include `priority`, `reasons`, `confidence`, `evidence_strength`, `manual_linkedin_available`, `manual_outreach_review_available`, `email_send_ready` and `outbound_messages_sent: 0`. An unverified address never sets email-send-ready. A verified address additionally requires freshness, human review and no suppression or identity conflict. Phase 4 must recheck all eligibility and consent/approval requirements at draft/send time rather than trusting a previously returned flag.

## API examples

All endpoints require `Authorization: Bearer <JOB_AGENT_API_TOKEN>`. An unconfigured token fails closed (503); wrong/missing tokens return 401. Protected requests are bounded to 1 MiB; request models reject unknown fields, arbitrary provider names, unsupported URLs and oversized role/target lists. Private responses use `Cache-Control: no-store`. No enrichment tool or contact lookup is registered on the unauthenticated MCP server.

```bash
curl -H "Authorization: Bearer $JOB_AGENT_API_TOKEN"   http://localhost:8000/api/v1/contact-enrichment/providers

curl -X POST -H "Authorization: Bearer $JOB_AGENT_API_TOKEN"   -H 'Content-Type: application/json'   http://localhost:8000/api/v1/companies/COMPANY_UUID/contacts/preview   -d '{"target_roles":["founder","cto","engineering_manager","recruiter"],"max_people":5,"providers":["apollo","signalhire"],"allow_paid":false}'

curl -X POST -H "Authorization: Bearer $JOB_AGENT_API_TOKEN"   -H 'Content-Type: application/json'   http://localhost:8000/api/v1/companies/COMPANY_UUID/contacts/enrich   -d '{"target_roles":["cto"],"max_people":5,"providers":["apollo"],"allow_paid":false,"idempotency_key":"contact-review-001"}'
```

Retrieve runs at `GET /api/v1/contact-enrichment/runs/{run_id}`. Reusing a run key returns the same run; changing the request under that key returns 409. Default `allow_paid=false` makes zero provider HTTP calls, including search. The first provider in the requested list is primary; no provider is silently substituted.

`GET /api/v1/companies/{company_id}/contacts` supports `role`, `email_status`, `provider`, `min_evidence_strength`, `last_observed_after`, `suppressed`, `has_linkedin`, `has_business_email`, `offset`, `limit`. Evidence-based filters use stored source attribution. Page size is at most 100. `GET /api/v1/contacts/{contact_id}` returns up to 100 most recent evidence records; expired provenance is redacted. `GET /api/v1/jobs/{job_id}/recommended-contacts` returns up to 25 recommendations.

`PATCH /api/v1/contacts/{contact_id}` accepts `full_name`, `role_title`, `company_id`, `email_status`, `verification_evidence_id`, `do_not_contact`, `suppression_reason`, `human_review_notes`. Corrections append a human-review evidence event. Affiliation changes with an existing company email require resolution first; email transfer to a new employer is never inferred. Setting `do_not_contact=true` immediately removes manual/contact eligibility and recommendations. Suppression survives refresh and retention pruning.

## Migration, retention and tests

Apply `supabase/migrations/005_contact_enrichment.sql` after 001–004 only with environment-specific approval. This implementation did not run a production migration. Migration 005 only changes `job_agent`, adds contact preference/review fields, and creates `contact_enrichment_runs`, `contact_evidence`, `contact_identities`, `contact_provider_lookups`, indexes and foreign keys. It preserves all old contacts, email states, companies, jobs, profiles, resources, answers and outreach history. It enables RLS, revokes public/anon/authenticated access and grants table access to `service_role` when present; the direct backend role must own tables or have appropriate RLS bypass rights. No browser database access is intended.

Evidence recheck expires after 30 days by default. Provider fields older than the 90-day retention period are hidden from current-contact responses. Minimal hashed profile/email suppression identities survive pruning to prevent rediscovery from recreating an eligible person. The operator must run explicit maintenance at least monthly:

```bash
python backend/scripts/prune_contact_enrichment.py
```

This command changes the configured database; run it only in an authorized environment. It removes expired evidence, clears old pattern research from runs, and replaces stale, uncorrected provider contacts with suppressed tombstones while preserving legacy audit/outreach references. Human-corrected records are user-maintained and retained until review/removal. Durable lookup hashes and cost audit are retained without raw provider responses to prevent duplicate spending. No scheduler or production job is created by Phase 3.

```bash
python -m pip install -r backend/requirements.txt
# Existing local empty test database is only an administrator connection; scripts
# create unique disposable databases and drop them after verification.
export PROFILE_TEST_DATABASE_URL=postgresql://localhost/candidate_profile_test
pytest backend/tests -q
python backend/scripts/verify_phase3_migration.py
python backend/scripts/demo_contact_enrichment.py
python -m compileall -q backend/app
```

Without the test database variable, four PostgreSQL integration suites skip; CI provides PostgreSQL and runs them all. Tests block real external HTTP globally. Provider tests inject httpx.MockTransport; no test uses account credits. The PostgreSQL verifier applies 001–004 then 005 twice, snapshots legacy data and public schema, and checks RLS, FKs, uniqueness, concurrent identity resolution, independent reservation caps, concurrent provider claims, idempotency and rollback.

The demonstration creates only a disposable SQLite database, a fictional startup and hypothetical CTO, then uses explicit mock providers. It shows cache preview, one simulated Apollo lookup, a provider-reported business email, one canonical contact, evidence/LinkedIn ranking and zero outreach rows. A second run uses cached evidence. Nothing is sent.

## Phase 4 boundary

Contacts and evidence are ready for personalized **manual drafting review**, subject to freshness, identity and suppression checks. Provider-reported emails are research data, not send-ready mailboxes. Secondary Gmail OAuth, draft creation, approval, sending and eligibility revalidation remain separate work. No Phase 4 implementation is included.
