# Phase 1 conversational Telegram boundary

The owner-bound long-poll worker now interprets ordinary phrasing, common command
misspellings, greetings followed by requests, compatible multi-sentence filters,
job-number selection and selected-job pronouns. It searches cached job records;
it does not silently launch discovery, paid research, sending or submissions.

The internal routing contract covers GENERAL_CHAT, FOLLOW_UP, JOB_DISCOVERY,
JOB_FILTERING, JOB_COMPARISON, APPLICATION_PREPARATION, APPLICATION_STATUS,
PROFILE_QUERY, PROJECT_QUERY, RESUME_STATUS, CONNECTION_STATUS, FOUNDER_RESEARCH,
APPROVAL_REQUEST and UNSUPPORTED_ACTION. Legacy intent names map to these routes.
They are structured operation categories, not a list of six accepted sentences.
Unknown or conflicting workflows receive an honest clarification/unavailable reply.

Flow: verify numeric owner and private chat; parse bounded intent; apply the
existing dispatcher/capability policy; read SQL context and approved evidence;
return a grounded response; commit operation, update offset and response outbox.
A nested transaction rolls back a partially failed dispatch. Arbitrary shell,
SQL, browser JavaScript, provider URLs and authority changes are never operations.
Model interpretation cannot add an executable command.

`owner_preferences` stores a persistent random conversation ID, at most eight
category/time history entries, bounded job IDs/selection, filters, project rank,
answer reference and clarification state. Raw chat transcripts are not retained.
Context expires after ten minutes of inactivity and is replaced on next access;
`/reset` or a natural reset request replaces selection and conversation ID.
Expiration prevents reuse; it is not a promise of physical deletion of old
PostgreSQL backups or operation audits.

Telegram update offsets and `agent_operations` request IDs prevent repeated work.
The outbox marks a send attempted before calling Bot API. Confirmed rate limits
can retry; ambiguous interrupted sends remain `sending` and are not replayed.
The Bot API has no sendMessage idempotency key, so exactly-once delivery is not
claimed. An ambiguous send needs reconciliation rather than an automatic repeat.

Profile answers require the existing exact-version owner confirmation. Project
answers use the `ApprovedKnowledge.answer(question, project_rank, max_words,
max_characters)` interface and require supporting sources. The independent module
in [PR #19](https://github.com/karanagg166/automated-apply/pull/19) provides a matching
adapter but is deliberately unmerged. Its dashboard, resume-engine selection,
notification/invalidation wiring and historical-version mapping remain pending
review. The running worker truthfully reports project context unavailable.

There is no functioning open-ended model in this runtime. AGY generation remains
disabled because tool-free isolation is unproven. No Gemini key is configured.
Ollama was not installed/running at the local probe; no model was downloaded or
invoked. Optional `TELEGRAM_LOCAL_AI_ENABLED=false` and blank `OLLAMA_MODEL` keep
local interpretation disabled. The adapter calls only `127.0.0.1:11434/api/chat`,
with a JSON schema, no tools, 2,048-token context, 256 output tokens, a five-second
budget and bounded responses. It has mocked protocol/security tests, not a live
model adequacy result. A small quantized model would need separate local latency,
accuracy and memory acceptance on the 8 GB Mac before enablement. See the official
[Ollama API](https://github.com/ollama/ollama/blob/main/docs/api.md).

The deployed worker uses online Supabase and preserved owner pairing. A fresh
owner application-status request has matching dispatcher and sent-outbox evidence;
the owner confirmed receiving replies. At 17:57:59 UTC on 2026-10-25, the final
collector recorded macOS screen lock, a new sent pong and a fresh worker poll
while locked. The owner confirmed that reply arrived. Earlier unsuccessful lock
collection attempts remain historical evidence, not the current acceptance result.
Live varied paraphrases, mistakes and contextual follow-ups still need matching
roundtrips. Unit tests and simulated Bot API transport do not establish them.
