# Telegram Naukri controls — source checkpoint 2026-11-16

Implementation [`fe02ace486904062f1ee6e9a7e12eccca9ae5681`](https://github.com/karanagg166/automated-apply/commit/fe02ace486904062f1ee6e9a7e12eccca9ae5681), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Uninstalled source; compilation/tests deferred.

Typed /naukri commands now reuse dashboard services for queue status/add/start/pause/resume/stop, separate preparation automation controls, saved-job listing, preparation intents and individual legacy pause/resume/cancel. They retain the current saved filters, quota/history/account/PDF gates and strict first worker receipt requirement. Queue resume uses the original Start guard; it cannot reset quotas or enable recurring AUTOMATIC without that receipt. The legacy apply command creates preparation intents only. Individual execution controls are labeled as legacy preparation, separately from application queue controls.

Only the verified private owner reaches these commands. The parser validates bot mention, bounded text, allowed argument shape and up to25 exact UUIDs; it rejects excess jobs instead of silently truncating. No reset/refund/unlimited action exists. Mutating commands acquire the owner fence before Telegram state; read status uses a consistent snapshot without the owner lock. Business rejection rolls back its savepoint but acknowledges the incoming update once. Database/ACK failures still roll back the entire update. Commands create no browser click or provider receipt; any subsequent application work has the independent native admission boundary.

Command replies omit raw URLs/query tokens, resume/answer/compensation content and are conservatively bounded. Saved-job discovery lists references/titles only and executes no portal search. Help now names the implemented Naukri namespace while leaving other incomplete legacy command areas explicit.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Typed commands, shared guarded services, consistent read status, mutation fences, rejection rollback, offset/outbox atomicity and bounded replies; formatter applied |
| New standard tests | NOT TESTED | 1 declaration covers namespace, mention, argument/UUID/text bounds and separation of read/preparation/queue control effects |
| New native PostgreSQL tests | NOT TESTED | 5 declarations: pause/unknown/spent history; deduplicated add/private query omission; preparation-only apply and separate controls; status under held owner lock/wrong mention inert; AUTO first-receipt rejection with acknowledged update |
| Compile/Clippy/lint/all suites | NOT TESTED | New executed tests0; final combined gate remains deferred under source-first instruction |
| Actual Telegram/Mac/browser/application/install | NOT TESTED | No real message, provider request, owner-data query, browser action or installation |
| Resource/latency/restart measurements | NOT TESTED | Behavior is source/fixture declarations only, no measured performance claim |
| Complete Telegram/service/platform parity | NOT TESTED | Browser/account/general conversation/preview/reset commands, explicit unknown-prompt reconciliation and remaining Gmail/outreach/provider/platform scope remain unfinished |
| Focus/strict receipts/awake/locked/24h | BLOCKED / NOT TESTED | Existing account/focus/operator migration gates stand; actual strict worker receipts0 |

After all source is integrated, reproduce through `scripts/run_acceptance.py`, including tests/telegram_owner_commands.rs and tests/support/telegram_owner_commands_pg.rs. No new executed failure log exists. Fixed sanitized codes include automatic_first_verified_worker_receipt_required, execution_revision_conflict, queue_backpressure and source/URL denials; private raw command arguments are not logged here.

Last validated source9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 dedicated native PostgreSQL passes,455 distinct; it does not validate this head. Estimate58% complete /42% remaining is unchanged, with no reliable finish time. Continue the [complete-source plan](../plans/completion-execution-20261116.md), combined final testing, reviewed whole-family installation and individually verified platform results. Installed STOP162, lifetime4/hour1, three quarantines, current saved filters/history/identity/PDF, first strict receipt, Gmail read/draft-only and browser focus protections remain. No hosted Actions, merge, live activation or cleanup.
