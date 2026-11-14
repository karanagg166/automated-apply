# Native Rust and Brave operational checkpoint, 2026-11-15

Implementation: [`1ec7995ff6b92d81eb1590fcdf97ae46690aae23`](https://github.com/karanagg166/automated-apply/commit/1ec7995ff6b92d81eb1590fcdf97ae46690aae23),
including direct native launch [`2e54eec15493f07aba8f112703ca8a4bdb4c3492`](https://github.com/karanagg166/automated-apply/commit/2e54eec15493f07aba8f112703ca8a4bdb4c3492).
Branch `feat/rust-agent-runtime`, [PR #50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling` ([PR #49](https://github.com/karanagg166/automated-apply/pull/49)).
**Whole-project acceptance remains IN PROGRESS. This is not completion.**

## Current behavior

Browser manifests can launch the Rust native executable directly. It reads one fixed
adjacent owner-only configuration file and validates the supplied extension origin;
the explicit configuration/origin command remains compatible. This follows the browser's
[native origin argument contract](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging).
No shell wrapper or ambient credential lookup is needed. The browser installer still
requires normal operating-system access to the binary and private file.

The actual Brave native registration now points to Rust implementation `2e54eec`, binary
SHA256 `ed335c20d948075372d611cd73d9c6a296047920822abf7d3b974905162a73a1`.
Its executable and private configuration live inside the canonical repository's ignored
runtime directory. The distinct `com.automated_apply.brave` host preserves the existing
Chrome agent registration and stable extension ID. Prior registration/installation
inventory remains private for rollback.

Actual Brave subsequently passed native health, connection of the existing owned profile,
all27 served extension file hashes and selected-tab preservation with commands disabled.
Naukri site access is absent. Owner login and independent account/identity/receipt checks
have not been completed. The interactive launcher is prepared but was not run by the agent;
the owner has been asked to grant the browser permission and verify/sign in normally.

The existing Python API/execution services were restored from immutable implementation
[`8e985c91c58588c9a9160a3e206e760426ac1bfc`](https://github.com/karanagg166/automated-apply/commit/8e985c91c58588c9a9160a3e206e760426ac1bfc).
This is transitional operation, not Rust backend cutover. Saved queue STOP162,
supervised4/hourly1 and any verified skill remain. Three uncertain applications stay
quarantined; the saved owner-assisted receipt is not a strict worker receipt. No allowance
was reset and recurring AUTOMATIC remains unaccepted.

## Acceptance matrix

| Check | Result | Evidence and limits |
| --- | --- | --- |
| Fresh standard Rust workspace | PASS | 127 tests, zero failures;121 PG cases intentionally ignored by this command |
| Native direct-launch checks | PASS | Two new binary unit tests plus one actual subprocess integration test within the127; adjacent private file, ignored ambient credentials, wrong origin and loose file mode covered |
| Dedicated PostgreSQL baseline | PASS | Previous121-test native PG baseline remains applicable to unchanged Rust DB code; not rerun for this native/JS-only delta |
| Qualified Rust total | PASS | 248 distinct current tests:127 fresh standard +121 retained PG baseline; not a claim that all248 were rerun together |
| New setup-policy suite | PASS | Two Node tests; stopped revision, pinned path, browser disable decisions, original portal/foreign tabs and missing URL rejection |
| Existing extension/browser/MCP suites | PASS | Retained evidence:399 extension unit tests,64 MCP tests and25 Python catalog/candidate tests; the two25-test log copies are not counted twice |
| Additive Rust schema package | PASS | Prior native PG verification has ten catalog/privilege/STOP/atomicity checks; owner database was not accessed by that verifier |
| Rust release build | PASS | Direct native target,25.26s,8,226,848-byte binary; actual Mac build |
| Actual Brave native/profile bootstrap | PASS | Native health and profile connection;27 SHA256 file checks; commands disabled; stable ID and existing profile storage retained |
| Current temporary helper cleanup | PASS | Subsequent cold start showed main disable reasons empty and zero helper references; two unreferenced helper files retired after confirming the owned browser stopped |
| API restore/readiness | PASS | Private cutover record shows installed8e985c9, ready HTTP200, old PID exited, new PID verified and rollback preserved; actual health200 rechecked |
| Saved execution state | PASS | Authenticated queue read observed STOP162, SUPERVISED,cap4/hourly1,any skill; three unknown applications retained |
| Formatting/Clippy/syntax/diff | PASS | Workspace all-targets warnings denied for native delta; Cargo fmt, Node syntax, Prettier and diff checks pass |
| Naukri browser permission/login | BLOCKED | Owner browser click/login requested; site access false. No cookies imported |
| Full unattended maintenance/focus acceptance | FAIL | Reload attempts timed out and temporarily left the extension disabled; subsequent focus endpoint checks passed, but the complete all-state path is not accepted |
| Actual OS observations | PASS / FAIL | Later observations preserved foreground/window order. First comparison failed as foreground changed from loginwindow to Chrome while window order stayed equal; cause unproven. No owner window was restored/activated to make a check pass |
| Original selected setup tabs | PASS | Actual inactive owned extension document; selected tabs compared before/after normal bootstrap. Other Chrome profiles were not controlled |
| Real portal/application acceptance | NOT TESTED | No portal navigation or Apply dispatched; observed portal requests0 after debug attachment. Pre-attachment network is not a complete capture |
| Full Rust services/API/providers/Gmail/platforms | NOT TESTED | Migration still incomplete; Python services remain transitional dependencies |
| Whole-project CPU/RSS/GPU/latency comparison | NOT TESTED | Binary/build figures are component observations, not complete-system performance claims |
| Hosted Actions / merge | NOT TESTED | No dispatch or merge |

## Failures and recovery

The former shell wrapper failed with `Operation not permitted` when started by Brave.
Direct Rust launch passed. A later runtime call still selected Chrome's host name despite
verified served Brave bytes; the runtime guard rejected `brave_runtime_native_host_mismatch`.
This observation establishes stale runtime behavior, not a proven V8 cache root cause.

Reload attempts could not observe a replacement service worker. One cold restart interrupted
the reload and the profile retained reason4, Chromium's
[`DISABLE_RELOAD`](https://chromium.googlesource.com/chromium/src/+/refs/heads/main/extensions/browser/disable_reason.h).
The first complete tab inventory also failed because page handles omitted protocol-visible
targets; full read-only target inventory resolved that discrepancy. A disposable reload
fixture timed out and is not counted as passing acceptance.

An attempted developer-protocol repair returned a loaded ID but did not immediately prove
readiness; its temporary-helper uninstall reported `could not find extension`. The helper
reference and original files were preserved while that outcome was uncertain. A subsequent
normal cold-start bootstrap passed; saved disable reasons were empty and the helper was
independently absent before its two unreferenced files were retired. No protected browser
preference file was edited, no user/policy disable decision cleared, and no consumed reload
was replayed. The unsuccessful automatic reload/repair implementation has been removed.
Current setup refuses disabled extensions, original portal tabs and a running queue.

Owner setup instructions are in [the browser guide](../agent/mcp-and-browsers.md).
The remaining browser permission and account steps are pending; full application acceptance
cannot be inferred from successful bootstrap. Raw logs, profiles, credentials, hashes of
private personal records and private PDFs remain excluded from this report.

## Reproduction and continuation

```sh
CARGO_INCREMENTAL=0 cargo test --locked --workspace
CARGO_INCREMENTAL=0 cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all --check
pnpm -C frontend exec node --test ../tests/brave_setup_policy.test.mjs
pnpm -C frontend exec node --check ../scripts/setup_brave.mjs
pnpm -C frontend exec prettier --check ../scripts/setup_brave.mjs ../scripts/brave_setup_policy.mjs ../scripts/open_brave_owner_setup.mjs ../tests/brave_setup_policy.test.mjs
uv run --no-project python scripts/project_continuity.py snapshot
uv run --no-project python scripts/project_continuity.py verify
git diff --check
```

Do not rerun bootstrap against an owner-used portal/form context. The owner interactive
launcher changes foreground by the owner's deliberate action; the agent does not run it.
Continue independent Rust REST/provider/browser/application/Gmail/Telegram service ports
while owner setup is pending. Then verify fresh account binding, policy/history/PDF/focus,
STOP-mode installation and rollback, resource use and a genuine worker receipt. Later
platforms require individual live acceptance. The original full migration goal remains active.
