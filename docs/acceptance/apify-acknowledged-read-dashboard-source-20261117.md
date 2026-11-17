# Durable acknowledged-read dashboard recovery — source checkpoint2026-11-17

Implementation [bcc1b182e2d32810dfd12d637b02e6030e6a3742](https://github.com/karanagg166/automated-apply/commit/bcc1b182e2d32810dfd12d637b02e6030e6a3742), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested/uninstalled source; no actual UI screenshot, browser/provider recovery, production SQL or Mac acceptance.

The dashboard retains a separate opaque parent/read UUID pointer under the original discovery Web Lock. Explicit read consent may issue only an empty keyed PUT. Inspection/reload uses saved GETs; missing browser read pointers adopt the server's original last-read UUID. A linked read can restore a missing original browser pointer using validated saved owner data. Unknown paid starts without an acknowledged run refuse read admission. Response-loss/uncertain read pointers remain retained and new search stays disabled.

Complete saved pages use empty local completion, then the original local discovery completion, without another provider read. After review, an expired/spaced-out read with no complete pages/finding and allowance remaining can prepare a fresh UUID without dispatch; the next PUT requires fresh consent. Parent terminal review clears only linked browser pointers while preserving server history and held budgets. Response validation checks IDs/source, fixed3-round/4GET bounds, preliminary full-cap accounting and minimum observed counts before allowing recovery decisions. Current configured readiness gates new read consent but is not required for saved inspection. No profile facts, tokens, provider IDs or search criteria are persisted in the read pointer.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source/formatting | PASS(source only) | Separate durable read helper/UI, shared original Web Lock, source/accounting validation, explicit read consent, saved pointer restoration and local page/original completion |
| New helper declarations | NOT TESTED |10: consent/no dispatch; pre-PUT persistence/response loss; unknown saved replay; local page/original completion; unknown start refusal; server UUID adoption; reviewed next UUID; corrupt response; missing original pointer restoration; concurrent callers/single PUT |
| New component declarations | NOT TESTED |2: separate read consent/empty PUT with retained original pointer; unknown read reload GET only/no terminal inference |
| New browser journey | NOT TESTED |1: fictional acknowledged read response loss, reload saved GET, local page/original completion and retained UUID; screenshot is only a deferred fixture output |
| Current tests/build/check/lint/types | NOT TESTED |New executed tests0. Remaining agreed source precedes combined gates |
| Actual browser/provider/Mac/install | NOT TESTED |No browser launched, screenshot captured, provider request, production SQL or installation operation |
| Timing/resources | NOT TESTED |Existing Web Lock and backend shared slot; no new recurring task/pool; no measured comparison |
| Full startup/runtime/tool/platform/combined acceptance | NOT TESTED/incomplete |Remaining agreed source and combined/live gates still open |

No private logs/screenshots are published. Fixed recovery refusal retains the original browser pointers. These reads cannot start/abort an Actor, reset Naukri Apply allowances or claim final billing/independent termination. Fixture declarations are not evidence of live automation.

Deferred reproduction: `pnpm -C frontend test -- tests/job-discovery-read-attempt.test.ts tests/job-discovery.test.tsx tests/job-discovery-attempt.test.ts`; after final build, isolated Brave/Edge-selected runner `pnpm -C frontend e2e -- tests/e2e/acknowledged-read-recovery.spec.ts`. Full frontend type/format/unit/gateway/paid/public discovery and browser regressions remain final combined gates. Tests have not run during this source checkpoint.

Last validated checkpoint remains9c4ace570535a5856184775f8045ee89eafdd05f:193 standard Rust+262 dedicated PG=455 distinct passes, which do not validate this head. Estimate held58%/42%. Last observed queue STOPPED162; lifetime4/hour1, three uncertain jobs quarantined, one fourth admission remaining, strict worker receipts0. Current identity/PDF/filter/focus constraints remain. No hosted Actions, merge, cleanup, sending/application, paid provider or installed-service operation. Connected GitHub publication is preferred now that its tools are available again.
