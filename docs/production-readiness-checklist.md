# Production readiness checklist

Production is not authorized by Phase 6B. `production_ready` deliberately stays false in automatic
configuration reports; the owner reviews actual deployment evidence before making that decision.
This remains a single-owner application, not an authenticated multi-tenant SaaS.

- [ ] Select a host, approve production deployment and separately approve every production SQL change.
- [ ] Use a separately verified database target, certificate-verified TLS, private networking and backups.
- [ ] Inspect 001–009 catalog parity read-only using an independently authorized production procedure;
      staging CLIs intentionally refuse production. Record missing/drift/privilege findings.
- [ ] Test runtime SELECT/INSERT/UPDATE paths with intended grants and RLS; do not use anon/authenticated.
- [ ] Review legacy tables without RLS and restrict database roles/schema exposure; see security review.
- [ ] Supply unique random API token and SECRET_KEY; disable debug, SQL echo and wildcard origins/hosts.
- [ ] Terminate HTTPS through a trusted ingress; test forwarded-header spoofing and owner access controls.
- [ ] Keep remote MCP disabled or separately authorize its own token, exact hosts/origins and TLS boundary.
- [ ] Supply and confirm the real candidate's facts, preferences, projects, resume resource and private data consent.
- [ ] Verify permitted public sources with fresh timestamps and persistent pacing in the actual environment.
- [ ] Authorize and evaluate a tiny fictional Gemini test, then separately consent to sending real profile facts.
- [ ] Review Serper rights/domain evidence, LinkedIn retention permission, pricing and per-call paid approval.
- [ ] Leave Apify/Apollo/SignalHire disabled until account endpoint access, prices and legitimate permissions exist.
- [ ] Validate Gmail metadata OAuth separately; sending stays disabled without a new explicit owner send action.
- [ ] Complete a real discovery/match/packet/review/manual handoff without submitting an application.
- [ ] Rehearse encrypted backup restore including key recovery; record RPO/RTO and a forward-repair plan.
- [ ] Configure health/readiness alerts, structured sanitized logs, failure/cooldown alerts and retention.
- [ ] Review image digest, dependency constraints, CI evidence and incident access before release.

Generate independent high-entropy secrets locally or through the host secret manager. Never reuse
SECRET_KEY as an OAuth key. Create OAuth Fernet keys with cryptography, use immutable key IDs,
add a new active key before an explicitly reviewed re-encryption, and retain old decrypting keys
until all envelopes and backups no longer need them. Changing a key under an existing ID is
rejected by existing TokenStore fingerprints. No script rotates production secrets automatically.
API token rotation invalidates clients immediately; coordinate the owner and restart safely.
