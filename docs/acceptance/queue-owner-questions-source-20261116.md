# Scoped queue owner questions/replies — source checkpoint 2026-11-16

Implementation [`c7dd77dabd463b8d3a3931915b19a005527c787c`](https://github.com/karanagg166/automated-apply/commit/c7dd77dabd463b8d3a3931915b19a005527c787c), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Source only; no prompt, Telegram delivery, model call or installation.

Original questionnaire questions now have stable per-work/packet/step identities, current profile/revision/options/length bindings, two-day envelopes and retained delivery/message metadata. Existing envelopes are returned unchanged, including expired or uncertain delivery history; they are not reenrolled or resent. Queue, current submitting packet/account/PDF and exact original step are rechecked before an owner reply. Dashboard source provenance is recorded as owner_dashboard, correcting the legacy queue helper's owner_telegram label for dashboard replies.

An accepted factual reply persists its expiry and provenance, keeps reuse OFF and queues refresh_questionnaire_profile. Account/PDF, listing and original form must refresh before a separately admitted answer. Original Apply admissions remain unchanged; no Save/Apply permit is produced. Question, work revision and outbox event require atomic exact acknowledgements. Expired, already answered, stopped, changed or wrong-revision questions reject without mutation.

Explicit reuse approval is separate, rechecks the current packet/profile/expiry and saves the existing full256-bit,50-character bank identity. The old oversized JSON-only legacy key can be converted without discarding hash bits. Approval does not authorize an application and the source never changes a canonical candidate fact. Actual HTTP/Telegram authentication/transport and the complete grounded preparation runner are still pending integration; these are host-internal primitives.

| Gate | Result | Evidence / limitation |
| --- | --- | --- |
| Source implementation | PASS (source only) | Stable questions, scoped replies, explicit reuse, provenance and exact ACKs; formatter applied |
| New native PostgreSQL regressions | NOT TESTED | 5 declarations: ask deduplication/reply refresh/no second Apply; revision/expiry/Stop/step changes; separate reuse approval/full hash; dropped reply/event ACK rollback; expired message-history retention |
| New standard tests | NOT TESTED | 0 additional declarations in this slice; prior source-phase factual-rule/oracle declarations remain unrun |
| Compilation/Clippy/lint/full suites | NOT TESTED | New tests executed0; final combined gate remains deferred |
| Native HTTP/Telegram/model/scheduler integration | NOT TESTED | Not complete; no operational owner prompt/reply claim |
| Actual Mac/live DB/browser/provider/message/application | NOT TESTED | No live data query, delivery or external action |
| Install/strict receipt/focus/restart/24h | BLOCKED / NOT TESTED | Existing prerequisites and actual focus findings stand; strict receipt count0 |

Prior fully validated checkpoint9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard +262 dedicated native PostgreSQL passes,455 distinct. It does not validate this head. Approximate engineering estimate remains58% complete /42% remaining.

Final reproduction is `scripts/run_acceptance.py` after all planned source is integrated. New fictional declarations are tests/support/queue_owner_questions_pg.rs and use the guarded original-Apply/encrypted-PDF fixture. No executed failure logs exist. Relevant rejection codes include question_revision_conflict, question_already_answered, question_expired_or_application_cancelled, questionnaire_question_context_changed, current_answer_required and execution_write_ack_failed. Unknown commits never authorize replay.

Question persistence/reply/reuse run under a serializable owner transaction with current packet/context checks and no network/model IO. Text is bounded to4,000 characters; delivery metadata remains private. No measured speed, RSS, Stop latency or resource claim. Expired/uncertain prompts deliberately remain retained; any future explicit reconfirmation flow must preserve their correlation and never automatically replay delivery. Continue grounded preparation and native/legacy owner-route/Telegram/scheduler integration, then remaining services/providers/platforms under the [completion plan](../plans/completion-execution-20261116.md). Installed STOP162, lifetime4/hour1, three quarantines, filters, first-receipt, Gmail read/draft-only and focus constraints remain unchanged.
