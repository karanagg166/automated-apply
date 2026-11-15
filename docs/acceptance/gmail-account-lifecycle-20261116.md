# Gmail account lifecycle — qualified source acceptance

Branch `feat/rust-agent-runtime`; implementation
[`01c3f6b0d8f283dffcc21f3b20e1fdc601debb41`](https://github.com/karanagg166/automated-apply/commit/01c3f6b0d8f283dffcc21f3b20e1fdc601debb41),
[PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`.
This checkpoint records the source port. The full project plan remains active/incomplete;
no installed account, provider consent, migration or application acceptance is implied.

The native service now preserves the two local Gmail account slots and existing encrypted
owner-preference keys. Explicit strict read/draft consent starts a generation-bound,
browser-bound one-use PKCE intent. A callback consumes its intent before token exchange,
requires the exact callback URI and scopes, cross-checks Google/Gmail identity, enforces
allowlist/reauthorization identity and prevents the same identity occupying two slots.
Only GET on the shared-policy callback path is exempt from bearer authentication; TLS,
peer, Host, origin and extension-client boundaries still run. Cookies are HttpOnly,
SameSite=Lax and Secure for HTTPS callbacks. Duplicate state/code/cookies fail closed.
No sending grant mode or sending endpoint is introduced.

Account access retains encrypted tokens, strict expiry, generation fences, a70-second
refresh lease and identity checks. Network calls run outside DB transactions; generation
and lease are checked again before saving. Disconnect commits a scrubbed new local
generation before attempting provider revocation. Failed revocation returns a fixed
manual-revocation-required state. All writes include production timestamp columns,
verify returned values and commit before acknowledgement. Suppressed/deferred writes
never produce success. Account IO shares the existing transient permit with generation
and document IO; no new pool or peak connection is added, and control/Stop stays separate.

A new concurrency regression exposed an expired-lease bug: a newer refresh could copy the
older lease from its baseline back into saved state. The older request could then mistake
that restored lease for ownership and clear newer credentials. The Rust port removes
expired lease fields on completion and refuses a superseded result before publishing it.
The equivalent legacy Python baseline correction is included with two regression cases.
Neither source correction was installed into the existing production release.

| Check | Result | Exact evidence / limits |
| --- | --- | --- |
| Full standard Rust workspace | PASS |181 passed,208 PG cases ignored;4 new standard cases are included, not additional |
| Native fictional PostgreSQL account suite | PASS |11 cases,0.42s after correction; actual IO, CAS/lease races, transaction/commit failures |
| Actual HTTP consent/cookie/callback/verify/disconnect | PASS |One of the11; real local API and Google transport against fixed loopback fixtures; no owner credentials |
| Callback/refresh replay and concurrent disconnect | PASS |Within11; expired/new intents, cross-slot identity, identity mismatch, newer lease success and unknown exchange covered |
| Legacy Python account regression module | PASS |17 tests,3.08s;2 new expired-lease success/failure cases, fictional SQLite/HTTP fixtures |
| All-target Clippy / Rust formatting / Python Ruff | PASS |Clippy17.13s, warnings denied; E9/F/I and formatting pass |
| Private project continuity | PASS |Snapshot and verify succeeded; available local references only, no account/session identity rewriting |
| Complete PostgreSQL/regression cycle | NOT TESTED |Only11 targeted PG cases this checkpoint; final sequential combined acceptance awaits remaining source integration |
| Search/body review/drafts/alerts/Drive and legacy account variants | NOT TESTED |Separate ports remain; this checkpoint implements local account lifecycle only |
| Owner Gmail login/provider account | BLOCKED |Prior real account search requires reauthorization; saved connected state is not live verification; no consent/retry requested here |
| Installed service/whole-family migration | NOT TESTED |Legacy installed services unchanged; no role grant/schema/config/browser action |
| Resource comparison/full plan/real application | NOT TESTED |No CPU/RSS improvement or receipt claim; full migration/live gates remain |

Account listing explicitly marks the unported Rust alert poller unavailable while retaining
its configured policy. It does not claim monitoring works or alter saved settings. No new
UI component was added. Existing frontend routes remain gated by session/CSRF and the fixed
BFF route list. No frontend rebuild is claimed for this Rust/Python-only checkpoint.

Initial fixture helper naming failed compilation; corrected. Clippy rejected compact
adjacent test `if` statements; explicit formatting fixed them. The expired-lease race first
failed with reauthorization instead of superseded-refresh, then passed after the substantive
correction above. Private logs are `.local/mailbox-*`; upstream error text and credentials
are never included in this sanitized report.

Reproduction:

```sh
cargo test --locked --workspace
uv run --no-project python -m rust.scripts.run_postgres_tests --filter mailbox_
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all --check
uv run --no-project --python .venv/bin/python python -m pytest backend/tests/test_phase54_mailboxes.py -q
uv run --no-project --python .venv/bin/python python -m ruff check --isolated --select E9,F,I backend/app/integrations/gmail/mailboxes.py backend/tests/test_phase54_mailboxes.py
```

Continue bounded selected-message reading/MIME evidence and exactly reviewed idempotent
drafts, alert polling/Drive/legacy accounts, remaining browser/execution/provider/CLI/
Telegram/platform ports, then complete source integration and the combined test cycle.
The eventual STOP-only whole-family cutover still requires reviewed schema/role headroom,
rollback, actual account/resume/focus/restart/resource evidence and strict worker receipts.
Supervised4/hourly1, three quarantined admissions, pending login and no unknown replay remain.
No provider message, draft, application admission, hosted Action, merge or cleanup occurred.
