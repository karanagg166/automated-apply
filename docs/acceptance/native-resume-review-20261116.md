# Native saved resume review — qualified acceptance

Branch `feat/rust-agent-runtime`; implementation
[`d8c02569b4dff61465086a3f2e867ede12e42a15`](https://github.com/karanagg166/automated-apply/commit/d8c02569b4dff61465086a3f2e867ede12e42a15),
[PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`.
The complete project plan remains active/incomplete; this is a source checkpoint.

The existing five resume-sync owner routes now run natively: status, source CAS, saved
review inspection, explicit approval and the intentionally deferred `/sync` response.
The current [account plan](../plans/real-account-connection-plan.md) selects manual PDF
upload; private Drive OAuth is optional future work. Existing production code also
rejects live downloads and enabling them. The Rust port preserves that boundary, exposes
`download_available=false`, does not reuse Gmail credentials or change sharing, and does
not report a Rust scheduler as active. No Drive downloader or authenticated connection
is claimed operational.

Source changes preserve archived versions, bytes and active pointers. Inspection combines
saved unverified evidence with the current profile; proposed skills preserve existing
skills without writing facts. Approval requires explicit owner confirmation, current
source/latest version and profile, explicit skill-removal consent and correct PDF digest/
resource binding. One transaction updates profile facts and material resume association,
private primary resource, approved evidence, encrypted review and active source pointer.
A production-equivalent trigger advances the profile once. Prior prose/packet snapshots
and PDF ciphertext remain unchanged. Lost-response replay creates no additional evidence
or timestamp changes. Missing-profile creation uses only the explicit approved input.

Returned state is checked before commit, including resource confirmation, review ciphertext/
status and source pointers. Suppressed/rewritten writes finish rollback before error
acknowledgement. Deferred commit failure is marked unknown, closes/reconnects the control
connection, and never replays approval automatically. Independent history inspection stays
available after reconnect. Fixed static SQL is used for both profile update/insert paths.

Status uses two metadata queries for the50-version page and older active/latest pointers,
with no additional connection. The functional test retains both pointers outside a full
page of53 versions. This removes per-version status queries and avoids converting encrypted
review blobs to JSON for metadata. This is a source query bound, not a measured CPU/RSS/
latency gain. Model services, provider calls and browser controls are absent from this path.

| Check | Result | Exact evidence / limits |
| --- | --- | --- |
| Full standard Rust workspace | PASS |188 passed;225 PG cases ignored, not counted as passes |
| Full native disposable PostgreSQL suite | PASS |225 passed in50.62s;413 distinct Rust cases with standard suite |
| New resume-review PG group | PASS |9 cases within225; targeted1.76s run overlaps the full run |
| Pure request/evidence oracles | PASS |2 tests within188;14 source inputs,14 approvals,10 source URLs and4 evidence-difference cases compare actual isolated Python |
| Existing legacy resume module | PASS |35 tests in8.30s; fictional injected downloads/reviews, not owner Drive access |
| Frontend unit suite | PASS |317 tests /45 files in16.19s; existing typed fixture updated for the false availability literal |
| API regeneration / TypeScript / formatting | PASS |Frozen OpenAPI export uses testing in-memory config, pnpm API types regenerated; typecheck/Prettier pass |
| Clippy / Rust formatting / Python Ruff / diff | PASS |All-target Clippy14.82s, warnings denied; E9/F/I and formatting pass |
| Frontend semantic contract drift | PASS |AST comparison finds no added/removed/changed paths or operations; only SyncStatus changed. Generated router ordering/comments moved |
| Actual owner resume/account/provider/browser | NOT TESTED |All new PDF/DB/HTTP evidence is fictional; no owner PDF, sharing, OAuth, app/tab or installation action |
| Drive OAuth/download/scheduler | DEFERRED |Intentional current workflow boundary; manual PDF upload remains supported |
| Resource/whole-project live acceptance | NOT TESTED |No paired CPU/RSS/latency benchmark, whole-family installation or real receipt |
| Full approved plan | BLOCKED |Remaining account/alert/browser/execution/provider/CLI/Telegram/platform ports and final combined/cutover/live gates remain |

The9 new PostgreSQL cases cover real owner HTTP/auth/strict review, source CAS and history,
unverified suggestions with no write, exact atomic approval/replay, stale generation/
profile/digest/primary-resource checks, explicit removal and new-profile inputs, rewritten
confirmation/ciphertext/source state, failed deferred commit, older pointers outside the
history page, and actual API reconnect without automatic replay. The reconnect fixture's
nontransactional counter proves exactly one attempted approval despite repeated status
reads. Locks are independently checked released after rejection.

Initial compile rejected a dynamically constructed SQL string; it was replaced with
checked-in static parameterized SQL. The isolated Python oracle initially lacked its
Literal import; corrected. API regeneration exposed an existing typed fixture missing the
new false availability field; corrected. A test-only unused setup variable was removed.
All final checks above pass. Private logs remain ignored under `.local/resume-review-*`.
No private environments, resumes, owner facts, ciphertext, raw logs or screenshots are
published in this report. No visual UI change required a new screenshot.

Reproduction:

```sh
cargo test --locked --workspace
uv run --no-project python -m rust.scripts.run_postgres_tests
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all --check
uv run --no-project --python .venv/bin/python python -m pytest backend/tests/test_resume_sync.py -q
uv run --no-project --python .venv/bin/python python backend/scripts/export_openapi.py
pnpm -C frontend api:types
pnpm -C frontend typecheck
pnpm -C frontend exec vitest run
pnpm -C frontend format:check
```

Continue legacy Gmail account/history/alert variants and remaining browser/application,
provider/CLI/Telegram/platform ports. Complete source integration before the final combined
project cycle. The eventual STOP-only whole-family migration still needs schema/role
headroom, rollback, actual account/canonical PDF/focus/restart/resource and strict receipt
acceptance. Supervised4/hourly1, three quarantined admissions, pending login, and no unknown
replay remain. No installed service, queue policy, actual profile, application admission,
message, hosted Action, merge or data cleanup changed.
