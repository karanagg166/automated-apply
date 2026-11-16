# Telegram local commands — source checkpoint 2026-11-16

Implementation [f939e54eaf8d9b8e3222035c618363f9fc26511b](https://github.com/karanagg166/automated-apply/commit/f939e54eaf8d9b8e3222035c618363f9fc26511b), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Uninstalled and untested source.

Verified private-owner commands now support local runtime status, saved connection metadata, saved discovery status, public-HTTPS URL previews and selection-memory reset. `/apply URL` records a preview/policy audit only: no fetch, packet generation, browser work or submission. Disabled platform policy produces an audited denial. `/jobs` reports durable legacy and public-feed schedules; expired running discovery becomes recovery_required, and failed/incomplete zero-job runs are not described as successful searches. `/agents runs` retains its separate saved-review meaning.

`/reset` uses the actual legacy owner-hashed Telegram context key, clears only job/project selection memory and saves a ten-minute TTL. Shared campaign memory, Codex identities/transcripts/backups, application history and spent admissions remain untouched. The audit uses the existing actor/request key and shared declaration-order native hash. Previous conflicting or uncertain intents are retained without adoption or replay. Matching old results are validated and returned. Selection writes, operation audit, update offset and outgoing acknowledgment are atomic; suppressed write acknowledgments abort the update.

Status avoids the owner fence. Connection replies query only saved Gmail/portal metadata and public selected-browser heartbeat projection, excluding credentials, email identity and URL queries. Saved state is explicitly distinguished from a live capability/identity check; Telegram does not assert that the Rust API listener was probed. The complete legacy provider/CLI/MCP registry and natural conversation parity remain unfinished. This slice does not remove them from scope. The legacy /start code shape continues to show help, without account-pairing authority.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Shared hashes/audit, policy preview, bounded private-owner parser, saved status, context-only reset; formatter applied |
| New standard tests | NOT TESTED | 2 declarations: command/URL/mention/effect bounds; actual legacy context-key AST comparison for3 owners. Existing native hash oracle gains2 cases |
| New native PostgreSQL tests | NOT TESTED | 8 declarations: preview/no authority; disabled preview; isolated reset/history; suppressed-write rollback; old conflicting intent; lock-free secret-free status; stale discovery; unauthorized/forward/wrong mention |
| Compile/Clippy/lint/combined suites | NOT TESTED | New executed tests0; source-first final gate remains deferred |
| Actual Telegram/Mac/provider/browser/install | NOT TESTED | No real message, owner-data query, provider check, browser action or installed runtime change |
| Performance/resource/restart comparison | NOT TESTED | No measured gain or current-head uptime claim |
| Full parity/platform receipts | BLOCKED / NOT TESTED | Natural conversation, complete registry, unknown prompt reconciliation and remaining Gmail/outreach/provider/platform source pending; operator/account/focus gates remain |

After complete source integration, use `scripts/run_acceptance.py`, including tests/telegram_local.rs, the extended native hash corpus and tests/support/telegram_local_pg.rs. Sanitized new codes: connection_disabled, request_id_conflict, invalid_discovery_timeout, telegram_local_write_ack_failed and telegram_local_rollback_unconfirmed. There is no new executed failure log. Raw arguments/URL queries/audit payloads remain private.

Prior9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 native disposable PostgreSQL passes,455 distinct; it does not validate this head. Estimate58% complete/42% remaining held. Continue the full plan before final combined testing and reviewed installation/live acceptance. STOP162/lifetime4/hour1/three quarantines/strict receipts0, current filters/account/PDF/history/focus and Gmail READ + CREATE DRAFT ONLY remain. No hosted Actions, merge, cleanup or live activation.
