# Personalized local outreach drafts (Phase 4A)

`OutreachDraftingService` is shared by REST and the opt-in MCP draft tool. It loads the saved
primary candidate profile, confirmed project/evidence contributions, professional links,
company/job records and Phase 3 contact evidence. Every output requires human review.
There is **no Gmail sending, provider draft synchronization or application submission**.
Approval is a local review record, not proof of delivery.

## Generation and grounding

`DraftInput` accepts contact ID, optional job ID, purpose (`job_opportunity`/`exploratory`),
style (`professional`, `concise`, `friendly`, `technical`, `founder-focused`), maximum body
length, optional personal instructions, `use_llm` and an optional idempotency key. Instructions
cannot add facts or override evidence checks. Additional personal requests are flagged for
human editing/review rather than used to fabricate facts. Styles control greetings, closing
requests and Gemini writing guidance. Without a job, the text describes potential opportunities
and does not assume hiring. A saved job is explicitly described as a saved listing, not proof
that an opening remains active.

Authenticated REST defaults to Gemini composition via the existing `ApplicationAnswerService`
provider abstraction and `LLMUsageManager`: one shared monthly cap, cooldown/concurrency
controls and usage accounting. The model drafts the relevant candidate contribution with
structured claims, exact evidence quotes and references. Existing conservative validation
checks claim coverage, numbers, named entities and unsupported vocabulary. Provider errors
are sanitized. Missing profile, confirmed project contribution, identity or appropriate
recipient evidence returns `needs_input` before generation. Unconfigured Gemini also returns
`needs_input`; invalid model claims return `validation_failed` without draft text.

The service assembles the subject, introduction, recipient, saved listing/company references,
reasonable request and verified profile links around the validated contribution. Shared
technologies are mentioned only when present in both documented project and saved source
context. Company technology intelligence retains source-reported language; it is not treated
as candidate history. No invented familiarity, metrics, referrals or active hiring claim is
needed. No remote URLs are visited by the LLM. These checks are conservative safeguards,
not semantic proof: the owner must still read every factual clause.

`use_llm=false` uses an exact saved contribution with the same recipient/context validation,
length checks and local storage. MCP always takes this non-billable path even if a caller
tries to request paid generation. Results identify provider/model/usage when applicable,
evidence references, missing information, unsupported-claim flags and `requires_review`.
Preview never persists outreach records; actual model calls still consume reserved budget.

## REST lifecycle

All endpoints require `JOB_AGENT_API_TOKEN` and return no-store responses.

| Endpoint | Effect |
| --- | --- |
| `POST /api/v1/outreach/drafts/preview` | Generate reviewable preview, no outreach row |
| `POST /api/v1/outreach/drafts` | Explicitly persist a successful local draft |
| `GET /api/v1/outreach/drafts?limit=20&offset=0` | Bounded page plus total |
| `GET /api/v1/outreach/drafts/{id}` | Text, recipient, revision, eligibility and review state |
| `PATCH /api/v1/outreach/drafts/{id}` | Human text/recipient edits with `expected_revision` |
| `POST /api/v1/outreach/drafts/{id}/approve` | Record current eligible revision; body `{ "expected_revision": 1 }` |
| `POST /api/v1/outreach/drafts/{id}/reject` | Record rejection of the current revision |
| `GET /api/v1/outreach/drafts/{id}/eligibility` | Re-evaluate recipient, evidence and approval currency |

Example creation input (fictional IDs must be replaced with actual saved records):

```json
{
  "contact_id": "00000000-0000-0000-0000-000000000001",
  "job_id": "00000000-0000-0000-0000-000000000002",
  "writing_style": "technical",
  "max_length": 1800,
  "use_llm": true,
  "idempotency_key": "owner-request-unique-123"
}
```

Persistence extends the existing `job_agent.outreach_logs`; it does not replace history.
New records use `pending_approval` (the legacy initial `draft_created` state remains supported).
Review sets `approved` or `rejected`. A successful API response includes the new revision;
subsequent edits/decisions must use it. PostgreSQL advisory locks and the unique idempotency
key prevent duplicate persistence and duplicate generation for concurrent keyed requests.
Reusing a key with changed inputs or a different REST/MCP origin is a conflict. Requests
without keys explicitly create distinct drafts. Rejected drafts can be edited into a new
pending revision, but cannot be approved unchanged.

## Eligibility, edits and approval

Before generation/approval the service checks current contact existence, suppression, identity
conflicts, fresh employer/role evidence, business-domain email, email observation freshness,
confirmed candidate project evidence and matching job/employer association. Speculative
`candidate`, missing, invalid, personal-domain or generic role-inbox recipients block approval.
Provider-reported addresses can yield a reviewable/approvable local draft with a retained
warning; they are **not send-ready**. Send readiness additionally requires fresh mailbox
verification evidence and human/contact reviews. It never dispatches a message in 4A.

Drafts snapshot material candidate version, selected project facts, contact/email/evidence,
company/job data and saved links. Approval binds text, recipient, evidence hash and revision.
Editing text or recipient clears previous approval. A changed profile, suppressed contact,
expired/changed contact evidence or job/company context makes `approval_current=false` and
requires regeneration/re-review even if the historical `approval_status` still records an
approval. Do not treat that historical status alone as valid authorization.

Human edits are accepted and retained. Conservative eligibility validation allows rearranging
or deleting grounded original sentences and adding exact recorded contribution sentences.
Novel subject/body claims are flagged `unsupported_edited_claim_requires_grounding` and
cannot be approved until corrected or grounded through updated evidence and regeneration.
This deliberately may block an accurate paraphrase; it does not ask the model to certify
its own output. Approval locks current records; future sending must recheck evidence and
suppression immediately before delivery rather than trust an old approval.

Migration 006 protects direct SQL edits as well: revisions advance, material text/recipient
changes clear approval, and new fake Gmail delivery IDs or sent transitions are rejected.
Existing real/historical sent records are preserved. `gmail_draft_id`, `gmail_message_id`,
`gmail_thread_id` and `sent_at` stay null for Phase 4A-created drafts. The connected account
foreign key is available for 4B; local drafting does not require or fabricate a Gmail binding.
There is no `/api/v1/outreach/send` route or Gmail send MCP tool.

Phase 4B must separately implement least-privilege sending authorization, sender binding,
revision-specific consent, current eligibility checks, dispatch idempotency, provider draft
synchronization only when authorized, and actual delivery evidence. Phase 5 application
integration remains separate and is not started by this foundation.
