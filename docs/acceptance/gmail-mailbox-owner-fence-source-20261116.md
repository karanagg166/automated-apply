# Shared mailbox owner fence — source correction 2026-11-16

Implementation [dabd37b2efe6bad0fca96df475c202cbdf037bdb](https://github.com/karanagg166/automated-apply/commit/dabd37b2efe6bad0fca96df475c202cbdf037bdb), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested and uninstalled.

Source review found that older local-mailbox lifecycle writers held only their local advisory lock, while new outreach/read-account services used the shared owner row. This permitted an account-family race and did not advance older serializable snapshots. Local mailbox locks now acquire/advance the shared owner row before their advisory lock, including draft/read guards, while retaining no lock across provider IO. The local OAuth callback independently refuses the currently assigned outreach identity after exchange. Owner bootstrap INSERTs in execution/browser storage explicitly supply timestamp columns for ORM schemas without database defaults. Existing conversation JSON/messages/TTL remain unchanged; only lock metadata advances.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source correction | PASS (source only) | Shared ordering, reverse identity check and timestamp bootstrap; formatter applied |
| New native PostgreSQL tests | NOT TESTED | 3 declarations: first owner with nondefault timestamps/private conversation preservation; outreach identity assigned during local exchange; old serializable snapshot fails after a local writer |
| Existing mailbox/account/native regressions | NOT TESTED | All retained suites remain deferred; no new standard declaration |
| Compile/build/Clippy/combined gate | NOT TESTED | New executed tests0; source-first instruction retained |
| Actual account/provider/Mac/install | NOT TESTED | No real account lookup, mail read/write, browser or installed change |
| Timing/resources/restart/focus/24h | BLOCKED / NOT TESTED | Shared ordering adds owner queries; no measured cost or acceptance claim |

After all source is assembled, reproduce with `scripts/run_acceptance.py`, including `tests/support/gmail_workspace_account_pg.rs`, local mailbox/draft/alert, read account, owner-fence and native browser fixtures. No executed failure log exists. Sanitized expected outcomes: gmail_separate_outreach_account_required, execution_write_ack_failed, gmail_account_write_ack_failed and PostgreSQL40001 for an old conflicting snapshot. No private conversation or account data is published. A whole-family STOP cutover remains required; mixed Python/Rust writers are not accepted.

Prior9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 disposable native PG passes,455 distinct; it does not validate this head. Estimate58% complete/42% remaining held. Continue explicit reviewed Gmail draft dispatch and all remaining source/final gates. STOP162/lifetime4/hour1/three quarantines/strict worker receipts0 and saved filters/account/PDF/focus/history remain. No hosted Actions, merge, cleanup or real application activation.
