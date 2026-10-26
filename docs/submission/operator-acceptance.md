# Owner acceptance and separate live rollout gates

Only fixture engine acceptance is in scope for this milestone. Every checkbox below starts incomplete. Tests use fictional facts and do not complete an owner's setup step.

## Before the first real application

- [ ] Owner reviews and confirms the current candidate profile, contact details and claims.
- [ ] Owner identifies and confirms the canonical resume PDF, verifies its contents and selects the correct primary resource/version.
- [ ] Owner approves project context and personal contribution claims needed by the actual application.
- [ ] Owner performs portal sign-in in the separate dedicated browser profile and verifies account/session identity. No credential, CAPTCHA or MFA automation.
- [ ] Independently accept the portal's actual current form, upload, final control, request semantics and confirmation behavior with explicit owner permission. Fixture compatibility is insufficient.
- [ ] Independently accept narrow portal-specific network rules, required redirects, receipt authenticity and read-only recovery. No general POST or arbitrary redirect enablement.
- [ ] Owner reviews the actual packet and filled document, all required answers, narratives, uploaded PDF and any sensitive attestations. Unsupported attestations remain manual.
- [ ] Owner issues an exact, current submission approval for the named employer/job, selected packet ID, precise destination and immutable versions. A generic “yes” is insufficient.
- [ ] Verify reliable confirmation evidence tied to that exact application, plus uncertain-result recovery without replay.
- [ ] Verify an available dedicated browser worker, heartbeat and durable database. Physical locked/asleep/offline Mac acceptance is separate; a sleeping or offline Mac is unavailable.
- [ ] Review and authorize a separate live rollout implementation/configuration and any required schema migration through the normal owner-approved database process. This release deliberately cannot enable live submissions with a flag.

Do not deploy hosting, apply production DDL or enable live employer submission as part of fixture acceptance. Existing packet-table guards against provider-confirmed submission remain in force. The owner must authorize later live portal acceptance and rollout separately. LinkedIn remains discovery-only and Gmail send actions retain their own exact approval requirements.

## Cohere is a separate optional gate

- [ ] Configure a verified, owner-confirmed free **evaluation** key. Its validity/account quota must be independently checked; an absent or unverified key blocks live model evaluation.
- [ ] Explicitly opt into the provider's evaluation budget/request/token limits.
- [ ] Separately authorize transmission of owner command text.
- [ ] Separately authorize transmission of candidate/profile/project/resume data before any such transfer.
- [ ] Run owner-permitted fictional-data provider acceptance and record the result before broader use.

No Cohere key verification or data-transmission consent is inferred from submission approval. Deterministic fixture acceptance requires no Cohere request, paid API, or Ollama process. Model understanding never grants execution authority or overrides a persisted result.

## Record three independent verdicts

1. **Fixture submission engine accepted:** controlled localhost HTTP POSTs and durable verified receipts, safety/recovery tests and final-head CI pass.
2. **Actual portal submission independently accepted:** remains unverified until separate permission and independent portal acceptance.
3. **Owner-approved live rollout enabled:** remains disabled until owner setup, explicit rollout approval and a separately reviewed live implementation/configuration are complete.
