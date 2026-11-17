# Original public discovery admission — source checkpoint 2026-11-17

Implementation [8cd8e4e707f89804fff60a132b9e09a42ccc40bd](https://github.com/karanagg166/automated-apply/commit/8cd8e4e707f89804fff60a132b9e09a42ccc40bd), branch `feat/rust-agent-runtime`, [PR 50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source; no provider transport has been connected to this admission yet.

Original UUID discovery requests now bind normalized source/query, private source context, one opaque in-memory invocation and a 75-second deadline. Owner-first SERIALIZABLE commits the existing shared provider access window and original private journal atomically. Independent rereads after triggers verify both. Remotive retains its six-hour interval; the other six public sources retain sixty seconds. Replays/reads cannot reconstruct grants, refresh expiry, reset intervals or import jobs. Changed source/query conflicts. Saved requests remain readable after current board configuration is removed. Pending and expired unknown states explicitly distinguish admission from a provider response.

The key is 44 characters and fits the actual owner-preference constraint. Saved journals are bounded to 9 MiB for subsequent retained batch results; no result body is stored yet. Status omits private invocation/context, reports provider HTTP count unknown and confers no application/live verification authority. Commit ambiguity returns a fixed qualified error rather than retrying. No new table/pool/library or runtime entitlement was added.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Atomic original admission, shared source windows, post-trigger ACK, saved read projection and formatting applied; transport/finding retention follow |
| Native PG additions | NOT TESTED | 8 declarations: original/replay identity; changed input/source conflict; removed configuration recovery; fresh-ID rate refusal/missing config; lost invocation expiry; journal-trigger window corruption; journal ACK rollback; saved tamper/size/not-found reads |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests: 0; complete source precedes combined gates |
| Actual native provider / Mac / install | NOT TESTED | No native feed, application, browser, production DB or installation operation in this slice |
| Timing/resources | NOT TESTED | No measured comparison; no transaction will be held across subsequent provider transport; existing shared connection budget retained |

Fixed codes include `public_job_source_rate_limited`, `public_job_request_conflict`, `public_job_commit_outcome_unknown`, `public_job_write_ack_failed`, `public_job_saved_batch_limit`, `invalid_public_job_batch` and `public_job_request_not_found`. No executed failure logs or private evidence is published.

Deferred reproduction: dedicated disposable PostgreSQL `public_job_*`, earlier pure job suites and `uv run --no-project python scripts/run_acceptance.py` after the remaining agreed source. Next: consume only original grants through bounded fixed-host GETs, complete pagination/deduplication and retained findings, then separate atomic startup/job ingestion. Reviewed Apify execution and other runtime/platform source remain. Source fields currently unused by transport are intentional pending connections, not a current build/Clippy acceptance claim.

Last validated `9c4ace570535a5856184775f8045ee89eafdd05f` remains 193 standard +262 dedicated native PG =455 distinct passes, not current-source evidence. Estimate remains 58% /42%. STOP162, lifetime4/hourly1, three uncertain quarantines, zero strict worker receipts and all identity/PDF/filter/focus constraints remain unchanged. No hosted Actions, merge, cleanup, sending or installation occurred.
