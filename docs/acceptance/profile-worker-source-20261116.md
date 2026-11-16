# Profile reconciliation worker — source checkpoint 2026-11-16

Implementation [`b6b1f4aeea4f52de831e816e27e27b3c29ecaebf`](https://github.com/karanagg166/automated-apply/commit/b6b1f4aeea4f52de831e816e27e27b3c29ecaebf), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Source only; no installed/runtime/provider change.

The worker now schedules version-pinned profile comparison independently of application quotas. It rechecks confirmed canonical facts, selected approved account, queue revision, local preference, execution mode and profile-sync policy. Only separately approved summary/skill changes can progress to a Save intent. Skill editor preparation preserves the complete original chip prefix and permits only verified additions; it carries no Save permit. A Save receives a two-second permit only after its UNKNOWN intent and append-only admission record commit.

A Save-click report is not persistence evidence. A different ordinary profile document must independently show the exact intended summary or complete prepared skill set. Positive verification closes only the active pointer and retains admission, verification and previous verified intent metadata, allowing the next separately approved field. Unknown, mismatched, malformed or absent intent references never clear a save or authorize repetition. A lost write permits one early read-only reconciliation, then the normal interval. This is a deliberate improvement over the legacy global active-save pointer, which stayed occupied even after successful verification.

Optional saved-resume verification binds actual decrypted/current confirmed private PDF bytes and resource version; matching a filename cannot pass. Dashboard questions use field/reference fingerprints, skip login/contact-email differences, resolve superseded notices and require write acknowledgements. No canonical fact is overwritten. The existing local preference parser is shared with Apply admission, without changing its saved policy or quotas.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source implementation | PASS (source only) | Worker, immutable records, notices and minimal shared preference helper written; formatter applied |
| New standard regressions | NOT TESTED | 2 declarations: typed intent corruption; transport redaction/preparation without Save permit |
| New native PostgreSQL regressions | NOT TESTED | 9 declarations: periodic single lease; summary intent/independent read/next field; preserved skills; uncertain Save; local manual/draft/disabled and OFF; contact separation and notices; suppressed write rollback; encrypted PDF bytes; account/confirmation/lease changes |
| Build/lint/Clippy/contracts/all suites | NOT TESTED | New tests executed0; final combined acceptance remains deferred |
| Actual Mac/browser/profile Save/PDF download | NOT TESTED | No provider request, browser action, live profile modification or data access |
| Authenticated queue/native integration | NOT TESTED | Library primitives only; broker, questionnaires, discovery and scheduler remain unfinished |
| Production installation / first application receipt | BLOCKED | Whole-family migration/grants and browser/account gates remain; previous strict receipt count0 |
| Focus/restart/locked/24h resources | NOT TESTED | Prior qualified focus findings stand; no resource or speed comparison |

Prior validated checkpoint remains9c4ace570535a5856184775f8045ee89eafdd05f:193 standard +262 dedicated PostgreSQL tests,455 distinct. It does not validate this head. Engineering estimate remains58% complete /42% remaining.

Final reproduction uses `scripts/run_acceptance.py` after all planned source is integrated; new declarations live in `tests/profile_sync_intents.rs` and `tests/support/profile_sync_work_pg.rs`. All fixtures are fictional and require the guarded disposable database. No executed failure logs exist. Expected rejection codes include profile_sync_attempt_requires_review, independent_profile_reload_required, provider_saved_resume_differs_from_canonical_pdf, queue_lease_lost and execution_write_ack_failed. Lost commits remain unknown; no Save replay.

Scheduling checks active leases/next interval before loading canonical resources; resource inventory is capped at10,000, and private PDF verification is capped at2,000,000 bytes. These are source bounds, not measured latency/RSS gains. No model/network work holds this transaction because this slice performs none. Complete authenticated native dispatch, discovery/job ingestion, original questionnaire/owner replies and remaining ports, then run the combined checks and reviewed STOP-only install/live acceptance under the [plan](../plans/completion-execution-20261116.md). Lifetime4/hour1, three quarantines, first-receipt prerequisites, Gmail read/draft-only and focus constraints remain.
