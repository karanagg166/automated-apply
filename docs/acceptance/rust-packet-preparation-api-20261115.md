# Rust packet preparation and inspection — 2026-11-15

Implementation: [`8befb06dd344cd81db18734f40fbe900c27c460b`](https://github.com/karanagg166/automated-apply/commit/8befb06dd344cd81db18734f40fbe900c27c460b),
branch `feat/rust-agent-runtime`, [draft PR50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling`. Development stays in the canonical checkout.

The seven-route preparation/inspection slice now uses Rust context, persistence and
readiness on the existing authenticated owner connection. No schema-shaped placeholder
or Python subprocess implements these routes:

| Method | Route |
| --- | --- |
| GET | `/api/v1/applications/platforms` |
| POST | `/api/v1/jobs/{id}/application-preview` |
| POST | `/api/v1/jobs/{id}/application-packets` |
| GET | `/api/v1/application-packets` |
| GET | `/api/v1/application-packets/{id}` |
| GET | `/api/v1/application-packets/{id}/readiness` |
| GET | `/api/v1/application-packets/{id}/events` |

Material context fingerprints retain Decimal salary strings, UTC Python datetime
representations, reviewed job/employer facts, resources/evidence, source observations
and approved owner-answer revisions. Read normalization retains legacy effective-answer
precedence, including a non-null empty human answer. Creation checks durable keys before
new preparation; identical retries return the original snapshot and fields even after
facts change. Packet, checklist fields, creation event and any missing-fact question
commit or roll back together. Shared parent locks and repeatable-read snapshots prevent
mixing parent revisions and edited fields. Known serialization/deadlock aborts during
missing-question insertion retain a separate internal rollback signal; packet retries
are bounded to one and happen after explicit rollback. Commit uncertainty is never
automatically replayed.

Preparations create seven core checklist fields plus up to50 owner questions, with
ephemeral preview IDs. They grant no approval, upload proof or submission authority and
never implicitly generate narrative drafts. Multiple selections require both the flag
and the installed, validated database constraint/function privilege. Missing profiles
remain previewable but cannot create durable packets; an unavailable explicit resume
never falls back to another selection. Closed, unknown and verified lifecycle overrides
retain their precedence. A naive expiry timestamp fails closed during readiness instead
of guessing its timezone; its public DTO representation remains compatible. The legacy
Python aware/naive comparison also cannot safely evaluate that value.

Added pinned `speedate0.18.0` with its stable `std` feature for datetime/numeric-timestamp
compatibility with the Pydantic parser family ([primary API documentation](https://docs.rs/speedate/0.18.0/speedate/struct.DateTime.html)).
Lockfile adds its four transitive packages. No toolchain change is required. The initial
no-default-feature attempt failed `E0554`; enabling `std` fixed it without nightly Rust.

| Acceptance | Result | Evidence / limits |
| --- | --- | --- |
| Full standard Rust suite | PASS | **137 passed,0 failed,150 PG tests ignored** |
| Full native PostgreSQL suite | PASS | **150 passed,0 failed,0 ignored**,34.85s test body |
| Distinct executed tests | PASS | **287** across those disjoint suites; oracle cases are not additional tests |
| New material-context oracle | PASS | 38 exact legacy snapshots/fingerprints in one standard test; native IO also compared under a non-UTC session zone |
| New saved DTO oracle | PASS | 135 actual Python-model/repository conversions in one standard test |
| New service-read oracle | PASS | 832 actual Python service/readiness combinations in one standard test |
| Native packet behavior | PASS | Six new tests: all seven HTTP routes, exact replay/staleness, conflicting and identical creation races, field/event failure rollback, shared-lock concurrency, profile/resume/multiple-selection gates, history and worker-receipt guards |
| All-target Clippy | PASS | `-D warnings`,7.70s |
| Formatting/diff, three new oracle drift checks, Ruff | PASS | Commands below |
| Real Mac runtime/platform/account acceptance | NOT TESTED | Tests ran natively on this Mac using fictional disposable PostgreSQL and loopback HTTP only |
| Whole-application CPU/RSS/GPU/latency improvement | NOT TESTED | Standard test-body sum6.09s is not an application benchmark or Python comparison |
| New runtime installation / live applications | NOT TESTED | Full Rust runtime remains uninstalled; no production DB/browser/model/Gmail/Telegram action in this milestone |
| Full migration and all requested integrations | NOT TESTED | Remaining work below; this milestone is not100% project completion |

The native fixture executes the repository's actual packet table/trigger SQL and the
worker followup definitions. It does not install the complete production grants/RLS
matrix, and is not evidence of production-role installation acceptance. Existing fixtures
drop the packet dependents together so foreign keys do not contaminate later tests.

Sanitized failure evidence: the first concurrent missing-question race returned
`missing_input_version_conflict`; after preserving the known rollback signal, both exact
retries converge on one packet/event. Injected field and event failures return
`packet_database_error` and leave no partial packet or missing question. Conflicting
requests return `packet_idempotency_conflict`; missing profile and unavailable multiple
selection return422; nonexistent records404; model/extension-client authority403.
Forged worker receipts and history mutation are rejected by the actual database guards.
No raw query parameters, private provider responses or environment values are published.

Reproduce in the canonical checkout:

```sh
cargo test --locked --workspace
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
git diff --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.packet_context_corpus --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.packet_record_corpus --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.packet_read_corpus --check
uv run --no-project ruff check --isolated --select E9,F,I rust/scripts/packet_context_corpus.py rust/scripts/packet_record_corpus.py rust/scripts/packet_read_corpus.py
```

Ignored local logs: `.local/rust-packet-flow-{full,all-pg,clippy}.log`. The PG harness
accepts only its own ephemeral localhost URL, never owner environment files or data.

Next finish packet edits, answer generation/review, immutable revision archives, manual
handoff/outcomes and their execution/notification coordination; browser intake and actual
worker execution remain separate. List reads currently rebuild context per packet, so
shared-inventory batching and measured list latency remain an optimization task before
full performance acceptance. Remaining Python services include browser/application,
Gmail/Drive, legacy Telegram/CLI and local fallback/rearranger/AGY paths. Actual per-platform
receipts, STOP installation/rollback, focus and resource comparisons remain open.

Retained operational handoff, not freshly resampled: legacy API/execution8e985c9, queue
STOPPED162, supervised4/hourly1, three uncertain jobs quarantined, zero strict worker
receipts. The owner unlock/profile-open or Brave sign-in step is still pending. No new
admission, quota reset, browser launch, hosted Actions, merge, installation or cleanup.
