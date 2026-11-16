# Telegram selected-browser controls — source checkpoint 2026-11-16

Implementation [8d85a956aa086c3306ce5f6ccc8af8347215954a](https://github.com/karanagg166/automated-apply/commit/8d85a956aa086c3306ce5f6ccc8af8347215954a), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Uninstalled source; final combined tests remain deferred.

The verified private owner can use `/browser status` and version-bound open/prepare/pause/resume/cancel commands through the selected ordinary profile. `/chrome` remains a compatibility alias. The adapter uses the existing queue, selected-profile/session/version, current packet/task, opt-in, expiry and capacity guards. It never starts a browser/window or chooses a fallback profile. Filling retains fresh inspection and separate exact-field approval. No submission command exists.

Telegram request IDs bind the chat/update. Saved actor provenance distinguishes Telegram from dashboard requests, including idempotent retries; a matching request ID from another actor is rejected. Mutation fencing precedes Telegram state locking; status avoids the owner lock. Incoming offset, queue intent and outgoing acknowledgment commit together. Expected business denials roll back their savepoint; database/ACK uncertainty rolls back the complete incoming update. Replies omit browser secrets, URL queries, answers and resume content.

| Gate | Result | Evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Parser, selected-profile queue adapter, trusted actor binding, shared command guards and receipt/status projection; formatter applied |
| New standard tests | NOT TESTED | 1 declaration: aliases/mention/UUID/revision bounds and refusal of fill/submit/script/focus/settings actions |
| New native PostgreSQL tests | NOT TESTED | 5 declarations: one deduplicated command/no fill authority; offline refusal; lock-free secret-free status; different-actor nonce conflict; stale revision/unsupported actions |
| Compilation/Clippy/all suites | NOT TESTED | New executed tests0; no current-head validation claim |
| Actual Telegram/Mac/browser/install | NOT TESTED | No real message, browser action, profile inspection or installed runtime change |
| Focus/strict receipt/awake/locked/24h | BLOCKED / NOT TESTED | Prior focus/account/operator gates stand; current strict worker receipts0 |
| Performance/resource comparison | NOT TESTED | No measured latency or resource claim |

After the remaining source is integrated, run `scripts/run_acceptance.py`, including `tests/telegram_browser_commands.rs` and `tests/support/telegram_browser_commands_pg.rs`. No new executed failure log exists. Sanitized refusal codes include PROFILE_OFFLINE, PROFILE_COMMANDS_DISABLED, command_id_conflict, packet_revision_conflict and profile_queue_full. Private arguments/logs remain private.

Prior validated9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 dedicated native PostgreSQL passes,455 distinct, and does not validate this source. Estimate58% complete/42% remaining is unchanged. Continue Telegram account/general conversation/preview/reset/reconciliation, Gmail/outreach/providers/platforms, then combined tests and reviewed installation/live acceptance. STOP162, lifetime4/hour1, three quarantines, saved filters/account/PDF/history, strict first receipt and focus rules remain. No hosted Actions, merge, cleanup or production activation.
