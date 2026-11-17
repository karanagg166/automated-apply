# First combined validation of the current local branch

The first 36-stage run used clean commit `8d0bc721600a09713772e73c92dfe3d8fa794b17`. It passed 10 stages, failed the Rust test compilation, and left 25 stages untested. The branch contains the offline cutover planner. No installation or browser operation took place.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source contracts and Rust formatting | PASS | The policy, native field order, execution, Gmail, contact, outreach, startup, people and Apify contract checks passed, along with Rust formatting. |
| Rust compilation on the first candidate | FAIL | A Rust conversation parser passed a method chain where the JSON macro expected one value. The stage exited 101. |
| Rust compilation after targeted repair | PASS | Local source `615f98171d1014e11f799e721c67b620dbea1167` compiled and ran the Rust workspace tests. Repairs covered the parser, SQLx timestamp feature and string types, a missing import, a fallible hash comparison, and the included PostgreSQL test sources. SQL values continue to use bound parameters. |
| Rust workspace tests after targeted repair | FAIL | `cargo test --locked --offline --workspace --no-fail-fast` reported 403 passing, 24 failing and 1,079 ignored tests. Failures include API normalization and legacy parity, MCP schema validation, Apify fixture setup and CLI timeouts. Disposable database cases still require their dedicated stage. |
| Database, dashboard, extension and release | NOT TESTED | The combined runner stopped at the Rust stage. The separate production cutover and live Naukri receipt remain pending. |

Repair the observed Rust failures, then resume combined validation on the next clean candidate. Use stage outcomes and verified capabilities for progress reporting. Overall project completion still requires installed and live acceptance.
