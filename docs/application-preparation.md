# Standalone application preparation — Phase 5A

This workflow prepares a persistent, reviewable application packet. It is not proof of submission.
FastAPI, PostgreSQL, the existing FastMCP server and Gemini are reused. `apply-extension` is not a
dependency and is outside approved scope. No browser library, login client, private portal API,
extra deployable service, scheduler or Gmail send action participates in this workflow.

## Capabilities and truthful boundaries

`GET /api/v1/applications/platforms` reports Naukri preparation/resume selection/grounded screening
answers/manual handoff as supported. Discovery is configuration-dependent, browser autofill is
`not_implemented`, automated submission is `not_authorized_or_verified`, and `live_verified=false`.
This implementation makes no assertion that an official Naukri submission API is available.

The adapter checks saved source labels, posting hosts and discovery observation links locally.
It distinguishes a Naukri-hosted destination, external employer destination, unknown URL and
expired/invalid listing. It preserves a saved external application URL. A genuine Naukri posting
can serve as the manual landing page when no separate application URL was saved. A source label
alone cannot establish a Naukri posting: disagreement blocks approval until the saved data is
corrected. Unknown platforms have `unsupported` readiness until a future adapter is implemented.
No URL is fetched, no redirects are followed, and no destination ownership or availability is
live verified. A recent observation does not establish that a vacancy remains open.

## Data and resolver contracts

The authoritative candidate is the persisted primary profile. Typed snapshots include name,
email, optional phone, skills, actual roles, education, projects, summary and saved preferences.
Professional URLs come from confirmed saved data, never unconfirmed environment fallbacks.
Blank/missing phone, education, projects, salary, notice period and authorization remain unknown.
The existing preference schema has a minimum salary, not a verified current/expected salary;
those questions require human input. Generic work authorization does not establish country-specific
authorization, sponsorship, age, gender, disability or other sensitive answers.

Each field has a UUID, question, category, field type, required flag, character/word limits,
explicit constraints, actual supplied options, proposed/human/effective values, provenance,
validation status, review state and answer revision. Categories include identity/contact, profile
URL, education, experience, skills, resume, salary, notice, authorization, project, motivation,
free text, choice, yes/no and unknown. The seven default fields are a **local checklist**, not
claims about Naukri form structure or DOM IDs. Additional fields originate from owner entry.
Choice fields require actual options; automatic answers must exactly match a saved value and an
option. The system never invents options or infers a yes/no answer.

`AnswerBuilder` reuses `ApplicationQuestionClassifier` and `ApplicationAnswerService`. Exact saved
facts resolve without a model. Preview/creation/question entry do not spend credits. An explicit
generate request uses the existing grounded Gemini provider, quotas, request/word/character bounds,
evidence references, conservative validation and `ApplicationAnswerDraft` persistence. Confirmed
project purpose/contribution and requested challenge/solution are required for project narratives;
skill names alone cannot support experience claims. Company/job text is opportunity context, not
candidate experience. Missing company context/preferences produce `needs_input`; unsupported
generated claims produce `validation_failed`; unavailable Gemini produces `provider_unavailable`.
No failed or over-limit answer is silently truncated into a usable answer.

Form constraints accompany explicit narrative generation. Non-length semantic constraints require
human review. All narratives and human edits require review, even if schema/grounding validation
passes. A human edit is labeled `human` and preserves the original proposal/evidence for comparison;
it never overwrites candidate facts. The owner must check every edited claim. A packet review is
separate from the historical answer draft's own review state.

Resume selection prefers an explicit, confirmed resource belonging to the candidate. Otherwise it
requires exactly one confirmed primary resume. Invalid/unconfirmed/missing/ambiguous selections
return alternatives and `needs_resume`; no arbitrary default is chosen. The selection preserves
resource ID, URL, label and a digest of its saved version. A Drive URL is not a PDF upload.
`manual_resume_upload_required` instructions and `file_upload_required` fields always remain visible.
The backend neither downloads the resource nor attests to a file upload. A selected resource cannot
be deleted while audit history references it; demoting/changing it flags the packet stale.

## Lifecycle, readiness and approval

The durable lifecycle starts at `created`. An internal `preparing` claim serializes a mutation,
then finishes as `needs_input`/`ready_for_review`, `reviewed`, or `approved_for_manual_handoff`.
An explicit owner tracking update may record `external_application_opened`. It does not open the
URL. A separate explicit report records `user_reported_submitted`; submitted applications may be
withdrawn and draft packets abandoned. `provider_confirmed_submitted` is reserved and rejected
in Phase 5A, including by PostgreSQL guards. There is no automatic transition to submission.

Readiness is computed separately: `needs_profile`, `needs_input`, `needs_resume`, `needs_review`,
`ready_for_manual_handoff`, `manual_action_required`, `completed_by_user`, or `unsupported`.
File upload is an outstanding manual step even when the packet is ready for manual handoff.
Required unanswered fields, invalid destinations, missing resumes and pending narratives block
approval. Listings older than 30 days (or with unknown observation time) carry an explicit warning;
destination confirmation includes checking that the vacancy is still open. Approval does not mean
the external form will accept the application.

Every mutation requires `expected_revision`. Approval requires the exact revision, explicit resume
and destination confirmation, and review of all populated narratives/edited answers. Editing an
answer, changing the resume, adding questions or refreshing saved data invalidates approval.
Tracking-only changes carry unchanged content approval to the next revision with an audit event.

The context digest includes material profile/job/company values, profile version, saved resources,
all evidence timestamps/confirmation states, and distinct source observation URLs. Reads flag
changes; edits/review/handoff reject stale context. Repeated discovery observations of the same
source URL do not create another packet. `PATCH` with `refresh_saved_data=true` rebuilds deterministic
fields, clears human answers and generated narratives, and requires fresh generation/input/review.
Inspect the previous packet before refresh if you need to retain a human edit. The global dependency
digest is deliberately conservative: even an unrelated resource/evidence change can require review.

Outcomes are an independent dimension: `not_applied`, `application_incomplete`, `applied_manually`,
`application_rejected`, `interview_scheduled`, `offer_received`, `archived`. Post-submission outcomes
require submission evidence; they cannot erase it. The explicit submission-report endpoint may
record actual manual completion even if the owner did not use packet approval/handoff. Stale
preparation must not suppress a truthful owner report. Receipt references are optional owner-supplied
text, never fetched or treated as provider verification. The report requires literal human
confirmation and idempotency. `Job.status` is deliberately unchanged throughout this domain.

## Protected REST API

All routes below require `Authorization: Bearer $JOB_AGENT_API_TOKEN`; unset configuration fails
closed. Payloads are limited to 64 KiB. Errors redact database/provider details and invalid input
values, and responses use `Cache-Control: no-store`. This is the existing single-owner boundary,
not a multi-tenant authorization system. UUIDs and question ownership are validated. Unknown
metadata, client-supplied ORM snapshots, provider receipts and lifecycle overrides are forbidden.

| Method | Path (prefix `/api/v1`) | Purpose |
| --- | --- | --- |
| GET | `/applications/platforms` | Honest capability matrix |
| POST | `/jobs/{job_id}/application-preview` | Read-only saved-data preview; `{}` is valid |
| POST | `/jobs/{job_id}/application-packets` | Persist with required `idempotency_key` |
| GET | `/application-packets` | `offset`, `limit`, `platform`, `job_id`, lifecycle `status` filters |
| GET | `/application-packets/{id}` | Packet plus current readiness/staleness |
| PATCH | `/application-packets/{id}` | Select resume and/or refresh saved data |
| POST | `/application-packets/{id}/questions` | Add owner-entered form questions |
| POST | `/application-packets/{id}/questions/{field_id}/generate` | Explicit grounded answer generation |
| PATCH | `/application-packets/{id}/questions/{field_id}` | Human edit with form limits |
| GET | `/application-packets/{id}/readiness` | Current computed eligibility |
| POST | `/application-packets/{id}/review` | Review field IDs, or approve exact revision |
| GET | `/application-packets/{id}/handoff` | Read-only URL, exact approved fields, copyable answers, upload instructions |
| POST | `/application-packets/{id}/report-submission` | Explicit actual manual-completion report |
| PATCH | `/application-packets/{id}/tracking` | Independent outcome/opened/withdrawn/abandoned update |
| GET | `/application-packets/{id}/events` | Ordered append-only audit, bounded `offset`/`limit` |

Idempotency keys are 8–100 alphanumeric/underscore/hyphen characters. Identical create requests
return the original packet; reused keys with different inputs or a different key for the same
candidate/job return 409. One durable packet per candidate/job prevents duplicate preparation.
Submitted/closed content is immutable. A submission retry requires the original request/key,
including its original expected revision; it returns the original evidence without another event.
Revision conflicts return 409. Use the latest GET rather than blind retries. See the
[fictional walkthrough](naukri-application-handoff.md) for complete request bodies.

## MCP

The existing server exposes `get_application_capabilities`, `preview_job_application(job_id)`,
`get_application_packet(packet_id)`, `get_application_readiness(packet_id)` and
`get_application_handoff(packet_id)`. All require `read_applications`, which is included in the
configured single-owner read scope set. Both discovery filtering and direct wrapper invocation
enforce it. A narrow token without that scope is denied. No mutation, approval, generation,
submission, browser or Gmail authority is added. Remote MCP stays disabled by default; REST works
independently. Follow [MCP security setup](mcp-security-and-tools.md) for separate tokens and TLS.

## Migration 008 and verification

Apply 008 only after 001–007 in an explicitly authorized environment. **Production migration is
not authorized or performed.** Historical migrations remain unchanged. The four new `job_agent`
tables are `application_packets`, `application_packet_fields`, `application_events` and
`application_submission_evidence`. RLS has no client policies; PUBLIC/anon/authenticated have no
grants. Backend service_role can select/insert, update packets/fields, and cannot delete history.

Unique candidate/job, create-key and submission-key constraints provide durable idempotency.
Restrictive FKs preserve source records; a composite resume-owner FK prevents cross-candidate
selection. Row locks and compare-and-swap revisions serialize mutations. Database guards invalidate
direct field/material edits and reject fake provider confirmation and unaudited submission.
Events and submission evidence reject UPDATE/DELETE. Packet, fields and events share the caller's
transaction. The existing Gemini usage reservation is deliberately independent and survives rollback.
No `public` objects, existing data, startup migration hooks or production deployment hooks change.

```bash
PROFILE_TEST_DATABASE_URL=postgresql://postgres:<test-password>@127.0.0.1:5432/candidate_profile_test \
  backend/venv/bin/pytest backend/tests -q
backend/venv/bin/ruff check --isolated --select E9,F,I backend/app/services/applications \
  backend/app/api/v1/applications.py backend/app/schemas/applications.py \
  backend/app/models/application_packet.py backend/app/repositories/application_packet.py
backend/venv/bin/bandit -q -r backend/app
backend/venv/bin/python -m compileall -q backend/app backend/scripts
git diff --check
```

The PostgreSQL verifier accepts only localhost and the `candidate_profile_test` base database,
then creates/drops a unique child database. It applies 001–008 (008 twice), snapshots all prior
tables, preserves a public sentinel, checks roles/RLS/FKs/history, runs eight-worker create/edit/
report races, tests stale evidence and rollback, and composes an offline grounded narrative.
Without the URL PostgreSQL tests skip explicitly; SQLite success alone is insufficient.
CI provisions PostgreSQL 16 and runs the complete suite, Ruff, Bandit and compilation. All HTTP
tests use mocks/ASGI transport; no Naukri calls, actual Gemini credits, Gmail sends or submissions.
