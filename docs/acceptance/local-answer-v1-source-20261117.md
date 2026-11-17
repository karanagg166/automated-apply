# Local-answer v1 and transient rewrite sharing — source checkpoint2026-11-17

Implementation [dfb7afdb071a4ddbb8e604e1af02eb70e33b4972](https://github.com/karanagg166/automated-apply/commit/dfb7afdb071a4ddbb8e604e1af02eb70e33b4972), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested/uninstalled source; no callback/model/daemon or production request.

Native answer preparation now adopts the deterministic local-answer v1 resolver while preserving existing HTTP/draft provenance. The library separates deterministic extraction, successful sentence matching, needs-input and validation failure. Failed/unsafe rewrite retains deterministic content, fixed error, attempted flag and usage; successful content is matched independently and claims reconstructed. Factual/summary/resolver/low-memory/missing-fact/single-clause exclusions remain. The existing successful rewrite label is sentence-matching provenance, not external verification of personal facts.

Optional callbacks receive only permitted sentence/options data and must perform bounded transport only, without durable reservations/commits inside cancellation. Production service adoption is deterministic/no callback; explicit writer adapters still own their current budgets/IO. Identical overlapping question/context/instructions share at most eight flights. There is no persistent candidate cache; last waiter removes its own nonce-bound entry and aborts transport, while one cancelling waiter leaves other waiters intact. No new DB connection/pool, automatic model startup or configured provider grant.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source/formatting | PASS(source only) | Versioned immutable outcomes, deterministic service resolver and bounded library coalescing; cargo fmt only |
| New standard fixtures | NOT TESTED |7: deterministic/no callback; route/low-memory/single-clause exclusions; missing/constraint abstention; successful versus failed/unsafe provenance; shared request/one waiter cancellation; last waiter cancellation; capacity/no lasting result cache |
| New dedicated PG fixtures | NOT TESTED |2: native deterministic draft/zero usage; missing facts/constraints/no citations or draft/zero usage |
| Current tests/build/check/lint | NOT TESTED |New executed tests0; remaining agreed source precedes combined gates |
| Production callback/model/daemon/Mac/install | NOT TESTED |No callback configured, model/daemon/production SQL or installed-service operation |
| Timing/resources | NOT TESTED |Map limited8 and no persistent cache/pool; no measured inference saving, cancellation or memory comparison |
| Full runtime/tool/platform acceptance | NOT TESTED/incomplete |Conversation/tool/platform source and final inventory/contracts/types/combined/live gates remain |

No private logs, candidate data or screenshots published. Deferred: `cargo test --locked -p automated-apply-agents --lib local_answer`; dedicated disposable PostgreSQL runner including two new ignored fixtures and existing answer/packet/extractive regressions. Commands were not executed. [Source limitations and integration](../agent/local-answer-v1.md).

Earlier general CLI and sentence provider source adds explicit native drafting branches that the legacy application-answer service refused, while retaining private enabled/quota/local-generation flags. Questionnaire remains Cohere-only. This is a qualified behavior extension, not a claim of identical legacy service policy or live provider acceptance.

Last validated9c4ace570535a5856184775f8045ee89eafdd05f:193 standard Rust+262 dedicated PG=455 distinct prior passes, not this head. Estimate58%/42% held. Queue last observed STOPPED162; lifetime4/hour1, three uncertain jobs quarantined, one fourth allowance remaining, strict worker receipts0. Identity/PDF/filter/focus rules remain. No hosted Actions, merge, cleanup, sending/application or installed-service action.
