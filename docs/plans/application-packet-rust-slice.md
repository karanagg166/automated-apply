# Next Rust application-packet slice

Deliver one complete preparation/inspection flow before claiming packet API parity:

1. GET `/api/v1/applications/platforms`.
2. POST `/api/v1/jobs/{id}/application-preview`.
3. POST `/api/v1/jobs/{id}/application-packets`.
4. GET `/api/v1/application-packets`.
5. GET `/api/v1/application-packets/{id}`.
6. GET `/api/v1/application-packets/{id}/readiness`.
7. GET `/api/v1/application-packets/{id}/events`.

Edit/generation/review/handoff/manual outcomes form the next group. Browser intake remains
separate. These routes must prepare real saved packets with current context/readiness,
idempotency and history; schema-shaped placeholder responses are not acceptance.

Reuse the existing Rust resource/resume selector and its canonical version digest,
profile contracts/store, full discovery matcher, reviewed opportunity/job context,
grounded direct answers and canonical JSON helpers. `packet_readiness` now implements
the pure legacy eligibility rules over validated internal projections, with an injected
fresh calculation time. It is not an external-input validator or application authority.
Packet DTOs, context construction, persistence and endpoint wiring remain to implement.

Authoritative sources:

- `backend/app/api/v1/applications.py` and `schemas/applications.py`.
- `services/applications/{service,packet_builder,answer_builder,eligibility,resume_selector}.py`.
- `repositories/application_packet.py` and `models/application_packet.py`.
- `supabase/fresh_public/001_phase1_public.sql` and `fresh_public/followups/003_naukri_worker.sql`.

Preparation contracts forbid arbitrary identity, snapshot, provenance and approval input.
There are at most50 owner questions and a bounded canonical idempotency key. The seven
core questions are a local checklist, not observed portal IDs. Preview field IDs are
ephemeral; creation persists IDs/positions. Narrative drafts require explicit generation
or owner input; file fields retain manual-upload status. Missing profile blocks persistence
but remains a truthful `needs_profile` preview. Unsupported sources retain that status.

Check existing idempotency/job-candidate keys before rebuilding a preview. Exact key/body
replay returns the original snapshot, even after facts change; its current read may be
stale. Conflicting keys/bodies conflict. Packet, fields and creation event commit together.
Creation starts revision1, no approval, lifecycle created and tracking not_applied.

Packet freshness has its own canonical recipe; do not substitute an answer-generation
stamp or the job catalog DTO. Include material candidate values/ID/version, the full
selected job material, closed state, reviewed opportunity/currentness, company metadata,
every resource and evidence stamp, deduplicated ordered source observations, Naukri
reviewed criteria/unavailability and approved owner-answer revisions. Preserve legacy
Decimal strings and Python datetime representations in digests; the catalog's normalized
JSON floats/UTC display strings are a different contract. Explicit resume selection never
falls back. Private resume references/download paths remain distinct from public URLs
and attachment proof.

Read under a shared parent lock to avoid mixing revisions/fields across an edit. Fields
sort by position and use a non-null human answer before the proposed answer. Rebuild
current context for freshness. Apply service lifecycle overrides after pure readiness:
closed packets, verified submission and submitting/unknown outcomes need their exact
legacy treatment. A ready manual packet is never proof of upload or worker submission.

Do not call the public Rust answer-generation lifecycle inside packet transactions: it
owns transaction/commit boundaries. Even legacy “read-only” preview may ensure durable
missing-input questions. Expose a transaction-safe internal factual resolver so packet
creation cannot partially commit. No model, packet or answer-draft work is implicit.

Preserve shared parent/context locks, CAS revision range, immutable revision snapshots,
approval clearing and trigger ordering when implementing later edits. Native worker
events use `local_worker`; the reader contract now explicitly accepts that existing DB
origin alongside owner_rest/system. Unknown origins remain rejected. Never derive a
worker receipt from a readable event or manual submission claim.

Core tables: application_packets, application_packet_fields, application_events and
application_submission_evidence. Context additionally uses jobs, companies,
candidate_profiles/resources/evidence, job_source_observations and owner_preferences.
Keep composite resume ownership, job/candidate uniqueness, append-only event/evidence
and current worker-state guards. Multi-select needs both explicit enablement and verified
DB capability, not just a JSON options list.

Preserve the existing fictional packet API, readiness, resume-selection, question-mapping,
review, handoff, revision-history and tracking fixtures. Add native PostgreSQL tests for
creation/replay races, raw fact/resource/evidence changes, shared-lock consistency,
trigger ordering and append-only enforcement; SQLite is insufficient for those guards.
No production migration/install, employer action or full packet completion is authorized
by a passing pure readiness test alone. Existing owner authorizations and action fences
remain the source of authority.
