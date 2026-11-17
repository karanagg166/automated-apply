# Bounded conversation memory — LOCAL source checkpoint2026-11-17

Local implementation `4ee520509821b39e5aaa8c9a5840fd688b6fcf9b`, branch `feat/rust-agent-runtime`. NOT pushed/published under current owner local-only direction. Untested/uninstalled source.

Memory reuses the existing private owner-hash key, eight category/time entries, ten unique job UUIDs and ten-minute selection lifetime. Load takes the existing owner fence before row locks and retains the exact original saved-row expectation. Expired selection produces a fresh in-memory proposal without rewriting the saved row on load. Writes compare the original row, retain conversation identity except explicit reset, and ACK exact values after triggers. Explicit reset clears bounded selection/history and changes conversation UUID; no application, job outcome or Codex transcript is removed. Malformed/oversized/unknown/incoherent memory remains saved and refuses automatic overwrite. Callers must verify actor/bot binding separately and roll back on errors.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source/formatting | PASS(source only) | Bounded memory/TTL/identity/selection, opaque saved expectation, owner-before-row lock and post-trigger ACK; cargo fmt only |
| New pure fixtures | NOT TESTED |4: valid/legacy shape/no raw message; unique bounded selected IDs; category/time-only history; malformed intent/rank/flags/question controls |
| New dedicated PG fixtures | NOT TESTED |6: owner-key isolation/eight-entry retention; expired proposal/no load rewrite; corrupt/oversized preservation; explicit reset/stale-row refusal; after-trigger ACK/rollback; nonpositive owner refusal |
| Current tests/build/check/lint | NOT TESTED |New executed tests0; full remaining source precedes combined gates |
| Conversation dispatch/API/classifier | NOT TESTED/incomplete |Storage primitives only; orchestration/binding/operation replay and read-only responses still need composition |
| Actual DB/provider/browser/Mac/install | NOT TESTED |No production DB, model, browser, message or installed-service operation |
| Timing/resources | NOT TESTED |Existing caller transaction/fence/owner_preferences; no pool/task added. No measured contention or resource comparison |
| Full project acceptance | NOT TESTED/incomplete |Remaining local conversation/tools/platform source; final inventory/contracts/types/combined/live gates remain |

No private logs, owner messages, candidate data or screenshots published. Deferred `cargo test --locked -p automated-apply-agents --lib conversation::memory`; disposable PG runner including six new ignored cases plus existing Telegram/owner lock/operation-history regressions. Commands were not executed. This memory is selection context, never approval, submission evidence or a provider grant.

Last validated9c4ace570535a5856184775f8045ee89eafdd05f:193 standard Rust+262 dedicated PG=455 distinct prior passes, not current-head validation. Estimate58%/42% held. Last observed queue STOPPED162; lifetime4/hour1, three uncertain jobs quarantined, one fourth allowance remaining, strict worker receipts0. Identity/PDF/filter/focus rules retained. No GitHub push/PR/publication, hosted Actions, merge, cleanup, sending/application or installation.
