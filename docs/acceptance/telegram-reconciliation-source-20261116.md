# Telegram uncertain prompt reconciliation — source checkpoint 2026-11-16

Implementation [63cf05918470ae5807e4a7cbbc58b17fc1d4e12c](https://github.com/karanagg166/automated-apply/commit/63cf05918470ae5807e4a7cbbc58b17fc1d4e12c), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. New source is uninstalled and untested.

Source review found that queue owner answers accepted only pending/sent questions, incorrectly rejecting current dashboard answers after an uncertain Telegram send. The handler now accepts delivery_unknown and owner-reconciled delivery_not_sent while retaining all current question/packet/account/PDF/original-step/expiry checks. Ordinary unanswered siblings follow the same final packet revision across these transport states without delivery renewal.

The new native owner endpoint `POST /api/v1/execution/questions/{id}/delivery-reconciliation` takes expected_delivery_attempt, outcome sent/not_sent and a positive integer message_id only for sent. It checks the configured runtime/owner binding, exact immutable send attempt, expired send lease, first resolution and unambiguous current/expired message references. It records a clearly labeled owner-reported finding; this is not a verified Bot API or application receipt. Exact retries return the retained finding, including after a later answer. Altered retries cannot overwrite it. Neither outcome resends, extends expiry, changes packet authority nor grants application permission.

The dashboard displays this control only for a native uncertain prompt with a saved attempt; original active sends remain blocked. It requires an explicit verified outcome and a safely represented positive message ID for sent. Older unbound prompts cannot be adopted through this control. The shared fixed BFF allowlist gains only the exact POST route; its generated package copies were rewritten. Existing authenticated session/CSRF/bearer boundaries remain. The native endpoint is additional to the frozen legacy OpenAPI; older installed services do not implement it, and legacy prompts without native attempts do not show the control.

A late matching Bot API positive receipt is retained independently, including a conflict marker when an owner previously reported not_sent or a different message. Closed/answered question state stays closed; expiry is never renewed. Same-receipt retries preserve original evidence time. Delivery evidence remains distinct from an application receipt.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Guarded native reconciliation, answer/sibling correction, late evidence, dashboard control, fixed shared route; formatters applied |
| New Rust standard tests | NOT TESTED | 1 declaration: strict conditional input/UUID/integer/extra-field bounds, exact POST route and no resend route |
| New native PostgreSQL/loopback tests | NOT TESTED | 9 declarations: sent/correlated reply/idempotency; not_sent/dashboard answer; stale binding/attempt/lease/message collision; immutable finding; dropped ACK; both queue transport answer states; sibling revision; late Bot API conflict; expired context |
| New frontend tests | NOT TESTED | 4 declarations: explicit choice, not_sent exact attempt/no resend, safe positive ID, old unbound/active-lease refusal. Existing application test gains1 transport-state case; shared gateway test gains3 assertions |
| Compile/Clippy/typecheck/build/combined suites | NOT TESTED | Executed new tests0; source-first final combined gate remains deferred |
| Actual Telegram/Mac/browser/install | NOT TESTED | No real message, owner-data query, browser action or runtime/extension change |
| Timing/resource/restart/focus/24h | BLOCKED / NOT TESTED | No measured improvement; existing account/focus/operator gates remain |

After all source is integrated, reproduce through `scripts/run_acceptance.py`, including the new Rust/PG/UI files and gateway/packet regressions. No new executed failure log exists. Sanitized fixed codes: telegram_delivery_attempt_conflict, telegram_delivery_binding_required, telegram_delivery_lease_active, telegram_delivery_already_resolved, telegram_delivery_message_conflict and execution_write_ack_failed. Raw question text, Telegram identifiers and private receipts remain outside this report.

Prior validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 native disposable PostgreSQL passes,455 distinct, and does not validate this head. Estimate58% complete/42% remaining held. Continue full natural conversation/registry, Gmail accounts/history/alerts/workspace, outreach/providers/platforms, combined final tests and reviewed installation/live acceptance. STOP162/lifetime4/hour1/three quarantines/strict worker receipts0, saved filters/account/PDF/history, Gmail read/draft-only and focus rules remain. No hosted Actions, merge, cleanup or live activation.
