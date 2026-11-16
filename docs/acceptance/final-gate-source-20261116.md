# Final local gate infrastructure — source only, NOT TESTED

Branch `feat/rust-agent-runtime`, implementation
[`3473cf039e336cde8ea1a9b27b4c0aef1d70a3ae`](https://github.com/karanagg166/automated-apply/commit/3473cf039e336cde8ea1a9b27b4c0aef1d70a3ae),
[PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`.
The preceding source correction
[`30033ac3d29f255d8111dba3489698f748216cd4`](https://github.com/karanagg166/automated-apply/commit/30033ac3d29f255d8111dba3489698f748216cd4)
retains the legacy denial for paused question-only contexts and adds the16th native form
database regression declaration. Neither implementation has been compiled/tested here.

## Changes written

- The sequential final runner now includes one combined Python unit/PostgreSQL stage,
  four UI/browser workspace configurations,26 explicit extension fixture scripts, the
  complete native-host stack and the explicitly named backend browser acceptance files.
  Ordinary test discovery did not collect those latter files.
- New native PostgreSQL17 fixtures choose their own temporary directory and loopback
  port, accept no external DSN, isolate environment/password/service files and stop their
  own cluster before removing disposable bytes. Uncertain shutdown preserves that
  directory and fails. SIGTERM closes the cluster; Node parent pipe loss also releases it.
  These fixtures use max40 connections; this is a fictional test-cluster setting and does
  not change the production Rust connection budget.
- The backend test plugin is explicitly loaded before conftest and disables implicit
  repository environment-file loading. Fixture subprocesses receive a small allowlist
  of environment variables, canonical Python and Brave selection.
- Browser fixtures and frontend Playwright configurations select installed Brave by
  default or explicitly selected Edge, with no Chrome fallback. The isolated backend
  browser driver uses a production browser-selection module, not an import from tests.
  Existing dedicated-profile guards remain in place.
- Ordinary extension builds now target Brave. Explicit historical Chrome builds remain
  supported for compatibility; no installed bundle is replaced. Native fixtures register
  the built bundle's matching Brave/Edge native name only under their temporary profiles.
- Three older stack/database fixtures use the new owned native cluster instead of
  Docker. The old hardcoded extension1.2.2 assertion now checks the source manifest.
- Combined acceptance and per-stage heavy locks are separate, preventing nested-lock
  deadlock in the existing self-locking stack fixture. Timeout cleanup snapshots only
  stage descendants, checks retained process identity before signaling and allows20s for
  owned shutdown. This remains untested source, not a proven cleanup guarantee.

## Exact evidence matrix

| Gate | Status | Evidence / limitation |
| --- | --- | --- |
| Source committed | PASS | Exact implementation SHA above; no installation |
| New harness regression execution | NOT TESTED | 9 new declarations:4 disposable PostgreSQL lifecycle/environment,3 coordination/process-selection,2 browser/default-build;0 executed,0 passed,0 failed |
| New native form correction | NOT TESTED | Current native form database declarations16,all unrun |
| Current compilation/typecheck/Clippy/build | NOT TESTED | Deferred under the owner's source-first/final-test instruction |
|26 extension browser fixture files | NOT TESTED | Explicit execution list written; no browser launched |
| Actual Mac Brave/focus/awake/locked | NOT TESTED | Executable inventory only; no tab/window/owner input or browser launch |
| Actual Edge | NOT TESTED | Expected app was absent from the observed `/Applications` inventory; no download/install or alternate-path probe |
| Safari | NOT TESTED | Retained deferred browser scope; no claimed adapter |
| PostgreSQL fixture startup/shutdown | NOT TESTED | No new cluster started; stop/status handling checked against [official PostgreSQL17 documentation](https://www.postgresql.org/docs/17/app-pg-ctl.html) |
| Runtime resource/timing comparison | NOT TESTED | No new measurement; source changes do not establish speed/RSS improvement |
| Full project/live application acceptance | NOT TESTED | Remaining source ports, complete final gate, STOP cutover and live per-platform receipts remain |

Only formatters wrote source formatting during this milestone. No lint/check/test/build,
hosted workflow, production migration, service restart, owner-browser operation, provider
call, application action, admission/refund, recurring automation or credential change.
Private historical evidence stays private. No new runtime logs/failure counts exist.

## Reproduction and remaining work

After completing all remaining source, invoke `uv run --no-project python
scripts/run_acceptance.py --run` on the Mac. It writes private stage logs and atomic
PASS/FAIL/NOT TESTED results, stops after the first failure and never deploys or operates
live accounts. The source-added stages and cleanup behavior need their own final validation;
do not treat this expanded list as a passing gate.

Continue native command-contract/hash compatibility, execution/kernel, legacy question
delivery/replies, account/history/service/provider and per-platform ports before the test
gate. Preserve the last validated9c4ace5 checkpoint separately from all new source.
Current rough estimate stays58% complete/42% remaining. No accepted speed or completion
increase is inferred from untested implementation.
