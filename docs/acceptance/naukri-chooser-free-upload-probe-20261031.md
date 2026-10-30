# Naukri resume blocker: chooser-free browser experiment

**PASS for isolated browser primitives; NOT TESTED on genuine Naukri or the
installed worker. The Naukri unattended phase remains OPEN.** No email or provider
outreach is authorized, planned or requested from the owner. The earlier draft
is historical research and is not a pending owner task.

Branch `fix/live-prepare-discovery-20261030`, base `main`,
[PR #48](https://github.com/karanagg166/automated-apply/pull/48).
Exact experiment implementation:
[`d7223c9b45f89b910cfbcfe1d92a9190d1889649`](https://github.com/karanagg166/automated-apply/commit/d7223c9b45f89b910cfbcfe1d92a9190d1889649).
Parent reporting milestone:
[`fe00184c747dc6c652395e62e97fd58dfc73214b`](https://github.com/karanagg166/automated-apply/commit/fe00184c747dc6c652395e62e97fd58dfc73214b).
[Sanitized measured results and exact source-file hashes](naukri-chooser-free-upload-probe-metrics-20261031.json).

## Technical result

The actual QTrino application skipped Upload Resume initialization on its first
file transfer, then succeeded after ordinary initialization and native selection.
It also demonstrated that file selection can immediately submit. The
[genuine receipt](qtrino-first-genuine-receipt-20261031.md) is preserved; requisition
`261026028027` was not opened, applied to or uploaded to again in this experiment.

This probe asks a narrower question: can an actual Chromium page run its ordinary
Upload Resume handler, then accept a FileList through the standard browser setter
without opening a native chooser? **Yes for the controlled fictional layouts
tested.** Three layouts retained the exact fictional bytes after initialization:
plain, nested controls and an input created by the normal Upload Resume handler.
The helper ran in an isolated world with `userGesture:false`; the site handler
remained in the page's normal world. It did not read or mutate its private state.
The page's ordinary input click did not produce a chooser in the final run.

This is a candidate mechanism, not Naukri compatibility evidence. The fictional
page models the observed sequencing dependency; it does not reproduce Naukri's
upload service, DOM selectors, validation, authentication or real retention. The
46-byte `%PDF-`-prefixed fixture is not a candidate resume and is not a full PDF
validation corpus. Its exact byte digest, declared type, revision and size bounds
are checked; actual canonical-PDF/provider acceptance still needs separate proof.

Two deliberate variants reject this candidate: asynchronous initialization and a
page requiring trusted file-change events. Both stop with NEEDS_INPUT and prohibit
automatic replay. Do not report those paths as supported or circumvent their event
requirements. No debugger permission or browser security setting was introduced.

## Files and isolation

- `extension/tests/support/chooser-free-upload.js`: test-only probe function. It
  accepts only the exact loopback fixture origin and marker, checks the trusted
  fixture binding/resume before action, and consumes the fixture attempt before
  initialization. It rechecks binding after asynchronous hashing and after UI
  activation, leaves existing attachments alone, detects explicit failure and
  ambiguity, and reports VERIFYING rather than a provider-recorded submission.
- `extension/tests/naukri-upload-probe.browser.mjs`: isolated Chromium runner,
  intercepted loopback pages, fictional file, 26 assertions/cases, chooser/network
  counters, fresh-browser-session check and optional exclusive-create JSON report.
- `docs/acceptance/naukri-unattended-plan-and-permission-20261031.md` and the prior
  worker report: mark the previous outreach request as superseded by the owner's
  instruction. No contact or replacement owner task is requested.
- This report and its metrics file contain sanitized experiment evidence only.

The probe helper is **not** imported by extension runtime modules and is **not**
listed in `extension/build.mjs`. It cannot operate on an actual Naukri origin.
The in-world consumed marker is not a durable server attempt lease: production
integration must use the existing persisted command/fence/idempotency system.
These laboratory checks must not be substituted for that integration.

## Exact checks and retained failures

**26/26 new browser cases passed, 0 failed/skipped, in 3.166 seconds**, using
isolated headless Chromium `156.0.8078.4` on the Mac. Final counters:
**0 chooser events, 0 external requests, 0 Naukri requests, 0 real applications.**
The complete named case list is in the metrics file. It covers:

| Dimension | Experiment result |
| --- | --- |
| Missing initialization | Reproduces explicit fictional upload failure |
| Initialize then assign exact bytes | Retained in three fictional layouts; VERIFYING only |
| Wrong PDF revision/type/header/hash or excessive size | Rejected before UI initialization |
| Wrong employer/tab/session binding | Rejected before UI initialization |
| Recent user activation | Refuses to initialize rather than opening a chooser |
| Existing attachment / ambiguous controls | Preserved / refused; no overwrite or speculative click |
| Explicit failure, asynchronous initialization, trusted-event requirement | NEEDS_INPUT, consumed attempt, no automatic retry |
| Navigation during initialization or selection / unconfirmed result | SUBMISSION_UNKNOWN, no repeated upload |
| Repeated invocation after retained attachment | No second initialization or file-change event |
| File change immediately triggers fictional submission | One simulated event; never promoted to a genuine/provider receipt |
| Document reload | Old execution context rejected; no file changed in the new document |
| Fresh isolated browser session | Prior session binding rejected before upload |
| Real Chrome Profile 8 restart / locked Mac | NOT TESTED by this experiment |

Four existing Naukri URL/form-recognition Node tests also passed, 0 failed/skipped,
in 807.304 ms. These are separate from the 26 browser cases. Earlier intermediate
20- and 24-case runs overlap the final run and are not additional acceptance counts.

The first prototype failed its final aggregate chooser assertion: **7 intercepted
chooser requests, expected 0**. Its fixture setup used Playwright evaluation and
introduced user activation. The corrected harness initializes through the page's
ordinary initial script; the helper also refuses recent activation. No native OS
dialog was operated and no installed profile was used in that failed prototype.
The failure is preserved here, not counted as a successful chooser-free run.

Changed-file Prettier and `git diff --check` passed. The extension build passed;
the development distribution matches **18/18** files from the prior production
extension source inventory, with zero extra files. This confirms the experiment
was not included in the distributed extension. No dependency or backend/API schema
change, migration, new pool or new backend/frontend regression run was needed.

## Actual installation and live evidence boundary

Fresh read-only inventory still found all four API/frontend/execution/Telegram
LaunchAgent program references at
`90f2f2ade50a1c31b26ca85cc7fdf5e93bb67c20`. Profile 8's saved extension path still
identifies historical `b06909293b1866e8191277d17fc284c398b4307b`; **15/18** current
extension files match, with the same background/coordinator differences and
missing tab audit. Runtime reload was not verified. No installation reference,
profile, permissions or service was changed or restarted.

Mac telemetry was **UNLOCKED**. The experiment creates and closes only its own
isolated headless Chromium processes; it never launches, attaches to, closes or
focuses the owner's Chrome. There was no new live Gmail scan, provider discovery
cycle, actual questionnaire answer, resume read/upload, application attempt,
unknown/failed real submission or Telegram send initiated by this milestone.
New real discovery count is **not measured in this milestone**; the last published
bounded source cycle returned zero. The known lifetime genuine count remains one
supervised QTrino receipt from prior evidence, with zero installed recurring-worker
submissions; no fresh provider reconciliation is claimed here.

No production timing/resource comparison was performed. The 3.166-second lab run
is not a submission-speed benchmark or uptime observation. Database role/pool
limits were not changed and no database connection was opened by this experiment.

## Reproduction

```sh
pnpm -C extension exec node tests/naukri-upload-probe.browser.mjs
pnpm -C extension exec node --test tests/naukri.test.mjs
pnpm -C extension build
backend/venv/bin/python backend/scripts/verify_extension_cutover.py \
  --sha a3472fcebe389ab4ec03739095cc4a841185a6c9 \
  --extension-dir extension/dist
pnpm -C frontend exec prettier --check \
  ../extension/tests/support/chooser-free-upload.js \
  ../extension/tests/naukri-upload-probe.browser.mjs
git diff --check
```

An optional `--report /NEW/OUTPUT.json` exclusively creates a sanitized report;
it refuses an existing file. It contains only case names, counters, fixture size,
browser version, timing and source-file hashes. Do not supply private profile or
resume paths. No real application is required to reproduce the experiment.

## Remaining acceptance and next technical work

| Completion gate | Status |
| --- | --- |
| A: Applicable platform route/permission | BLOCKED / unresolved; no outreach requested |
| B: Installed recurring discover/match/prepare/submit workflow | NOT COMPLETE; probe is not an installed executor |
| C: Resume/questions under real awake/locked conditions | NOT TESTED; chooser-free primitives are promising, genuine site integration pending |
| D: Multiple distinct worker-recorded applications | NOT MET; no new real applications |
| E: Stop/Pause, recovery, history, outbox | Existing implementation preserved; fixture binding/replay checks do not establish live acceptance |
| F: Extended unattended window | NOT TESTED |

Next technical work is to bind a Naukri adapter to verified actual UI variants and
the existing durable admission protocol, then establish the required release/live
test prerequisites. The normal initialization step and potentially submitting
file selection must remain within one admitted action. Unknown outcomes require
permitted read-only reconciliation, never an automatic repeat. Direct FileList
assignment cannot be enabled merely because these fictional pages accept it.

No email, paid service, other platform, merge, hosted Action, production release
or cleanup was performed. There is no new installed release to roll back. If the
experiment is later removed through a reviewed Git revert, preserve the genuine
QTrino receipt and all installed/historical releases. Do not delete worktrees or
replace runtime files to roll back laboratory-only code.
