# Local Rust release package and rollback inputs

Local branch `feat/rust-agent-runtime`, implementation `5d47c495e5bf0a7ce5ae139e31bec6022f518303`.

The combined plan now builds the optimized Rust workspace and records a checksum inventory of four binaries, the standalone dashboard and launcher, the reviewed SQL, and the Brave and Edge bundles. Edge has its own output directory, so both builds preserve the stable extension ID and the browser-specific native host. The staging tool ties the inventory to the complete clean-commit report, checks build outputs again, and copies verified artifacts once into the private release directory.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source and plan | PASS | Python lint, JavaScript syntax and formatting, and Git whitespace checks passed. The plan lists 36 stages and schedules optimized build and artifact inventory last. |
| Installed rollback inputs | PASS | A private filesystem snapshot saved nine launch and native messaging definitions. All 16 recorded direct references were present and verified. The snapshot operation compared the saved definitions against the installed files. |
| Release build and fixture suite | NOT TESTED | The optimized build, checksums, staging regressions and separate Edge output regression await the combined run. |
| Restore and live operation | NOT TESTED | A launchd restore drill, browser connection and live Naukri worker receipt remain pending. |

Use the [runtime ownership procedure](../architecture/runtime-ownership.md) to revalidate a current rollback snapshot immediately before cutover. The snapshot covers the recorded launch definitions and direct paths. The legacy process inventory, database compatibility, service health, and rollback drill remain separate installation checks.

The estimate remains 58% complete and 42% remaining. All evidence is local.
