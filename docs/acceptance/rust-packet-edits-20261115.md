# Rust revisioned packet edits — 2026-11-15

Implementation [`2ffe01b8cee2bc5db032010b29321646941b2c4e`](https://github.com/karanagg166/automated-apply/commit/2ffe01b8cee2bc5db032010b29321646941b2c4e),
branch `feat/rust-agent-runtime`, [draft PR50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling`. Extends the
[seven-route preparation milestone](rust-packet-preparation-api-20261115.md).

Three existing owner flows now run in Rust:

| Method | Route | Result |
| --- | --- | --- |
| PATCH | `/api/v1/application-packets/{id}` | Refresh saved context or change explicit resume selection; rebuild factual fields and clear old human/narrative answers |
| POST | `/api/v1/application-packets/{id}/questions` | Add up to50 questions within the100-field packet cap |
| PATCH | `/api/v1/application-packets/{id}/questions/{field}` | Save an owner answer within exact displayed option/length rules; review stays pending |

All three retain a parent write claim, lock current material in legacy order, enforce
revision CAS and archive the exact previous snapshot/fields before replacement. Archives
use the existing `prv:<compact UUID>:<revision>` key, canonical digest and first-insert
retention; no schema migration or stronger database immutability claim is implied.
Old approval is cleared. Freshness, profile identity and closed/submitted/unknown-state
gates remain; refresh can explicitly repair stale saved context. Upload fields reject
typed upload attestations. Multiple selections retain flag/database capability checks.

Creation and edits now require acknowledged field/event inserts and acknowledged refresh
metadata. A trigger returning NULL cannot silently omit a field/audit event or discard a
refresh while reporting success. Failed writes roll back the revision claim, archived
values, fields, missing-input questions and history. Human editing preserves the raw
proposed answer/provenance except the deliberate human source/resolver change.

| Acceptance | Result | Exact evidence |
| --- | --- | --- |
| Standard Rust workspace suite | PASS | **139 passed,0 failed,158 ignored PG cases**,6.21s sum of test bodies |
| Native disposable PostgreSQL suite | PASS | **158 passed,0 failed,0 ignored**,36.72s test body |
| Distinct executed tests | PASS | **297**; the suites are disjoint |
| New DTO/archive oracles | PASS | 68 actual Python edit DTO cases and four actual repository archive expressions, inside two tests; not extra test counts |
| Eight new native PostgreSQL cases | PASS | Actual HTTP edits/readback; CAS race; stale/closed/foreign/upload/options rejection; field/event rollback; exact100-field capacity and explicit resume behavior; real guard-validated approval clearing; concurrent profile correction; suppressed write rejection |
| All-target Clippy | PASS | `-D warnings`,9.32s |
| Format/diff/Ruff/oracle drift checks | PASS | Reproduction below |
| Full production role/grant/RLS installation | NOT TESTED | Tests execute actual packet/worker table/trigger definitions against fictional native fixtures, not the full production grant matrix |
| Real owner/browser/model/application effects | NOT TESTED | No owner DB, browser, model, Gmail or Telegram action in this milestone |
| Physical browser/account handoff | BLOCKED | Retained owner unlock/profile-open or Brave sign-in step remains pending; no repeat request or browser relaunch |
| Whole-application resource improvement | NOT TESTED | These timings are test bodies, not Python/Rust CPU/RSS/GPU/latency comparisons |
| Full migration / all requested integrations | FAIL | Remaining ports and live/installed acceptance below are incomplete; no100% claim |

Sanitized failure codes: competing old revisions return `packet_revision_conflict`;
concurrent corrected facts return `packet_context_changed`; closed packets return
`packet_closed`; file answers return `packet_upload_attestation_denied`; suppressed
writes return `packet_write_ack_failed`. Injection failures return
`packet_database_error` and leave the pre-edit packet/history intact. No private provider
body, credentials or candidate values appear in this report or the published fixtures.

```sh
cargo test --locked --workspace
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
git diff --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.packet_edit_corpus --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.packet_contract_corpus --check
uv run --no-project ruff check --isolated --select E9,F,I rust/scripts/packet_edit_corpus.py rust/scripts/packet_contract_corpus.py
```

Ignored local logs: `.local/rust-packet-edit-{full,all-pg,clippy}.log`; focused native
run `.local/rust-packet-edit-pg.log` passed eight cases in2.52s before the final full run.
No new dependency in this milestone. No production schema change or runtime installation.

Next implement packet generation with provider calls outside packet write claims and a
fresh post-call CAS/context check, exact human review/approval with execution-owner fence
and transactional notification updates, manual handoff/outcomes and tracking. Browser
intake/worker, Gmail/Drive, legacy Telegram/CLI/fallback/rearranger/AGY, per-platform actual
receipts and STOP installation/rollback/focus/resource comparisons remain. List context
batching/measurement remains an optimization task. Do not expose placeholder approval or
claim a manual outcome as a strict worker receipt.

Operational handoff retained without fresh sampling: legacy API/execution8e985c9, full
Rust runtime uninstalled, STOPPED162, supervised4/hourly1, three uncertain jobs quarantined,
zero strict worker receipts. No quota/admission reset, external submission, browser focus
change, hosted Actions, merge, cleanup or new source/build copy occurred.
