# Reviewed Gmail link import — source checkpoint 2026-11-16

Implementation [3b1ef35ce350383f9508aa9c886fa1c4bba44781](https://github.com/karanagg166/automated-apply/commit/3b1ef35ce350383f9508aa9c886fa1c4bba44781), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Uninstalled, untested source.

The existing account/evidence/import path requires actual LeadImport review, exact selected mailbox ownership, unexpired evidence and exact retained URL membership. It constructs an unverified gmail_alert normalized record from supplied title/employer/domain and source link. Missing employer stays unknown. It performs no page inspection, vacancy/experience inference, packet creation or application action.

The local transaction follows owner fence → account advisory/row → shared ingestion lock. Source observation identity precedes exact canonical URL, then bounded legacy URL normalization. Ambiguous candidates fail closed. Employer evidence respects canonical association and same-name ambiguity; domain conflicts cannot transfer an existing job. Similarity produces at most20 hints from500 candidates, never merges. Description is absent in these records, so legacy content-based merging cannot apply. This slice does not claim full general rich-job ingestion parity.

Existing title/status/score/explanation/skills/description/source/discovery metadata remain intact. New jobs stay discovered/requires_review. Only acknowledged job/source observation writes permit the final per-URL message marker. Suppressed marker/observation ACK aborts company/job/message changes together. Reimport preserves durable identity and human decisions.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Selected evidence guard, normalized projection, conservative identity, ACKs and per-URL marker; formatter applied |
| New standard tests | NOT TESTED | 2 declarations:18 actual NormalizedJob constructor/DTO comparisons; exact account/evidence POST route bounds |
| New native PostgreSQL/HTTP tests | NOT TESTED | 10 declarations: unknown/unverified new job; human-preserving retry; wrong/expired/unselected evidence; employer conflict; concurrent mailbox identity; similarity-only hints; dropped observation ACK; dropped marker ACK; legacy canonical identity; fictional owner HTTP/auth/method/link checks |
| Compile/Clippy/build/combined suites | NOT TESTED | Executed new tests0; final source-first gate deferred |
| Actual Gmail/Mac/provider/browser/install | NOT TESTED | No real message read, provider request, URL visit, owner-data query, migration or runtime change |
| Resource/latency/restart/focus/24h | BLOCKED / NOT TESTED | No measured comparison; prior external gates remain |

After all source is integrated, reproduce through `scripts/run_acceptance.py`, including tests/gmail_lead_import.rs and tests/support/gmail_lead_import_pg.rs with native/owner-import regressions. No new executed failure log exists. Fixed codes include gmail_evidence_not_found, gmail_lead_not_in_selected_evidence, gmail_lead_identity_requires_review, gmail_lead_legacy_inventory_limit and gmail_read_write_ack_failed. Raw mail/private identities/URLs/evidence stay unpublished.

Prior9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 native disposable PostgreSQL passes,455 distinct; it does not validate this head. Estimate58% complete/42% remaining held. Continue job alerts, three-role workspace/drafts, conversation/registry/outreach/providers/platforms, combined tests and reviewed whole-family STOP installation/live proof. STOP162/lifetime4/hour1/three quarantines/strict receipts0, saved filters/account/PDF/history/focus and Gmail READ + CREATE DRAFT ONLY remain. No hosted Actions, merge, cleanup or live activation.
