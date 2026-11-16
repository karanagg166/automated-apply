# Owner contact correction — source checkpoint 2026-11-17

Implementation [e56651be4161c286f2b199afa5ca87677b6eff2e](https://github.com/karanagg166/automated-apply/commit/e56651be4161c286f2b199afa5ca87677b6eff2e), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

The existing contact PATCH route now supports owner corrections against the exact reviewed row version. Saved reads expose an opaque PostgreSQL row-version/updated-time precondition; PATCH requires it through If-Match. A lost response cannot repeat the old version or append another correction. SERIALIZABLE transactions acquire the shared owner fence, old/new company locks in sorted order and the contact lock. The complete updated row and new immutable human-correction evidence are checked against returned acknowledgments. Missing/altered acknowledgments roll back the contact, evidence and any identity deletion together.

Only an exact, current, user-confirmed mailbox-verification record for the same contact/company/email and an authorized method can request verified status. The evidence row is share-locked through commit; future/expired/identity-only/provider-claim evidence fails closed. Provider-reported status requires a saved mailbox. Required nulls are rejected; nullable notes can clear. Company changes require no retained email and remove only this contact's bounded identity inventory with exact deletion acknowledgment. No paid request, email send, queue or application-policy change occurs.

The dashboard renders selected evidence fields and reviewed name/role/exclusion/notes/mailbox controls. It requires a review checkbox, sends the exact precondition and disables mutation retries. After any attempt, the form requires a current evidence reload. A changed saved version remounts the review state, preventing old local input from silently adopting a newer precondition. Unchanged mailbox status is omitted, so name/suppression review does not re-attest mailbox verification. Raw evidence JSON is no longer rendered by this modal.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Actual AST-exported correction DTO, native transactional PATCH, public version and review UI; formatting applied |
| Standard fixtures | NOT TESTED | 1 new declaration with36 actual DTO comparisons; no settings/service imports |
| Dedicated native PostgreSQL/HTTP | NOT TESTED | 14 declarations: exact precondition/state preservation; lost response; null/omission; provider/identity refusal; exact mailbox proof;7 invalid evidence variants; affiliation/identity scope;2 update ACK faults;2 evidence ACK faults; deletion ACK fault; HTTP/precondition/native denial; concurrent same-version; owner-fence ACK;10001-identity bound |
| Frontend | NOT TESTED | 4 new declarations: exact reviewed version/omitted mailbox claim; uncertain response lock/reload; evidence-gated verification/no sending; missing version/selected fields |
| Current-head build/types/lint/test | NOT TESTED | New executed tests0; final combined execution remains deferred |
| Actual Mac/provider/production/install | NOT TESTED | No runtime or real contact/provider action |
| Timing/resources | NOT TESTED | Bounded inventory and shared lock structure; no measured comparison |

Fixed response codes include `contact_review_precondition_required`428, `contact_review_version_conflict`412, `contact_current_mailbox_evidence_required`422 and `contact_write_ack_failed`503. Source review caught and corrected an owner-handler response-type mapping omission before compilation. No executed test failure log exists; no private contact records or raw logs are published.

Final reproduction: coordinated `scripts/run_acceptance.py`, including new `contact-contracts` drift stage, Rust `contact_rules`, dedicated `contact_correction_*` PostgreSQL/HTTP cases, frontend `contact-review.test.tsx` and people journeys/types/build. Provider planning/research/budgets, grounded outreach and remaining registry/platform source precede that gate. Exact operator permissions and whole-family STOP migration/install remain required.

Prior validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 native PostgreSQL passes,455 distinct; it does not validate this head.58% complete/42% remaining held. STOP162/lifetime4/hour1/three quarantines/strict worker receipts0, saved filters/identity/PDF/focus/history controls remain. No hosted Actions, merge, cleanup, purchase or provider activation.
