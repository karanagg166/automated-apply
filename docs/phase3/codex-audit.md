# Phase 3 baseline audit

Verified remotely before editing: PR #37 open, head `89e2a50ef72610af06859b85ac7c33a2bcf1c2cb`; main `1ad14a4d37cbef59548df2b6ec75c9495719b61f`. Work began in the required linked worktree and branch. No merge or hosted Action was requested. The integration head already includes the #35/#36 histories.

| Area | Baseline classification | Reused implementation / Phase 3 change |
| --- | --- | --- |
| Startup discovery | Working for permission-confirmed imports, saved evidence and public ATS; partial live company directory discovery | Reuse observations, hiring evidence, identity, ranking, budgets and existing search. Add country/industry/technical-staff filters, 2–10 reported band and stronger namesake separation. |
| People discovery | Working for reviewed official-company evidence and opt-in public search | Reuse the contact bridge and evidence store. Add technical staff roles; never infer a verified executive role from a search hit. |
| Contact enrichment | Working normalization, local cache, suppression, correction, retention and reservations; partial account eligibility | Reuse Apollo/SignalHire. Add Apollo free-account/endpoint review, official credit and rate introspection, pre-dispatch hard stops. |
| Apify | Working opt-in job Actor runner; missing local MCP connection and typed metadata access | Reuse run reservations, polling, abort and ingestion deduplication. Add official API metadata/schema/limits transport, multiple same-account routes, review expiry, byte caps and collection-method guards. |
| Gmail OAuth | Working PKCE/state, verified identity, encrypted credentials, refresh/revoke; single legacy account | Reuse one lifecycle service. Add separate read-only account and OAuth-intent tables, preserving legacy send/compose storage and behavior. Stage schema changes only. |
| Gmail job ingestion | Offline parser existed; multi-account selected-message ingestion missing | Add GET-only reader, explicit selection, bounded history/pages, leases, safe MIME, minimal evidence retention and reviewed local lead imports. No mailbox writes. |
| Unknown answers | Working abstention and reviewed drafts; durable requests missing | Reuse private owner records and answer drafts. Persist requests, evidence requirements, drafts, exact-context approvals, versions and history; propagate source changes to packets/fill plans. |
| Candidate editing | Working profile optimistic concurrency, evidence edits and packet revisions | Preserve existing APIs; new request edits remain drafts until separate factual approval. No automatic profile-fact or semantic-reuse approval. |
| Browser/native/extension | Working gesture, owner policy, preservation, controlled inputs, choices, navigation, cancellation, resume checks and submit boundaries, with extensive fixtures | Reuse existing DOM/native implementation. Add durable unknown-question references, safe review links and approval-revision freshness checks. |
| Telegram | Working owner-only Bot API adapter, delivery ambiguity safeguards and private logs | Inspected; unchanged. No Telegram or other message sent during Phase 3. |
| Online schema/security | Working approved restricted-runtime public schema, immutable catalogs and manual maintenance | Add a pinned optional read-only-account catalog overlay. No live DDL, permission expansion or runtime replacement. |

The public-search and company-directory rights/cost gates remain meaningful. Merely discovering an Actor, authenticating an API key, or seeing a professional URL does not authorize collection or establish a verified person, email, role, hiring claim or job suitability.

The historical 27-job online timeout remains undiagnosed. Phase 3 does not relabel a small fixture or successful metadata read as proof that it is resolved.
