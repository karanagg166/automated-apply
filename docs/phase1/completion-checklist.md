# Core Phase 1 completion checklist

**Core Phase 1 Ready: not yet.** Every core criterion must pass; historical owner acceptance of a provider limitation cannot replace actual secure answer generation. PR #18 remains draft and unmerged. Phase 2 requires owner approval.

- [ ] An approved AI provider produces valid JSON for a bounded fictional generation and a grounded project answer under enforced tool isolation. AGY authentication passes; its authenticated headless initialization still advertises 60 tools, and no new model input was sent.
- [ ] Owner saves reviewed candidate facts and confirms a checksum-valid canonical PDF in the dashboard. Owner intends to review; completed review is not inferred.
- [ ] Owner configures ranked projects, authorized source checkouts, technology stacks and context templates, then approves their evidence and summaries. The recomputation, invalidation and retrieval implementation/tests pass; live fields remain empty.
- [x] Controlled real Chrome passes Google Forms/HTTPS, redirect, refresh, popup/menu registration, service-worker stop/recovery, extension reload, browser restart, offline/recovery, duplicate and stale-origin checks. Exact returned preview JSON persists in Supabase; no submission occurs.
- [x] Installed native host rejects wrong origins, malformed/oversized frames and reports a real partial-frame timeout accurately. Reversible installed-source update preserves private configuration.
- [x] Telegram supported routing and approved-only project retrieval pass deterministic tests; online polling is healthy.
- [ ] Verify retrieval of actual owner-approved project context through the live Telegram integration after project configuration. No live approved projects currently exist. No outbound messages were sent by this verification.
- [x] Supabase restricted TLS/catalog and Gmail identity/compose scope verification remain healthy; encrypted resume checksum and existing key are preserved.
- [x] Reuse integrated PR #19; connect dashboard project/review controls and exact BFF routes to its existing service. Preserve the single existing resume-sync engine.
- [x] Manual PDF versions support checksum-verified download/confirmation and atomic canonical selection, including selection of an already confirmed version. Stale selection is rejected and prior review is invalidated after a canonical change.
- [x] Disable live Drive downloads and automatic-enable controls while retaining historical encrypted versions and reviews.
- [x] Pass full local backend/PostgreSQL, candidate-context, resume, AGY protocol, frontend unit/E2E, extension and native lifecycle checks, Ruff, Bandit, dependency audits and secret scanning.
- [ ] All required GitHub Actions checks pass on the actual final PR head. Prior-head success is historical; inspect PR #18 checks and record the exact final SHA.

The new local dashboard/API source and tested frontend build are installed with a rollback backup. Private backend/frontend configuration, encryption keys, database credentials, Telegram pairing and owner data are preserved. Local API, frontend and Telegram services were restarted. See [core-readiness.md](core-readiness.md) and [verification.md](verification.md) for evidence and limits.

Deferred without blocking this milestone: Drive OAuth and live auto-download; real Naukri, Wellfound, Instahyre, YC and Internshala connections; actual job submissions. Manual-only portal acceptances remain unchanged and do not claim authentication. VS Code MCP acceptance and the earlier six-example Telegram follow-up remain separate follow-ups rather than additional core gates.

Historical migration approvals, earlier owner Chrome/locked-screen Telegram acceptance, prior failed model attempts and earlier CI failures remain in Git history and live-evidence.json. They have not been rewritten as current successes. No merge, Phase 2 start, real submission, Gmail send or paid-provider activation is authorized by this checklist.
