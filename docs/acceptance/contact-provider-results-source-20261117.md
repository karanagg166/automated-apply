# Bound provider results before identity ingestion — source checkpoint 2026-11-17

Implementation [8f8f05b979628330bd85b2c38451e1c2ee97441c](https://github.com/karanagg166/automated-apply/commit/8f8f05b979628330bd85b2c38451e1c2ee97441c), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

Transport outcomes now carry a private binding to the consumed dispatch invocation/reservation/provider/request and exact content hash. Changing public outcome fields cannot publish a new finding. Result recording validates the immutable POST admission and commits normalized evidence, full lookup acknowledgment, budget finding and one run-usage entry before identity ingestion. Identical replay returns the retained finding without another usage row or provider request. Unknown results retain full reservations; actuals never refund caps. The budget finish/cooldown operations now offer same-transaction internal helpers while preserving their standalone contracts.

Identity ingestion is separate and idempotent. Current run/company/target checks hold changed or expired contexts for review while preserving the already committed remote result/accounting. Complete ACK failure rolls back identity work alone; it cannot erase a provider finding. Only completed, successfully reconciled profile results with no mailbox/conflict/suppression may justify already-reviewed fallback. Source review found a valid fallback would otherwise be blocked after the first identity check refreshed strong profile evidence; the native preparation/dispatch now permits that qualified no-mailbox fallback while rechecking provider order, opt-in and prior usable finding. Prepared/unknown/error results never qualify.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Bound immutable results, atomic accounting/usage, independent guarded ingestion and qualified fallback; formatter applied |
| Dedicated native PG/loopback | NOT TESTED | 13 new declarations: result-before-ingestion; exact replay; mutated outcome; changed contact; expired context; unknown/full charge; mismatched admission;2 result ACK faults; full lookup expiry ACK;2 usage/budget ACK faults; identity failure preserves result; ingestion receipt ACK; positive completed/reconciled/no-email fallback |
| Earlier fixture/helper impact | NOT TESTED | Existing budget/dispatch fixtures cover refactored helpers; fictional transport gained no-email mode |
| Standard/frontend count | NOT TESTED | 0 new declarations; database/loopback integration slice |
| Current-head build/lint/tests | NOT TESTED | New executed tests0; source-first final combined gate remains deferred |
| Owner enrichment controller | NOT TESTED / INCOMPLETE | Full local-first/controller/host orchestration still remains before public native readiness |
| Actual provider/Mac/runtime/install/timing | NOT TESTED | No actual provider/account action, installation or measured comparison |

Fixed failures include `contact_provider_result_changed`, `contact_provider_result_context_changed`, `contact_provider_result_conflict`, `contact_provider_result_write_ack_failed` and qualified changed-target/context held reasons. No executed failure log, private result body, mailbox, token or raw journal is published.

Final reproduction: coordinated `scripts/run_acceptance.py`, dedicated `contact_result_*` cases and earlier budget/run/lookup/dispatch/identity fixtures, then complete controller/outreach/registry/platform/build/browser/UI contracts. Prior validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 native PG passes,455 distinct; it does not validate this head.58/42 held; provider public readiness false. STOP162/lifetime4/hour1/three quarantines/strict worker receipts0 and saved filters/identity/PDF/focus/history controls remain. No hosted Actions, merge, cleanup, purchase, provider activation or runtime installation.
