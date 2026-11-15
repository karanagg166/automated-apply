# Rust owner notification preferences — 2026-11-15

Implementation [`1d8f25a7df5998d16e59ec220f3ab1e02000aeee`](https://github.com/karanagg166/automated-apply/commit/1d8f25a7df5998d16e59ec220f3ab1e02000aeee),
branch `feat/rust-agent-runtime`, [draft PR50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling`.

GET/PUT `/api/v1/dashboard/notification-preferences` now run in Rust. Reads preserve
defaults without inserting a row; PUT replaces the complete validated preference value
using defaults for omitted fields, matching the existing contract. In-app pause/opt-in,
digest, score thresholds, quiet-hour fields and timezone remain editable. Browser push,
Telegram and WhatsApp stay literal false in this preferences contract. Saving a setting
does not schedule or send a notification or alter profile/application state.

Writes commit before acknowledgement and verify the returned complete stored value.
Suppressed updates roll back; deferred commit failure returns an uncertain outcome and
closes the connection instead of advertising a retryable transaction. Invalid saved
preferences fail closed and remain repairable through a valid PUT. Error responses do
not echo rejected fields or saved canaries. Concurrent full replacements use an atomic
upsert; no partial merge or implicit channel activation occurs.

| Acceptance | Result | Exact evidence / limit |
| --- | --- | --- |
| Full standard Rust suite | PASS | **142 passed,0 failed,167 ignored PG cases**,11.15s sum of test bodies |
| Full native disposable PostgreSQL suite | PASS | **167 passed,0 failed,0 ignored**,38.34s test body |
| Distinct executed tests | PASS | **309**, disjoint suites |
| Actual Python DTO oracle | PASS | 738 cases, including598 available system timezone names, inside one standard test |
| Three new native PG tests | PASS | Owner HTTP defaults/replacement/readback/no dispatch; invalid input/saved data and repair; suppressed update and deferred commit rollback |
| All-target Clippy | PASS | `-D warnings`,10.80s; initial collapsible-match warning fixed without a lint exemption |
| Format/diff/Ruff/oracle drift | PASS | Commands below |
| Full production role/grant installation | NOT TESTED | Disposable fictional native PostgreSQL only |
| Mac live owner preference mutation/delivery | NOT TESTED | No owner DB, browser, model or message action in this milestone |
| Physical browser/account handoff | BLOCKED | Retained owner unlock/profile-open or Brave sign-in step remains pending |
| Whole-system resource improvement | NOT TESTED | Test timing is not a Python/Rust CPU/RSS/GPU/latency comparison |
| Full autonomous multi-platform project | FAIL | Remaining integration and acceptance below are incomplete |

Timezone validation uses bounded normalized relative names and four-byte TZif headers
under fixed public system timezone roots. It does not read an arbitrary supplied path,
consult a custom `PYTHONTZPATH`, or provide Python's packaged `tzdata` fallback. Exact
available-name parity is verified against this Mac's current598-name system database;
other OS/database versions need their own parity run. This slice validates preferences;
scheduled notification synchronization/quiet-window calculation is still a separate port.
No dependency or runtime Python subprocess was added.

Sanitized failures: invalid owner input422, corrupt saved value503, suppressed write409,
deferred commit failure503 without `X-Automated-Apply-Transaction`. The original value
remains after both failed-write fixtures. Tests verify105 existing fictional notifications
and105 delivery rows remain unchanged, and profile facts remain unchanged.

```sh
cargo test --locked --workspace
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
git diff --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.notification_preferences_corpus --check
uv run --no-project ruff check --isolated --select E9,F,I rust/scripts/notification_preferences_corpus.py
```

Ignored logs: `.local/rust-notification-preferences-{full,all-pg,clippy}.log`; focused
three-case native run passed in0.21s. Fixtures never load owner configuration or an
existing database. Published data contains no credentials, candidate PII or raw logs.

Next use this transaction-safe preferences reader in packet review notifications while
porting the execution-owner fence, exact review/approval and handoff/outcomes/tracking.
Complete browser/worker/Gmail/Drive/legacy CLI/Telegram/fallback ports, the
[expanded platform adapters/accounts](../plans/expanded-platforms-20261115.md), actual
employer receipts and installed STOP/rollback/focus/resource acceptance. Operational
STOPPED162, supervised4/hourly1, three uncertain jobs and zero strict worker receipts
are retained handoff findings, not freshly sampled or changed here. No hosted Actions,
merge, cleanup, source/build copy or production installation occurred.
