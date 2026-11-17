# Paid discovery review and durable dashboard recovery — source checkpoint2026-11-17

Implementation [ae755950d35e4f1026f2180a9863c331265dc590](https://github.com/karanagg166/automated-apply/commit/ae755950d35e4f1026f2180a9863c331265dc590), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested and uninstalled source; no new actual UI screenshot/browser/provider or Mac acceptance.

Dashboard source now offers saved-ready native paid sources alongside public feeds. Paid sources require separate budget opt-in before preview and existing reviewed-run consent after a ready preview. Changing criteria clears both permissions. Preview displays selected estimates, run/month caps and a fixed blocker; missing paid estimates are described as unavailable, never free. Blocked or missing-ready previews cannot execute. Results display the retained full-cap reservation and unverified final billing. Company/provider prerequisites remain setup requirements and are not inferred from UI availability.

The existing durable UUID/source pointer and Web Locks remain unchanged. Reload uses saved GET only. Retained findings complete through an empty local-only POST without renewed paid start consent or another PUT. An uncertain start retains its pointer and cannot prepare a new search. Native paid response validation now requires positive bounded six-decimal full-cap accounting and preliminary billing before terminal review/pointer release; corrupt, missing, refunded/final or oversized accounting refuses. Legacy saved rows remain separately qualified by original_scope_available=false.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source/formatting | PASS(source only) | Explicit paid consent, ready preview gate, selected cost/cap messaging, saved reservation view and native accounting validation |
| New component fixtures | NOT TESTED |4: separate paid/run consent and reservation; changed criteria clears consent; blocked paid preview/unknown estimate; unknown-start reload GET only |
| New helper fixtures | NOT TESTED |3: retained finding local recovery without renewed opt-in; unknown start cannot release pointer; corrupt native reservation refusal |
| New browser journey | NOT TESTED |1: isolated fictional paid preview, committed finding followed by lost response, reload GET, local-only completion, same pointer and single original PUT; screenshot is only a deferred fixture output |
| Current tests/build/check/lint/types | NOT TESTED |New executed tests0. Remaining agreed source precedes combined gates |
| Actual browser/Mac/provider/install | NOT TESTED |No browser launched, provider start, production request, screenshot or installation operation |
| Timing/resources | NOT TESTED |No new backend pool or recurring browser task; UI/Web Locks source only, no measured comparison |
| Full runtime/known-run recovery/platform acceptance | NOT TESTED/incomplete |Subsequent agreed source and final combined/live gates remain |

No private logs or screenshots are published. Fixture account/token/job data are fictional. Fixed refusal wording retains the original attempt for review instead of erasing it. No paid entitlement, final credits/billing or actual Naukri application acceptance is inferred.

Deferred reproduction: `pnpm -C frontend test -- tests/job-discovery.test.tsx tests/job-discovery-attempt.test.ts`; after final frontend build, isolated Brave/Edge-selected fixture runner `pnpm -C frontend e2e -- tests/e2e/paid-discovery-recovery.spec.ts`. Full frontend type/format/unit/gateway/public discovery and isolated browser regressions remain combined gates; no repeat test/build cycle has run during source work.

Last validated checkpoint9c4ace570535a5856184775f8045ee89eafdd05f remains193 standard Rust+262 dedicated PG=455 distinct passes, which do not validate this head. Estimate held58%/42%. Last observed queue STOPPED162; lifetime4/hour1, three uncertain jobs quarantined, one fourth admission remaining, strict worker receipts0. Identity/PDF/filter/focus constraints remain. No hosted Actions, merge, cleanup, sending/application, paid provider or installed-service operation. GitHub CLI publication fallback is used while the connector is unavailable.
