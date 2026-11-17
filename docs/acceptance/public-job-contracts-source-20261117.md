# Actual public job/query contracts — source checkpoint 2026-11-17

Implementation [e4da98431b9471ef0e95b586589f1e37df6eaf74](https://github.com/karanagg166/automated-apply/commit/e4da98431b9471ef0e95b586589f1e37df6eaf74), branch `feat/rust-agent-runtime`, [PR 50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`. Untested, uninstalled source.

Actual NormalizedJob and DiscoveryQuery schemas are frozen through the existing pure exporter. Native normalization preserves declared fields/defaults, ordinary-string versus Literal whitespace behavior, boolean/number coercion, strict experience evidence, finite bounded salary, UTC dates, original versus ATS identity rules, unknown company flags and tri-state remote evidence. Original evidence links remain intact while canonical identity is computed separately. Observation ordering and the actual 256-KiB serialized record limit are preserved. A conservative 1-MiB incoming envelope limit precedes ignored-field removal. Query pagination/list limits and extra-field refusal remain explicit. This pure contract grants no provider, identity, verification or application authority.

Provider research used primary [Greenhouse](https://docs.greenhouse.io/job-board), [Lever](https://github.com/lever/postings-api/blob/master/README.md) and [Ashby](https://developers.ashbyhq.com/docs/public-job-posting-api) references. Provider-specific normalizers, transport and startup orchestration follow; the new contract is not yet a working feed adapter.

| Gate | Result | Exact evidence / limitation |
| --- | --- | --- |
| Source integration | PASS (source only) | Actual schema generation, native job/query normalizers and formatting applied |
| Standard additions | NOT TESTED | 3 declarations: 70 actual job DTO cases, 30 actual query cases and payload/record bounds; fictional pinned observation time, no provider clients/settings imported by oracle |
| Current tests/build/check/lint/types | NOT TESTED | New executed tests: 0; full source precedes combined gates |
| Actual Mac/provider/install | NOT TESTED | No real feed/account/application/browser/production or installation operation |
| Timing/resources | NOT TESTED | Pure source bounds only, no runtime measurement or performance improvement claim |

The initial schema-generation command used a direct script path and failed with `ModuleNotFoundError: backend`. It was corrected to the repository module invocation `uv run --no-project python -m rust.scripts.export_startup_contracts --write`, which generated the source successfully. This was a generation-path issue, not an executed test result. No other failure logs or private data are published.

Deferred reproduction: `uv run --no-project python -m rust.scripts.export_startup_contracts --check`, `cargo test --locked -p automated-apply-agents --test job_source_contract`, then full `uv run --no-project python scripts/run_acceptance.py` after the remaining agreed source. Continue the seven public provider normalizers, fixed-host transport, durable pacing/retained discovery and startup job-led ingestion, plus reviewed Apify execution and other remaining platform/runtime source.

Last validated `9c4ace570535a5856184775f8045ee89eafdd05f` remains 193 standard +262 dedicated native PG =455 distinct passes, not current-source evidence. Estimate remains 58% /42%. Last observed STOP162, lifetime4/hourly1, three quarantines, zero strict worker receipts and all identity/PDF/filter/focus constraints remain unchanged. No hosted Actions, merge, cleanup, sending or installation occurred.
