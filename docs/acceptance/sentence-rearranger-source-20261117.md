# Explicit approved-sentence rearranger — source checkpoint2026-11-17

Implementation [065bf87f9dd77917141e06651165380bddbffe72](https://github.com/karanagg166/automated-apply/commit/065bf87f9dd77917141e06651165380bddbffe72), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested/uninstalled source; no local daemon/model or production request.

The missing legacy provider branch is now in native source: selected Ollama with `OLLAMA_ENABLED=false` and explicit `OLLAMA_GENERATION_AUTHORIZED=true` uses a closed approved-sentence `/api/chat` writer. Generic enabled Ollama remains distinct. Only exact prepared whole sentences or existing narrow variants are sent, with answer-only schema/no tools/no stream, keep_alive0 and bounded local context/thread/output options. Model citations are refused; existing extractive matching reconstructs claims/quotes locally and checks complete coverage. No model-supplied sentence may add, omit, merge or repeat a fact. Selected local model/assistant/complete/stop, remote metadata, tool calls, usage and64KiB chat replies are checked.

The existing local metadata proof still precedes the private prompt. Shared optional ledger/semaphore/original transport deadline and current candidate/job generation checks remain. No daemon start/pull, new pool, provider retry or application authority. This provider path does not implement or claim acceptance of the legacy internal LocalAnswerEngine v1 provenance/coalescing contract; that separate item remains open.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source/formatting | PASS(source only) | Closed sentence plan/chat, explicit provider branch and exact local claim reconstruction; cargo fmt only |
| New standard fixtures | NOT TESTED |6: reorder/coverage; narrow variant; missing/injected facts/limits; private bounded chat payload; explicit selected-provider consent; strict envelope/no tools |
| New dedicated PG/loopback fixtures | NOT TESTED |4: explicit chat/budget/grounded draft; permission/locality/no private prompt; tools/added facts/usage/size/no retry; deterministic no model/current candidate stamp |
| Existing fixture alignment | NOT TESTED |Shared fictional Ollama handler now has chat response from permitted sentences while retaining generic generate cases |
| Current tests/build/check/lint | NOT TESTED |New executed tests0; remaining agreed source precedes combined gates |
| Actual daemon/model/Mac/install | NOT TESTED |No actual local metadata/generation, model install/pull, production SQL or installed-service change |
| Timing/resources | NOT TESTED |Existing connection/gate/client/ledger; no pool/cache/recurring task; configured options are not measured resource results |
| Full local AI/runtime/platform acceptance | NOT TESTED/incomplete |Internal v1 engine/coalescing and conversation/tools/platforms; final inventory/contracts/types/combined/live gates remain |

Primary [Ollama chat API](https://docs.ollama.com/api/chat) and [structured output guidance](https://docs.ollama.com/capabilities/structured-outputs) were read as design references, not daemon/model evidence. An initial inaccessible documentation URL was corrected; no API endpoint was probed. No raw logs, candidate data or screenshots published.

Deferred: `cargo test --locked -p automated-apply-agents --lib rearranger`; Ollama unit regressions; dedicated disposable PostgreSQL harness including four new ignored fixtures and existing optional-provider/fallback/source-contract regressions. Commands were not executed. [Source setup/limits](../agent/local-fallback.md).

Last validated9c4ace570535a5856184775f8045ee89eafdd05f:193 standard Rust+262 dedicated PG=455 distinct prior passes, not this head. Estimate58%/42% held. Queue last observed STOPPED162; lifetime4/hour1, three uncertain jobs quarantined, one fourth allowance remaining, strict worker receipts0. Identity/PDF/filter/focus rules remain. No hosted Actions, merge, cleanup, sending/application or installed-service action.
