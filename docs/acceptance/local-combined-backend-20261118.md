# Local combined validation through backend

Branch `feat/rust-agent-runtime` started clean at `cc18359268e9a28bc8d6b6a01f363fdae7833ae3`. The command was `uv run --no-project python scripts/run_acceptance.py --run`. The runner stopped at stage 13 of 36. The run record captured its starting commit and the failed stage. Its final source stamp was missing.

| Gate | Status | Evidence |
| --- | --- | --- |
| Contracts and Rust formatting | PASS | Ten stages passed before the Rust suite. |
| Rust workspace | PASS | 427 passed, zero failed and 1,079 ignored. Dedicated Rust PostgreSQL fixtures are a later stage. Workspace runtime was 173.899 seconds. |
| Strict Clippy | PASS | All workspace targets passed with warnings denied. The combined stage took 1.017 seconds using the existing build cache. |
| Backend on this commit | FAIL | 3,410 passed, 21 failed and one skipped in 844.57 seconds. Twenty tracebacks showed `explicit_postgresql_database_required`. The command workflow was the other failure. |
| Remaining 23 fixture stages | NOT TESTED | Frontend, extension, Rust PostgreSQL, migration rehearsal, browser E2E and release stages await the next run. |
| Installation and live provider acceptance | NOT TESTED | Validation covered fixture data. The Rust cutover, Mac focus evidence and strict Naukri worker receipt remain open. |

An isolated reproduction identified the first mismatch. The fixture URL omitted a password required by the application’s PostgreSQL target guard. After enabling authenticated disposable PostgreSQL, the reproduction exposed missing explicit executor fields in legacy browser acceptance requests and outdated assumptions in the command queue fixture. The targeted browser and PostgreSQL checks use fictional records and a separate headless Brave profile.

The PostgreSQL browser tests then uncovered a one-connection deadlock. Signed browser endpoints now check the exact signature before the operation and claim the nonce on the same transaction after acquiring the browser lock. Operation status uses the active command's pinned revision for cancellation. Named cancellation stops the exact operation before database reconciliation. The fictional narrative provider now follows the same read-transaction release and evidence checks as the default service. The runner records the ending source stamp when the first failure stops the run.

| Repair verification | Status | Evidence |
| --- | --- | --- |
| Originally failing backend cases | PASS | All 21 passed in targeted repair batches on PostgreSQL 17 and isolated Brave. The final narrative batch ran nine cases, including four remaining PostgreSQL cases, owner-proof replay and four cancellation regressions. |
| Acceptance harness and database lifecycle | PASS | 18 tooling tests. The Node fixture also connected to the authenticated disposable cluster and shut it down. |
| Complete clean-commit validation and cutover | NOT TESTED | The focused runs cover the repaired paths. The combined run and installed operational evidence remain required. |

Private combined evidence is under `.local/acceptance/20261118T091356Z-03149b5fab764dfbbab4decf4caa34f6/`.
