# Approved90 installation: incomplete extension cutover and stopped acceptance

**Overall: FAIL / BLOCKED, not reliability acceptance.** Six service/native references were installed at the owner-approved SHA. The extension was initially verified there, then reverted to preserved historical content. One genuine Open completed but disappeared from the bounded status history. **Zero of the required three Open → Prepare cycles completed.** No Prepare, fill, Apply, submission or replay was admitted.

- Repository/branch/base: `karanagg166/automated-apply`, `fix/live-prepare-discovery-20261030`, `main`; [PR #48](https://github.com/karanagg166/automated-apply/pull/48).
- Approved and installed service source: [`90f2f2ade50a1c31b26ca85cc7fdf5e93bb67c20`](https://github.com/karanagg166/automated-apply/commit/90f2f2ade50a1c31b26ca85cc7fdf5e93bb67c20).
- Preserved rollback: [`79ce5f6b514279e6d9022d85b659ad77fb31bd89`](https://github.com/karanagg166/automated-apply/commit/79ce5f6b514279e6d9022d85b659ad77fb31bd89).
- New development correction, **not installed**: [`98965f7607a4714371599fef0143d5e1f8eed25b`](https://github.com/karanagg166/automated-apply/commit/98965f7607a4714371599fef0143d5e1f8eed25b).
- [Sanitized measurements, inventories, startup failures and reconciliation](approved90-installation-metrics-20261030.json); [actual Naukri flow and action boundary](naukri-application-route-20261030.md).

## Installation and actual Mac evidence

The approved release's tracked source is clean at the exact SHA. Its previously completed independent Python/pnpm builds were checked, pip check passed again, and extension identity/permission sets match the preserved original. No release source was edited, environment changed, migration applied or dependency directory shared with another release.

Before cutover, four running services were identified. All nine static installation/private-configuration hashes matched the previous backups; a separate nine-file private backup was verified. The selected binding was unchanged, task PAUSED without authorization, and no command was active. A real TLS PostgreSQL inventory mapped **API business + API readiness + execution + Telegram = four runtime connections**, with the temporary audit using the fifth under role limit five. No unidentified backend was present; audits closed before the workload.

The single pre-install HTTP-only window covered pool recycling: **24/24 HTTP200**, eight samples per endpoint over approximately315 seconds, original12-second deadline. Two subsequent snapshots caught ordinary between-query transaction states: execution about0.21 seconds old, then API about0.47 and Telegram about0.26. The initial diagnostic guard rejected *any* idle-in-transaction observation; those rejections are retained as a verifier limitation, not evidence of persistent leaked transactions. Six targeted samples established four runtime sessions throughout, no blocked sessions and maximum observed transaction age **1.860105 seconds**. The earlier execution transaction had cleared. There was no new full acceptance loop, backend termination, role-limit increase or timeout change.

Known services stopped gracefully with exits verified. Six references were atomically replaced; API then frontend/execution/Telegram started. API readiness returned200 at16:19:29 UTC and frontend at16:19:34. The planned startup probe recorded **seven ConnectErrors followed by one200**, separately from workload measurements. These errors are preserved, not discarded. Installed native-host health passed without a browser application action.

Chrome's native folder chooser was difficult to reach while another profile had a full-screen window. UI troubleshooting and owner desktop assistance occurred; diagnostic Profile8 windows/tabs were created. At16:24:39, Profile8's persisted extension path was verified at exact90 and all18 candidate files matched. Later verification found the same extension ID at its preserved historical directory, with17 files exactly matching the original/rollback extension content. Task history recorded browser-restart fencing during that interval. **The actor or mechanism that changed the extension path is unproven.** Do not attribute it to the owner, a leak or a specific Chrome mechanism without evidence.

All six installed service/native references still match the reviewed90 plans; all three unchanged private/manifest files match their backups. The90 release remains clean. The overall installation is nevertheless **incomplete** because its extension is no longer at90. A same-approved-SHA restoration attempt did not produce a verified final cutover. The owner subsequently required background-only work without screen/focus interference; no further GUI, typing, chooser or Chrome-launch actions were performed after that instruction. More filesystem access does not resolve that desktop constraint. All historical releases, native identity, credentials, data and rollback backups remain protected.

## Bounded workload and exact receipt reconciliation

The HTTP-only observer ran16:25:57–16:28:01 UTC, retaining the original12-second deadline and original failures without retry:

| Endpoint | Exact outcomes | Mean / maximum seconds |
| --- | --- | --- |
| health | 24/24 HTTP200 | 0.0145 /0.0379 |
| readiness | 24/24 HTTP200 | 1.0548 /1.3854 |
| profile status | 24/24 HTTP200 | 3.2886 /8.3227 |

That is **72/72 HTTP200, zero12-second timeouts and zero readiness503s**, with no connection-limit/53300 markers in the sampled service logs. It is an Open-only window with an extension-source change; it does **not** prove corrected full-Prepare latency. The prior failed Prepare windows and earlier database failures remain in the linked historical reports.

Only one original Open was admitted. The live status response repeatedly omitted its ID. A single bounded read-only operator reconciliation found its durable state **completed** among37 command records, while the API returned30 older/arbitrarily ordered records. No alternative command ID or application action was retried. After authoritative reconciliation the acceptance helper was interrupted, its finalization read the task, and the observer stopped. The helper's FAIL records the interruption and missing original receipt; it is not a completed cycle.

Persisted task events establish Open's binding at16:27:07, followed by browser-restart invalidation at16:27:19–23 and explicit recovery at16:27:36. The final task is PAUSED with no tab binding or fill authorization. This is a successful safety fence, not functional preparation success. Its restart source is not independently established. Prepare was never admitted.

The final one-connection audit established:

- **36/36 historical terminal commands unchanged**; exactly one new command, Open/completed, submitted=false.
- **Zero active commands, new plans, new packets for the selected job, submissions or unknown-outcome replays.**
- Selected profile binding unchanged, task PAUSED without authorization.
- Five sessions including the audit; maximum observed runtime transaction age0.031615 seconds. Audit closed cleanly.

No live Stop fault was injected after acceptance stopped. Pause/restart fences were exercised by the actual task state; the focused tests below include the existing Pause/global Stop/expiry checks. A stopped acceptance is not authority to repeat disruptive fault tests.

## Measured correction and local validation

`_listing` obtains a fresh UNION ALL snapshot without ORDER BY, then slices command/receipt lists to their last30 records. SQL result order is unspecified; physical updates/scan changes can place a newly completed record outside that slice. This is a receipt-visibility defect even when HTTP latency passes.

Development98965f7 sorts commands and receipts by **persisted created_at and stable key before bounding the response**. It adds no SQL statement, engine, cache, timeout or replay, and retains credential redaction and maintenance fences. Pure selection over the saved genuine37-record snapshot places the original completed command inside the newest30. That is genuine-data reproduction, **not a deployed correction**.

Four regression cases vary database scan direction and equal/different timestamps with35 deliberately shuffled commands and35 receipts. **All four fail before the correction (0.42s). After correction, 47 focused tests pass in8.82s**, including those four cases, Chrome command/task safety, existing reliability and timing tests. Tests use isolated fictional SQLite/unit fixtures; no live candidate data or employer action. Ruff E9/F/I and diff checks pass. No PostgreSQL integration suite, frontend build or extension suite was rerun for this Python-only sorting change; the exact90 build results remain prior build evidence.

```sh
.venv/bin/python -m pytest \
  backend/tests/test_chrome_status_history.py \
  backend/tests/test_chrome_profiles.py \
  backend/tests/test_reliability.py \
  backend/tests/test_request_timing.py -q
.venv/bin/ruff check --isolated --select E9,F,I \
  backend/app/browser/chrome_profiles.py backend/tests/test_chrome_status_history.py
git diff --check
```

Do not reproduce the genuine history defect by creating more employer/browser commands. The fixture above reproduces it safely. Review98965f7 against90; it needs separate exact-SHA installation approval before any runtime replacement.

Representative resource samples across this24-sample window:

| Service | Mean CPU % | Peak RSS MiB |
| --- | ---: | ---: |
| API | 2.333 | 86.016 |
| execution | 0.458 | 38.328 |
| Telegram | 0.092 | 47.141 |
| frontend | 0.017 | 9.094 |

The previous diagnostic window had88 samples and full inspections, two status timeouts, and status mean3.0293/max12.0087 seconds. Current mean3.2886 does not establish improvement. CPU/RSS and latency windows have different work and uptime; no optimization or full-Prepare throughput claim is made. The earlier10→1 project-fingerprint read comparison is prior routine evidence, not a new live inspection benchmark.

## Tabs, form evidence and remaining boundaries

All **seven original selected-Profile8 tabs** retain their IDs/window IDs/URL hashes. During the bounded Open window **12/12 non-target baseline tabs** were preserved, zero missing/changed. One own diagnostic settings tab disappeared and a new job-details tab appeared; lifecycle attribution is unavailable. The attempted session audit could not be enabled from AppleScript's isolated script world, so no event-attribution claim is made.

Two tabs from another initial window disappeared **before** the workload baseline, during desktop troubleshooting/owner intervention. Their disappearance is retained as **unattributed**, not relabeled application-caused or fixed. Broad all-profile cutover preservation is not accepted from that record. No explicit unrelated-tab close operation was issued.

Read-only DOM evidence on the genuine selected job found zero forms/iframes and only three optional, empty search inputs. No live application questionnaire, approved resume attachment, required answer or prepared application is established. [The separate route report](naukri-application-route-20261030.md) records the real hiring-company/posting-recruiter distinction and the exact unapproved Apply boundary.

| Requirement | Verdict | Evidence / next action |
| --- | --- | --- |
| Exact90 clean source, six service/native references | PASS | Final hashes and preserved nine-file rollback backup |
| Entire exact90 installation including extension | **BLOCKED / INCOMPLETE** | Initially90, final historical original content; background-only constraint |
| Four runtime connections / five-role limit | PASS, bounded observations | Process tuple mapping; no unknown backend; audits closed |
| Original12-second HTTP monitoring | PASS, scoped | 24 preflight +72 Open-window HTTP200; planned startup7 ConnectErrors retained |
| Three consecutive genuine Open→Prepare cycles | **FAIL /0 of3** | Only original Open completed; zero Prepare admissions |
| Reliable recent-command/receipt visibility | **FAIL installed; FIXTURE PASS corrected** | Newest command omitted from37-record unordered history;98965f7 uninstalled |
| Original outcome/history and no replay | PASS | One original completion,36 old terminals unchanged, zero new unknown/replay |
| Pause / restart fencing | PASS for exercised safety | Final PAUSED, no binding/authorization; restart source unproven |
| New live Stop fault test | NOT TESTED | Existing focused fence tests pass; no unnecessary fault loop |
| Selected/bounded non-target tabs | PASS for stated scope | 7/7 original Profile8 and12/12 workload non-targets preserved |
| Broader all-profile cutover tab preservation | **NOT ACCEPTED** | Two pre-workload tabs missing, cause unproven |
| Genuine application form, fill or submission | BLOCKED / NOT TESTED | No application form; no potentially submitting control activated |
| Discovery/Gmail policy changes, locked unattended operation | NOT TESTED / UNCHANGED | Dependent functional gates unmet; no source broadening |
| Hosted Actions, merge, cleanup | NOT PERFORMED | Manual-only triggers preserved; no release overwritten/deleted |

Next action is review of98965f7 and resolution of a non-disruptive, verifiable extension cutover within the owner's desktop constraint. Do not repeat broad infrastructure acceptance or claim the original latency issue resolved from this Open-only run. Any later native acceptance must first reconcile the existing original command and fresh profile/task versions, preserve the same12-second deadline, and stop on a critical failure. No new runtime SHA, Apply/follow action, Gmail access expansion or submission has been authorized by this report.
