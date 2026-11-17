# Durable startup dashboard and child handoff — source checkpoint2026-11-17

Implementation [3833f23eb112a8ddc081bb442bf3512eea049529](https://github.com/karanagg166/automated-apply/commit/3833f23eb112a8ddc081bb442bf3512eea049529), branch `feat/rust-agent-runtime`, [PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested/uninstalled source; no new actual browser screenshot, provider/recovery request, production SQL or Mac acceptance.

Startup discovery controls are now isolated from the Discover tab shell and replace its former in-memory POST key with an opaque UUID/source pointer saved before original PUT. Startup Web Locks serialize original work. Mount/reload performs saved GET only. Response loss, unknown child state, corrupt response or changed criteria preserve original authority/history; retained findings use an empty local-only completion POST. Only reviewed terminal results remove the local pointer. Missing admission requires fresh same-source consent on the same UUID. Company unknown facts remain unverified.

Only configured/authorized native implemented job-led sources are selectable. Paid startup execution additionally requires saved ready review/build/budget, separate paid opt-in and an actual-query ready preview followed by run consent. Criteria edits clear consent. Preview and result messages distinguish estimates/full-cap held reservations from final billing. Startup completion never issues provider read recovery. An explicit original child handoff validates saved child data and then stores only its opaque job UUID/source under the job-discovery lock, refusing to overwrite an unrelated saved job/read pointer. This switches the existing tab to original job discovery where separately bounded read consent/recovery is available.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source/formatting | PASS(source only) | Isolated startup controls/helper, durable original pointer, GET-only reload, local recovery/terminal review, saved source readiness/paid consent and validated child handoff |
| New helper declarations | NOT TESTED |10: pre-PUT pointer privacy; consent/storage refusal; response loss/saved GET; retained local completion; unknown state;404 same UUID/source; terminal pointer release; corrupt identities/counts/paid accounting; concurrency/single PUT; original child handoff/unrelated pointer refusal |
| New component declarations | NOT TESTED |4: native source/preview/run consent; unknown reload/locked criteria; separate paid opt-in/blocked preview; retained local completion/terminal review |
| New browser journey | NOT TESTED |1: fictional response loss, reload saved GET and local company completion with same UUID/single PUT; screenshot is a deferred fixture output only |
| Current tests/build/check/lint/types | NOT TESTED |New executed tests0. Remaining agreed source precedes combined gates |
| Actual browser/provider/Mac/install | NOT TESTED |No browser launched/screenshot captured, provider/recovery request, production SQL or installation operation |
| Timing/resources | NOT TESTED |Existing shared host slots; keyed browser Web Locks only, no pool/recurring task added; no measured comparison |
| Full runtime/tool/platform/combined acceptance | NOT TESTED/incomplete |Remaining agreed source and final combined/live gates still open |

No private logs or screenshots are published. No provider start/abort, Apply allowance reset, eligibility inference or final-billing claim follows from the dashboard. Old fixture-only startup UI flows must adopt the UUID contract during final combined fixture/contract work; old public phase2 discovery POST expectations are also known remaining fixture alignment work from the earlier UUID migration.

Deferred reproduction: `pnpm -C frontend test -- tests/startup-discovery-attempt.test.ts tests/startup-discovery.test.tsx`; after final build, isolated Brave/Edge-selected runner `pnpm -C frontend e2e -- tests/e2e/startup-discovery-recovery.spec.ts`. Full frontend type/format/unit, discovery/job/read/gateway and browser regressions remain combined gates. Fixture success will not establish platform/provider acceptance.

Last validated checkpoint remains9c4ace570535a5856184775f8045ee89eafdd05f:193 standard Rust+262 dedicated PG=455 distinct passes; those results do not validate this head. Estimate held58%/42%. Last observed queue STOPPED162; lifetime4/hour1, three uncertain jobs quarantined, one fourth admission remaining, strict worker receipts0. Identity/PDF/filter/focus constraints remain. No hosted Actions, merge, cleanup, sending/application, paid provider or installed-service operation.
