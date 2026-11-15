# Brave window focus and login preparation — 2026-11-15

Implementation [`b9f4925e55ac57538b88aa3dce494e5fc53a8c90`](https://github.com/karanagg166/automated-apply/commit/b9f4925e55ac57538b88aa3dce494e5fc53a8c90),
branch `feat/rust-agent-runtime`, [draft PR50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling`. Overall unattended browser setup remains **FAIL**.

The owner confirmed granting Brave macOS file access. The existing owned browser
passed native extension health, API health/readiness200 and an authenticated queue
STOPPED162 read. Selected tabs stayed unchanged in that read-only check. Permission
and native connectivity do not establish Naukri account identity or a worker receipt.

## Actual failure

An initial attempt to prepare an inactive login tab refused before mutation with
`single_owned_window_required`. Independent browser inventory showed zero windows
and zero tabs, although the owned browser process/extension remained alive.

A single STOP-checked native window experiment requested
`{url:"about:blank",focused:false,state:"minimized",type:"normal"}`. The
[documented API](https://developer.chrome.com/docs/extensions/reference/api/windows#method-create)
supports inactive creation. Actual fresh readback instead reported **focused=true,
state=normal**. The passive before/after desktop check reported foreground and window
ordering changed. The code stopped at the assertion before explicit portal navigation.
No automatic window restoration, activation, closing or cleanup was attempted to
force a passing check. The request path failed acceptance; component-level causation
is not established by these samples.

Subsequent inventory observed22 tabs in the new window, including one inactive
Naukri login tab and retained extension/blank pages. This is consistent with restoration
of the profile's earlier session; the operator requested only a blank page. Do not
claim zero portal network traffic during restoration: requests were not instrumented.
All restored tabs were preserved. No Apply, login/verification form, upload or email
verification request was explicitly submitted by this experiment.

The Naukri tab reported `status=unloaded`, inactive, not discarded. The Naukri origin
grant still reported true, but a bounded isolated-world status read was refused with
the browser's page-access error. No DOM or account identity was obtained. A later
fixed-login load attempt refused with `unique_unloaded_login_required` before its
navigation intent was admitted; no result/intent was created and no navigation was
performed by that attempt. Missing evidence files were independently noticed; no
successful load, account check or sign-in is inferred from them.

## Guarded replacement

`scripts/prepare_brave_login.mjs` connects only to the already-running dedicated
Brave profile using `noDefaults`. It verifies pinned extension hashes and STOP,
requires a unique existing normal/non-incognito window with a verifiable neutral
selected tab, and plans only an **inactive** fixed Naukri login tab. Existing Naukri
tabs, pending navigation, windowless/ambiguous sessions, inaccessible neutral URLs
and previous intents cause refusal. It never creates, launches, activates or closes
a browser/window. It records intent before tab creation and retains uncertain intents.
No bearer/configuration value is printed. A generic error preserves the failure;
known policy errors have closed sanitized codes.

The actual helper refused before tab admission when the session could not satisfy
its inventory requirements. Its passive comparison passed because no creation
occurred. That is a safe refusal, **not** acceptance of its successful tab-creation
path. The owner's existing Naukri tab remains available for an ordinary manual
sign-in; no further terminal or extension-configuration task is requested here.

| Check | Result | Exact scope |
| --- | --- | --- |
| Existing Brave native bridge/API health | PASS | Earlier fresh checks; queue STOPPED162 |
| Windowless tab preflight | PASS | Refused before creating a tab |
| Native inactive/minimized window creation | FAIL | Actual focused=true/state=normal; foreground/window order changed |
| Existing-tab/pending-navigation preservation policy | PASS | **4 Node tests**,0 failures,154.960ms; two new tests plus two retained tests |
| Actual guarded replacement refusal | PASS | No admitted intent or tab; passive foreground/window order unchanged |
| Successful new inactive login-tab creation | NOT TESTED | Replacement refused; do not promote that refusal to success |
| Portal DOM/account sign-in validation | BLOCKED | Unloaded restored login page; isolated-world access refused |
| Explicit fixed-login load | BLOCKED | Preflight refused before navigation; no replay |
| Automatic setup/unattended maintenance | FAIL | Native window-creation path suspended in AGENTS.md |
| New application/strict worker receipt | NOT TESTED | No Apply; recurring AUTOMATIC remains disabled |

```sh
node --test tests/brave_setup_policy.test.mjs
pnpm -C frontend exec prettier --check ../scripts/brave_setup_policy.mjs ../scripts/prepare_brave_login.mjs ../tests/brave_setup_policy.test.mjs
git diff --check
# STOP-only preparation; refuses if the owned profile/window/intent is unsuitable.
pnpm -C frontend exec node ../scripts/prepare_brave_login.mjs
```

No Rust/backend/frontend/extension implementation changed in this guard correction;
the preceding337 Rust,3,364 Python passes/64 skips,305 frontend and399 extension tests
are retained earlier evidence, not rerun or added to the four guard tests. See
[the public feed checkpoint](public-feed-live-and-links-20261115.md) and
[full runtime boundary report](runtime-review-and-boundaries-20261115.md).
No whole-system timing/resource comparison was performed; the guard runtime is not
a browser performance benchmark. No new production install, database schema change,
quota/profile/resume/history mutation, hosted Actions, merge or cleanup occurred.

Next the owner completes ordinary Naukri sign-in in the existing dedicated Brave tab
when ready. Do not repeat the login/verification intent or request the same physical
step again. Preserve STOP, commands disabled, supervised4/hourly1, all three uncertain
admissions and the first strict worker-receipt prerequisite. Continue independent
Rust ingestion/browser/execution/account/service work; complete focus/install/rollback/
resource and real per-platform acceptance before calling the project operational.
