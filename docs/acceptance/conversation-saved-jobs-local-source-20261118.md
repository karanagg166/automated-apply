# Dashboard search preferences and Telegram saved jobs

Local branch `feat/rust-agent-runtime`. Source commits `86d438fafbf39f34942e93aa76473d42fe390415` and `d7fddf963f655d18e81183d02366f1574d141af4`.

The existing dashboard preference endpoint reads and replaces the saved filter set with owner authentication and write acknowledgement. The configured Telegram host can search the bounded saved-job window, show a numbered result, recheck selections against current preferences, preview policy and application history, and prepare a packet for dashboard review. The displayed links exclude query strings and fragments. Private Telegram replies, replay records and update progress use the same transaction. The search does not start discovery or send an application.

| Gate | Status | Evidence |
| --- | --- | --- |
| Source and formatting | PASS | `cargo fmt --all`, standalone formatting of the new fixture, and `git diff --check` passed. |
| Fictional reference generation | PASS | Generated 1,620 legacy filter cases and nine preference cases. Native comparison is deferred. |
| Native tests | NOT TESTED | Two standard fixtures and two PostgreSQL fixtures added. Zero executed on these commits. |
| Live delivery and local installation | NOT TESTED | No production database, Telegram transport, browser, or installed service action during this checkpoint. |
| Timing and resources | NOT TESTED | Saved reads are capped at 200 jobs plus one row to detect the limit. No measured comparison. |
| First strict Naukri receipt | NOT TESTED | Prior recorded count remains zero. This checkpoint does not change the local queue or submission limits. |

Use `uv run --no-project --python backend/venv/bin/python -m rust.scripts.export_conversation_filters --write` to regenerate the reference cases. The combined local gate should include `cargo test --locked -p automated-apply-agents --test conversation_filters` and `uv run --no-project python rust/scripts/run_postgres_tests.py` with its disposable database harness. The last validated baseline remains `9c4ace570535a5856184775f8045ee89eafdd05f`, with 193 standard Rust passes and 262 dedicated PostgreSQL passes.

Continue the remaining tool and platform source, inventory the contracts and fixtures, then run combined validation before installation and live acceptance. Estimate held at 58% complete and 42% remaining. GitHub publication is suspended under the owner’s local-only direction.
