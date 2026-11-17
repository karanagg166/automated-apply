# Expanded platform packet preparation

Local branch `feat/rust-agent-runtime`, implementation `8e946a27c422ce7fead3d4f7b1e09374ce972305`.

Instahyre, Wellfound, YC Work at a Startup, Internshala and HiringCafe now have packet preparation rules for saved provider listings. The selector checks the provider host and listing identity. The packet directs the owner to the canonical provider listing, including when an importer has also reported an external employer link. Legacy and Naukri destination rules remain on their existing paths. The browser context keeps the new packet sources in manual handoff until the separate browser adapters have approval and evidence.

Himalayas and We Work Remotely packets retain the exact feed application link after it matches the canonical job identity and the stored observation. The selector uses the known expiry from the saved feed. A changed or expired destination makes the packet stale and the dashboard shows the provider backlink by name. [Himalayas API reference](https://himalayas.app/docs/remote-jobs-api), [Himalayas API terms](https://himalayas.app/terms), [We Work Remotely RSS attribution](https://weworkremotely.com/remote-job-rss-feed)

| Gate | Status | Evidence |
| --- | --- | --- |
| Source and formatting | PASS | Rust formatting, standalone fixture formatting, frontend format and Git whitespace checks passed. |
| Standard fixtures | NOT TESTED | Four additions cover the new portal links, listing identity, feed provenance and time-based fingerprint drift. The 4,968-case legacy destination corpus remains in the suite. |
| Disposable PostgreSQL fixture | NOT TESTED | One addition covers packet creation, preservation of the feed link, refusal to create a browser command and stale handling after the saved evidence changes. |
| Current build and combined run | NOT TESTED | Zero tests executed for this checkpoint. The last validated baseline remains `9c4ace570535a5856184775f8045ee89eafdd05f` with 193 standard Rust and 262 disposable PostgreSQL passes. |
| Live accounts, forms, timing and receipts | NOT TESTED | Public documentation research only. The provider detail examples are fixture shapes rather than live account evidence. Runtime, queue, budgets and installed services were untouched. |

Include `cargo test --locked -p automated-apply-agents --test packet_platform` and `uv run --no-project python rust/scripts/run_postgres_tests.py` in the combined local gate. The estimate remains 58% complete and 42% remaining pending verification. Continue the platform discovery and account adapter work, then the combined gate and reviewed local acceptance.
