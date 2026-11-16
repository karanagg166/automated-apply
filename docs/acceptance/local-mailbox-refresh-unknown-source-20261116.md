# Local mailbox uncertain refresh — source checkpoint 2026-11-16

Implementation [78f2df50b45375d6e1e9ebabf9d2333adfe52e93](https://github.com/karanagg166/automated-apply/commit/78f2df50b45375d6e1e9ebabf9d2333adfe52e93), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Uninstalled and untested source.

While porting approved local-mailbox alerts, source review found the older local account service could refresh again after an expired lease or transport failure. It now records credential-free immutable refresh attempts before IO. An abandoned lease, failed response or positive result arriving after expiry requires reauthorization; access credentials are cleared and the unknown outcome remains. No refresh repeats after restart. Definite invalid credentials retain a distinct failed_reauthorization_required outcome. New OAuth remains an explicit separate operation; retained attempt history survives replacement of the current account record. Owner locks are not added across provider IO.

| Gate | Result | Evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Durable attempt records, expiry/unknown guards, unchanged token purpose and fixed provider transport; formatter applied |
| New PostgreSQL tests | NOT TESTED | 2 declarations: abandoned restart/no replay; positive late result. Existing revoked/transient test updated to require reauthorization after either response class and assert no second call |
| New standard tests | NOT TESTED | No new declaration; existing token/local lifecycle corpora must revalidate |
| Compile/Clippy/all suites | NOT TESTED | Executed new tests0; final source-first gate deferred |
| Actual account/provider/Mac/install | NOT TESTED | No real refresh, authorization, mail read, owner-data query or runtime change |
| Timing/resources/restart/focus/24h | BLOCKED / NOT TESTED | Fixtures/source only; no measured comparison; prior external gates remain |

After all source is integrated, run `scripts/run_acceptance.py`, including the two new local mailbox cases and existing account HTTP/draft/refresh tests. Fixed codes: gmail_refresh_in_progress, gmail_refresh_unavailable, gmail_refresh_lease_expired, gmail_read_draft_account_not_connected. No executed new failure log or private token/identity bytes are published.

Prior9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 native disposable PostgreSQL passes,455 distinct; it does not validate this head. Estimate58% complete/42% remaining held. Continue approved alerts, three-role workspace/drafts and all remaining source, then combined tests and reviewed installation/live proof. STOP162/lifetime4/hour1/three quarantines/strict receipts0, saved filters/account/PDF/history/focus and Gmail READ + CREATE DRAFT ONLY remain. No hosted Actions, merge, cleanup or live activation.
