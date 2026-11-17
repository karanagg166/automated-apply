# Native local fallback — source checkpoint2026-11-17

Implementation [7c20bb796d9e3b02dd5cd50fd7b5959ea6c5f99f](https://github.com/karanagg166/automated-apply/commit/7c20bb796d9e3b02dd5cd50fd7b5959ea6c5f99f), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested/uninstalled source. No real provider, daemon, model or production operation.

Explicit local fallback composes after eligible primary availability/quota/transport/schema failure. It never selects another remote provider. Original writing transport time is split55% primary/remainder local while retaining provider-specific bounds; reservation/token/cooldown COMMITs are outside cancellation. Slow/unknown persistence is never a refunded or renewed attempt. Both ledgers remain consumed independently; actual selected provider/model and selected-attempt usage are returned, with fixed warnings retaining primary reservation provenance. Existing local cloud-disabled/model checks and final grounding/context stamps still gate content. Unknown ledger/context, unsafe CLI tool/init/policy or usage-overrun failures stop. The separate questionnaire writer forces fallback off and readiness refuses a general fallback-capable settings object. See [operator/source limits](../agent/local-fallback.md).

MCP source lists now wrap their arrays in an object structured result; the existing framed fixture asserts that envelope. No new API route or provider authority is added by this correction.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source/formatting | PASS(source only) | Shared policy/deadlines, transport-only caps, selected provenance and questionnaire separation; cargo fmt only |
| New standard fixtures | NOT TESTED |4: independent local opt-in/no local chaining; original deadline slices; unsafe/unknown error refusal; questionnaire Cohere-only isolation |
| New dedicated PG/loopback fixtures | NOT TESTED |6: original+local consumed accounting/actual draft; disabled and deterministic no dispatch; local metadata refusal/no private prompt; unknown ledger/usage-overrun no fallback; slow primary/deferred COMMIT deadline; changed candidate context |
| Existing framed MCP fixture | NOT TESTED |Source array object envelope assertion updated |
| Current tests/build/check/lint | NOT TESTED |New executed tests0; remaining agreed source precedes combined gates |
| Actual provider/daemon/Mac/install | NOT TESTED |No network model/metadata request, daemon/start/pull, production SQL or installation |
| Timing/resources | NOT TESTED |Original request/gate/connection reused; one optional local client, no pool/recurring task/cache added. Timing assertions are deferred fixtures, not measurements |
| Full runtime/provider/platform acceptance | NOT TESTED/incomplete |Sentence rearranger, local conversation/tools/platforms and final inventory/contracts/types/combined/live gates remain |

No raw logs, private candidate data or screenshots published. Deferred commands: `cargo test --locked -p automated-apply-agents --lib local_fallback`; questionnaire unit and dedicated disposable PG harness including six new ignored fixtures plus existing cloud/Ollama/CLI/MCP regressions. Commands were not executed. Fixed deadlines rely on the pinned local reqwest source documenting request timeout through response body completion; no provider behavior was inferred from a URL or model name alone.

Last validated9c4ace570535a5856184775f8045ee89eafdd05f:193 standard Rust+262 dedicated PG=455 distinct prior passes, not this head. Estimate58%/42% held. Queue last observed STOPPED162; lifetime4/hour1, three uncertain jobs quarantined, one fourth allowance remaining, strict worker receipts0. Identity/PDF/filter/focus rules remain. No hosted Actions, merge, cleanup, sending/application or installed-service action.
