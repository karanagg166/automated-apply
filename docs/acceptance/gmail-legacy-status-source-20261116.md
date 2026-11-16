# Legacy Gmail status/send refusal — source checkpoint 2026-11-16

Implementation [8e399d6648ac5bd37fbb0ff866fd3a4afe70fe4f](https://github.com/karanagg166/automated-apply/commit/8e399d6648ac5bd37fbb0ff866fd3a4afe70fe4f), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested and uninstalled. Original single-account OAuth/refresh/verify/disconnect remains the next source unit.

The existing primary Gmail status path now reads only public connected_accounts columns in a coherent read-only snapshot, without owner locks or encrypted credentials. Identity, scope facts and recorded verification dates are preserved, with explicit saved-record/current-probe separation. Missing schema reports setup_required; multiple primary accounts fail closed. Current mailbox restrictions suppress permissions. Legacy send grants remain visible as saved scope facts but cannot enable sending; primary message reading/draft creation is not inferred from a saved grant. The independently implemented read/workspace/local-account APIs retain their own permissions.

Historical outreach send/send-preview paths now require the owner boundary and return an explicit fixed owner-policy refusal, even if an old GMAIL_SENDING_ENABLED value is true. Refusal occurs before body parsing, database/account/token work, send reservation or provider dispatch. Wrong methods return405/Allow. No confirmation token is minted or consumed and no prior send history is changed. Full local outreach/history/registry source still follows separately.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Saved primary status, fixed route boundary and historical send refusal; formatter applied |
| New standard tests | NOT TESTED | 2 declarations:16 actual account_output identity/scope/date comparisons with explicit policy/probe overrides; closed legacy status/refusal paths |
| New native PostgreSQL/HTTP tests | NOT TESTED | 4 declarations: read-only privacy/no owner lock; ambiguity/restrictions; missing/empty schema; actual fictional owner HTTP/refusal with old send flag and exclusive table/owner locks proving no data work |
| Compile/build/Clippy/combined suites | NOT TESTED | New executed tests0; source-first final gate deferred |
| Actual Gmail/Google/Mac/install | NOT TESTED | No real account query, OAuth, mailbox read/write/send, migration, browser or installed change |
| Timing/resources/restart/focus/24h | BLOCKED / NOT TESTED | Public projection and no-work refusal design/fixtures only; no measured comparison |

Final reproduction: `scripts/run_acceptance.py`, including `tests/gmail_legacy_status.rs`, `tests/support/gmail_legacy_pg.rs`, retained authentication/owner/primary-account and frontend connection/outreach regressions, after remaining source integration. No executed failure log exists. Sanitized codes include gmail_legacy_schema_update_required, gmail_legacy_identity_requires_review, invalid_gmail_legacy_saved_record and send_blocked with gmail_sending_disabled_by_owner_policy. Private account/token/confirmation/mail/log data is unpublished.

Prior validated9c4ace570535a5856184775f8045ee89eafdd05f provides193 standard +262 dedicated disposable native PG passes,455 distinct; it does not validate this head. Estimate58% complete/42% remaining held. Continue original primary account lifecycle, full conversation/registry/contacts/outreach/providers/eight platforms and final acceptance infrastructure, then combined tests and reviewed whole-family STOP migration/install/live proof. STOP162/lifetime4/hour1/three quarantines/strict worker receipts0, saved filters/identity/PDF/focus/history and Gmail READ + CREATE DRAFT ONLY remain. No hosted Actions, merge, cleanup or provider activation.
