# Retained research to local contacts — source checkpoint 2026-11-17

Implementation [9977246db53abf0795650b22e6fff3d4b9f1a282](https://github.com/karanagg166/automated-apply/commit/9977246db53abf0795650b22e6fff3d4b9f1a282), branch `feat/rust-agent-runtime`, [PR 50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source. Native owner endpoint and dashboard integration follow.

The paid research controller now completes retained findings through a second owner-first serializable local transaction. It checks the exact original input, current configuration/rights, company snapshot, required employer domain and 24-hour finding lifetime. Changed context records a qualified held result. Accepted data reuses conservative identity/suppression/ACK rules with explicit public_search provenance, unconfirmed provider identity and original observation times. Local receipt, people/contact changes and terminal paid journal commit atomically. A failed local completion preserves the earlier finding and never repeats the paid search.

The original acquisition phase remains available separately to retain evidence before local work. Normal controller execution acquires once and completes locally; replay can finish an existing valid finding even with no remote client. Completed reads return the original selected history without refreshing facts or writing. Rate/auth/unknown findings remain qualified and do not become contacts. Held results cannot silently restart after settings change. Provider charges remain unverified and the local request allowance remains consumed.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Shared batch ingestion, original public-search provenance/time, current-context holds, coupled receipt/journal ACK, local-only recovery and selected history; formatting applied |
| Standard additions | NOT TESTED | None in this slice; earlier source remains unrun |
| Native PG / loopback HTTP | NOT TESTED | 12 declarations: official complete flow/replay; public original observation; company hold; disabled/current settings hold; stale finding; local ACK rollback/recovery without client; coupled receipt corruption; concurrent completion; completed privacy; empty result; missing domain; manual controller without paid client |
| Host / frontend additions | NOT TESTED | None in this slice; UUID owner endpoint and durable dashboard recovery remain pending |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests: 0; complete source precedes combined gates |
| Actual Mac/provider/install | NOT TESTED | No live credential, account, provider execution, real budget, browser, production or installation action |
| Timing/resources | NOT TESTED | Source transaction/connection/bounds only; no measured runtime comparison |

Fixed codes include `public_research_configuration_changed`, `public_research_company_changed`, `public_research_company_domain_required`, `public_research_finding_expired`, `public_research_local_receipt_conflict` and `public_research_write_ack_failed`. No executed failure logs or private evidence are published.

Deferred reproduction: complete dedicated disposable PG `people_search_*`, `people_*` and shared contact/budget/company suites, then `uv run --no-project python scripts/run_acceptance.py` and later provider/UI/install/live gates. Continue the native UUID owner endpoint, durable dashboard recovery, startup provider orchestration and remaining agreed full source before coordinated tests and operational acceptance.

Last validated `9c4ace570535a5856184775f8045ee89eafdd05f` remains 193 standard + 262 dedicated native PG = 455 distinct passes, not current-source evidence. Estimated completion remains 58% / 42%. Last observed STOP revision 162, lifetime allowance 4/hourly 1, three uncertain quarantines, zero strict worker receipts and all current filters/identity/PDF/focus rules remain unchanged. No hosted Actions, merge, cleanup, sending or installation occurred.
