# Phase 2A: candidate resources and grounded application answers

This backend prepares answers for review. It does not submit applications, send messages or emails,
retrieve resume files, or modify Drive sharing. The original public LinkedIn professional URL is
profile data; secondary LinkedIn login credentials are never collected.

## Setup and migrations

Install `backend/requirements.txt` and configure `backend/.env` from the placeholder-only template.
Apply migration `003_candidate_resources_and_answer_drafts.sql` after 001 and 002 in an approved
development database. Production migrations require separate approval. Migration 003 creates four
`job_agent` tables, indexes and an update-timestamp trigger function. It preserves existing profiles,
versions, jobs, records and public objects. All new tables have RLS with no client policies and revoke
PUBLIC/anon/authenticated privileges; the backend needs an owner or BYPASSRLS connection.

`JOB_AGENT_API_TOKEN` is mandatory for **every** endpoint below. Send `Authorization: Bearer <token>`.
Unset authentication returns 503; missing or invalid credentials return 401 before body parsing.
Requests are bounded to 64 KiB; schema limits further bound questions (2,000 characters), company
names (200), job descriptions (10,000), evidence text (4,000) and output (20–10,000 characters).
Successful private responses use `Cache-Control: no-store`. This remains a single-user backend:
one bearer token protects one primary profile, not a multi-tenant authorization system.

The server LLM API account/key is separate from the model Codex uses for code development and
separate from credentials in `karanagg166/apply-extension`. Deterministic answers need no AI key.

## Resources and precedence

Supported types: resume, github, linkedin, portfolio, leetcode, codeforces, geeksforgeeks,
hackerrank, kaggle and other. Resources require public-host HTTPS URL syntax without userinfo,
private/reserved literal IPs, internal hostnames, non-443 ports or control characters. This is URL
validation, not a sharing/access check. There are no URL-fetching endpoints or background downloads.
DNS resolution is intentionally not performed. No link is treated as an accessible file.

`github_url`, `linkedin_url` and `portfolio_url` in the existing candidate profile are the sole
storage for those standard links. The additional-resource table intentionally excludes those three
types. Updating a standard link through POST below synchronizes the authoritative profile column,
requires explicit confirmation and `expected_profile_version`, and advances its version through
the existing compare-and-swap repository. Standard links can also be edited via authenticated
`PATCH /api/v1/profile` with the current quoted `If-Match` ETag.

Resolution order is saved profile field, confirmed additional resource, environment default, missing.
An ambiguous or unconfirmed saved resource blocks fallback instead of quietly choosing a default.
Once an edited profile (version > 1) has a null standard link, its environment fallback is suppressed.
This conservative rule avoids resurrecting a deliberately cleared field; import links explicitly if
needed. Defaults never update the database at startup. Their provenance is `environment_default`,
confidence is 0.75 and review is required. Exact confirmed links have confidence 1.0.

Optional defaults are `CANDIDATE_RESUME_DRIVE_URL`, `CANDIDATE_GITHUB_URL`,
`CANDIDATE_ORIGINAL_LINKEDIN_URL`, `CANDIDATE_PORTFOLIO_URL`, `CANDIDATE_LEETCODE_URL`,
`CANDIDATE_CODEFORCES_URL`, `CANDIDATE_GFG_URL`, and `CANDIDATE_HACKERRANK_URL`.
Empty defaults are absent. Invalid URLs stop configuration validation.

Explicit import, from the repository root:

```bash
python -m backend.scripts.import_candidate_resources --dry-run
python -m backend.scripts.import_candidate_resources --apply
```

Review the dry-run URLs before applying. The command requires an existing profile. It skips any
existing resource type and any saved/edited standard field. `--apply` approves the listed standard
links; additional imported links remain unconfirmed until reviewed with the resource endpoint.
Concurrent standard edits produce a version conflict and roll back the import, never overwrite
another user's edit. Repeated imports are idempotent.

## API contract

OpenAPI `/docs` describes the typed request/response schemas. All paths below start `/api/v1`.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/candidate/resources` | Page of saved resources plus resolved standard/coding links |
| POST | `/candidate/resources` | Create additional resource, or update by supplied `id`; synchronize standard profile links |
| POST | `/candidate/resources/resolve` | Resolve `{ "question": "GitHub profile link?" }` without an LLM |
| GET | `/candidate/evidence` | Page separated into `verified` and `unverified` lists |
| POST | `/candidate/evidence` | Add user-supplied professional facts; confirmation defaults to false |
| PATCH | `/candidate/evidence/{evidence_id}` | Correct facts or explicitly confirm them |
| POST | `/application-answers/generate` | Deterministic answer or grounded narrative draft |
| GET | `/application-answers/drafts` | Saved drafts with profile-version staleness |
| PATCH | `/application-answers/drafts/{draft_id}` | Change review state to draft, reviewed or discarded |

Lists accept `offset` (0–100,000) and `limit` (1–100; default 25). Resource/evidence responses include
pagination metadata. Evidence separation applies within the requested page. Drafts return a bounded
array. Unknown UUIDs return 404; malformed UUIDs return 422. UUID lookups are always profile-scoped.

Fictional additional-resource payload:

```json
{
  "resource_type": "resume",
  "label": "Backend engineering resume",
  "url": "https://drive.google.com/file/d/fictional-example/view",
  "is_primary": true,
  "user_confirmed": true
}
```

Multiple resume variants are supported. A partial unique database index prevents competing primaries
for one profile/type; another unique constraint prevents duplicate URLs within a type. Conflicts
return 409. To change the primary, update the existing record by `id` with `is_primary: false`, then
promote the selected record. Every resource update supplies its full new values and explicit
confirmation, so a changed URL cannot inherit an old approval. Standard resource POSTs require
`resource_type: "github"` (or linkedin/portfolio), `user_confirmed: true` and the current
`expected_profile_version`; they return a resolved link rather than a duplicate resource row.

## Verified professional evidence

The existing verified skills, roles, education, certifications, summary and job-search preferences
remain available. `VerifiedProject` adds purpose, contribution, implementation_details,
engineering_challenges, solutions and measurable_results to its existing name, description,
technologies, achievements and URL fields. Existing project JSON is compatible; no old project is
assigned a contribution or outcome automatically.

Additional evidence types are project, experience, achievement, resume_note and other. A source URL
or imported text does not establish verification. Confirmation means the **user asserts correctness**,
not that the system independently verified it. Corrections clear confirmation unless the same
PATCH explicitly reconfirms. Resume notes must be supplied by the user; the Drive URL is metadata.

Fictional project evidence:

```json
{
  "evidence_type": "project",
  "title": "Example Relay",
  "content": "Reviewed project notes supplied by the applicant.",
  "source_description": "Applicant's own project notes",
  "user_confirmed": true,
  "project": {
    "name": "Example Relay",
    "purpose": "A service for sharing task updates.",
    "contribution": "I implemented backend authentication using Python and FastAPI.",
    "technologies": ["Python", "FastAPI"],
    "implementation_details": "I used signed tokens to authenticate requests.",
    "engineering_challenges": "Concurrent connections required consistent authentication.",
    "solutions": "I checked authentication before accepting each connection.",
    "url": "https://github.com/example/relay"
  }
}
```

No metrics are supplied here, so generated answers cannot introduce them. Project narratives require
a purpose/description and personally attributable contribution. Questions asking about challenges
also require an actual challenge and solution. Skills alone never establish project accomplishments.
For technical experience, confirmed first-person work notes and role highlights may also be used.

Retrieval is deterministic: SQL keyword ranking selects up to 100 confirmed additional evidence rows
across the stored collection; structured profile projects/roles are then included and ranked by
question overlap and contribution. At most six relevant sources enter the prompt. Skill-specific
questions require evidence of that technology in actual work. There is no vector store, embedding
service, document fetch or automated third-party import. Large relevant contexts return
`input_limit_exceeded` rather than silently cutting facts mid-sentence.

## Answer routing, styles and limits

Links, email, phone, name, experience years, notice period, skills, education and certifications use
exact stored facts. Authorization/sponsorship/country questions are handled conservatively: a generic
authorization statement cannot establish a visa answer. Current compensation is never inferred from
a minimum salary preference. Multiple requested facts or links require clarification. Requests to
upload/attach files return `file_upload_required`, known resume metadata and `accessibility:
"not_checked"`; no upload has occurred.

Project explanations, technical experience, short bios and grounded motivation may invoke Gemini.
Motivation requires actual saved preferences plus supplied company and job context. `job_id`, when
supplied, must exist; its saved company/description fill missing context. All job/page/question text
is untrusted data, not instructions or evidence of candidate history. Unknown categories, missing
contributions and missing preferences return `needs_input` with a specific follow-up.

```json
{
  "question": "Tell us about your most technically challenging project.",
  "writing_style": "technical",
  "job_id": null,
  "company_name": null,
  "job_description": null,
  "max_characters": 1500,
  "max_words": 180,
  "save_draft": false
}
```

Styles: professional (default), conversational, technical, concise and founder_focused. All ask for
natural first-person factual prose. Explicit numeric word/character limits in the question tighten
the API limits. The server rejects overlong answers without truncating URLs or regenerating.

Responses include question_type, status, answer, writing_style, used_llm, requires_review,
evidence_references, missing_information, provider/model, nullable token usage, error_code,
retry_after_seconds and optional draft_id. Status is one of draft_ready, needs_input,
file_upload_required, provider_unavailable or validation_failed. Model-generated narratives always
require review; schema validity never sets factual verification or submission approval.

## Provider configuration and request accounting

Only Gemini is implemented, through `ApplicationLLMProvider` and the current `google-genai` SDK:
async `client.models.generate_content`, JSON MIME type and Pydantic `response_schema`. SDK retries
are disabled so hidden network attempts cannot bypass the budget. No tools or URL context are enabled.
Official references consulted for the implementation:

- [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/)
- [Structured outputs](https://ai.google.dev/gemini-api/docs/structured-output)
- [Provider error guidance](https://ai.google.dev/gemini-api/docs/troubleshooting)

Configure a Gemini model available to your own API project that supports structured output. There is
no hardcoded default or model discovery call. A setup example using the alias shown in Google's SDK
examples is `LLM_PROVIDER=gemini`, `LLM_MODEL=gemini-flash-latest`; set `GEMINI_API_KEY` privately on
the server. Availability and alias targets can change; check the official model catalog for your
account before use. Syntactically invalid model identifiers, non-Gemini provider values and unsafe
numerical limits fail typed settings validation. Missing key/model gives `llm_not_configured` only
for generation; deterministic endpoints remain usable. No live availability is asserted by tests.

Defaults: 1,000 output tokens, 16,000 total input characters (including the system instruction and
serialized payload), 30-second overall generation deadline, 200 provider attempts per UTC month,
and two concurrent requests **per server worker/event loop**. Concurrency can be configured from
1 to 8. The monthly cap is shared across workers through an atomic PostgreSQL upsert. It counts
attempts, including failures and the one permitted transient retry, and commits each reservation
independently of draft/profile transactions. A crash after reservation can conservatively consume
one request without a provider call. It is not a dollar-spend cap.

There are at most two attempts, with a bounded delay only for transient connection/5xx failures.
429 is returned immediately with parsed Retry-After metadata and no automatic retry. A long
Retry-After also prevents transient retries; the client must respect it before a later request.
Queue time and retry delay count against the same deadline. No fallback model/key rotation or
regeneration loop is used. Provider authentication, unavailable model, timeout, rate limit,
monthly cap and invalid structured responses have distinct safe error codes. Raw provider errors,
prompts, full resumes, bearer tokens and keys are not logged or returned.

Returned provider token counts are recorded atomically in the monthly aggregate; missing usage
stays null in the response. Stored totals sum only reported usage, not estimated unknown tokens.
No dollar costs are claimed. Monthly usage is deliberately separate from the existing enrichment
credit pool, whose provider keys and credits have different units.

## Validation and review

The server validates JSON, output length, allowed source IDs, exact source quotes and claim coverage.
It rejects unknown proper names, numbers/dates, strong unsupported accomplishment language and novel
domain vocabulary absent from the selected candidate facts. External job descriptions cannot support
an applicant claim. These conservative checks may reject legitimate paraphrases, and cannot prove
semantic truth, attribution or resistance to every prompt injection. They are additional safeguards;
all generated narratives still require human review. The engine does not optimize for AI detector
evasion or represent generated text as human-authored.

No draft is persisted unless `save_draft: true`. Saved drafts include the original question, answer,
style, evidence IDs, provider/model, optional job and profile version. Review states are draft,
reviewed and discarded. Profile changes set a computed `stale` flag on old drafts without rewriting
their content or approval state. A stale draft cannot be newly marked reviewed. Evidence changes
require reconfirmation; Phase 2A staleness compares the profile version and does not yet maintain
a full dependency revision graph for separately edited evidence/resources.

## Offline testing and demonstrations

```bash
python -m compileall -q backend/app backend/scripts backend/tests
python -m pytest backend/tests -v
# For both isolated PostgreSQL checks, set a dedicated LOCAL test server URL:
PROFILE_TEST_DATABASE_URL=postgresql://postgres:TEST_PASSWORD@127.0.0.1:55432/candidate_profile_test \
  python -m pytest backend/tests -v
```

Both PostgreSQL scripts reject remote hosts and other database names. They create and drop only
uniquely named disposable databases and verify old/public records, migration replay, foreign keys,
primary conflicts, concurrent quota reservations, transaction rollback, drafts and staleness. CI
provides PostgreSQL 16 and runs these tests. Without the dedicated URL they are explicitly skipped.
Unit tests use injected fake providers/SDK clients and block live HTTP; personal credentials are
cleared before settings import. No Gemini, Drive, Gmail, LinkedIn or platform account is called.

With fictional `github_url=https://github.com/example`, a confirmed primary resume at
`https://drive.google.com/file/d/fictional-example/view`, and the project above:

| Question | Expected behavior |
| --- | --- |
| Provide your GitHub | Exact `https://github.com/example`, no LLM, no review needed |
| Share your resume link | Exact saved Drive URL, no LLM; accessibility not asserted |
| Upload your latest resume | `file_upload_required`, metadata only, no upload |
| Explain your most technically challenging project | Reviewed evidence supplied to the provider; first-person narrative draft requires review |
| What's the most impressive thing you've built? Describe contribution and biggest technical challenge. | Same documented work, contribution, challenge and solution; no invented scale or metrics |
| What's your current salary? | `needs_input`; minimum salary preference cannot answer it |

The offline fake-provider narrative is `I implemented backend authentication using Python and
FastAPI.` It demonstrates the contract and validators, not the quality or availability of live
Gemini generation. Missing project contributions or challenges produce `needs_input` before any call.

## Later extension integration and Phase 2B

`karanagg166/apply-extension` was inspected read-only. Its background provider orchestration and
content-script DOM extraction/insertion stay in that repository. A later authenticated extension
client can send its extracted question and bounded job context to this stable JSON contract and
handle exact answers, narrative drafts, missing information and review status. Do not embed the
server bearer token or Gemini key in a publicly distributed extension bundle.

The profile, resources and evidence are ready to support Phase 2B job/startup discovery and richer
matching with saved preferences. Account authorization, platform-specific discovery, browser fill,
actual file retrieval, Drive OAuth, submissions, outreach, scheduling, dashboard and deployment
remain separate work. LinkedIn automated scraping, messages and submissions remain excluded.
