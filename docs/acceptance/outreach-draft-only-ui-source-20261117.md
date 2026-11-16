# Outreach read/draft-only dashboard — source checkpoint 2026-11-17

Implementation [6d60fac890df45f503b789e8b75c4388334964ee](https://github.com/karanagg166/automated-apply/commit/6d60fac890df45f503b789e8b75c4388334964ee), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

The older outreach dashboard still contained send-preview/send mutations and a send-confirmation modal despite the owner's newer Gmail READ + CREATE DRAFT ONLY scope. Those actions are removed. Local draft editing/exact approval and preserved historical attempts remain available; the Gmail panel links to the independent account/draft workspace. Connection copy consistently describes reading and unsent drafts. An older sending_enabled response cannot activate a send flow in this component. The retired primary Gmail status request is also removed from outreach detail.

Historical uncertain attempts remain visible with editing/approval blocked, their recorded status/dates/message reference and manual-reconciliation requirement. Provider acceptance remains a recorded observation, with no delivery inference. Internal hashes/tokens/raw record JSON are not rendered. Backend send endpoints retain their separately implemented owner-policy refusal.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source correction | PASS (source only) | Read/draft-only UI, retained local approval/history and qualified evidence; formatter applied |
| New frontend tests | NOT TESTED | 3 declarations: no send flow even with legacy send-authorized data/local approval preserved; historical uncertainty/locked editing/private-field omission; local list/history/policy copy |
| Frontend types/build/browser/full suite | NOT TESTED | New executed tests0; deferred until full source integration |
| Rust/PG regression count | NOT TESTED | 0 new declarations; backend policy-refusal regression remains deferred |
| Actual Gmail/Mac/installed UI | NOT TESTED | No provider call, message action, browser use or installed change |
| Timing/resources/focus/restart/24h | BLOCKED / NOT TESTED | One retired detail query structurally removed; no measured comparison or live acceptance |

Final reproduction: `scripts/run_acceptance.py` plus `pnpm -C frontend test`/typecheck/build/e2e for the final coordinated gate, including `tests/outreach-policy.test.tsx`, mailbox/workspace/connection journeys and backend refusal/retained history checks. No executed failure log exists. No mail/account/token/private log content is published. Complete contacts/outreach/registry/provider/platform source still remains.

Prior validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 dedicated disposable native PG passes,455 distinct; it does not validate this head. Estimate58% complete/42% remaining held. Continue full source before combined acceptance and reviewed whole-family STOP installation/live proof. STOP162/lifetime4/hour1/three quarantines/strict worker receipts0 and all saved filters/identity/PDF/focus/history controls remain. No hosted Actions, merge, cleanup or provider activation.
