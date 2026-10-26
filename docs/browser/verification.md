# Inspection and fill verification

Implementation base: PR #22 exact head
`94fe1106528cde23bf30faf4e532c5d74d42ae8c`.
Feature branch: `feat/chrome-form-inspection-autofill`.
One writer owns the new `automated-apply-chrome-fill` worktree.

The Phase 1 worktree at `7dfe694` has preserved untracked `AGENTS.md` and
`backend/app/agent/tools.py`. The latter conflicts with PR #22's tracked registry;
no ownership assumption or checkout overwrote it. #22 and Phase 1 are preserved;
this feature is a stacked draft rather than an integration into the occupied
Phase 1 worktree. Neither Phase 1 nor main was merged or deployed.

## Evidence boundaries

All candidate/project/PDF/job/form data used below is fictional. Chrome for Testing
is real, launched in task-created profiles. Web pages are local HTTP fixtures,
including ordinary and Google Forms-like applications. These tests do not attest
that a real Google Forms, Greenhouse or Lever deployment has passed acceptance.
Telegram message delivery is simulated; the authenticated Telegram intake,
executor, packet persistence, separate Chrome worker and saved results are real.
No Ollama or live Cohere call was made. No email or external application POST was
sent. The fixture HTTP server rejects any reached application POST as a test failure.

## Browser coverage

The explicit Chrome suite covers native controls and required fields; Google
Forms-like structure; multi-step progression with final Submit refusal; confirmed
PDF upload and integrity; project question mapping/review; dropdown/radio/checkbox
metadata; validation errors; missing facts; expired login; CAPTCHA and MFA;
sensitive values excluded from metadata; injection in labels; unexpected submission
on change/next; redirects; process crash/restart and stale document IDs; independent
application tabs; rejection of a pre-existing non-dedicated profile; actual MV3
refusal to inspect without an activeTab gesture; and page-state injection against
the isolated inspector.

The vertical Telegram test searches saved fixture jobs, prepares an actual packet,
accepts `Fill the first application`, queues browser work, fills actual controls,
persists field receipts and the truthful Telegram response, and deduplicates the
same Telegram update. Approved Quick-Clinic contribution sources enter a separate
actual Chrome project plan, wait for owner field review, and then fill. Missing
salary stays untouched while known fields fill.

Inspection v1 metadata has no value/selector/credential fields. Backend regressions
cover owner/native boundaries, strict contracts, URL restrictions, plan mode and
single-use authorization, nonce/scope/fencing, profile/job/packet/project/expiry
changes, PDF confirmation/checksum, missing/consent abstention, exact dropdown
mapping, deterministic bounded compound commands, cancellation and browser lease
loss. The restricted-role PostgreSQL acceptance includes real concurrent browser
claims and an active row locked by another session, immutable audit grants and
crash recovery that never repeats a browser side effect.

## Regression results

Final local totals and exact-head hosted checks are recorded in the draft PR and
delivery report. Earlier completed checkpoints: 1,836 full backend tests with zero
skips, 52 frontend unit tests, 31 extension tests, typecheck, formatting, Ruff and
Bandit. The final run includes subsequent regression additions and isolated-world
hardening; these checkpoint numbers are not represented as final-head results.
No test/assertion/security detector was disabled. Existing pypdf `add_js` deprecation
warnings come from executable-PDF rejection fixtures.

## Locked Mac and remaining submission blockers

Sleep/offline is simulated through stale heartbeat/lease timestamps. Chrome process
crash/restart is actual. PostgreSQL engine restart and durable queue recovery are
actual. Physical lock/sleep testing and unattended operation while locked are
unverified; the owner's Mac and installed runtime were not modified or locked.
A sleeping/offline/powered-off Mac is not available to the browser worker.

Before automatic external submission there must be a separate accepted capability,
portal-specific submission semantics and request/receipt verification, exact owner
submission approval, file/network upload acceptance, login/CAPTCHA/manual boundaries,
and independently verified runtime/locked-screen behavior. Submission is still
hard-disabled. This milestone's conservative network guard intentionally hands off
network-dependent widgets, uploads, autosave and step transitions.
