# Rust migration checkpoint, 2026-11-15

Implementation: [`c7c73e37930284a4e78c9856fee6e7f22ad56e1b`](https://github.com/karanagg166/automated-apply/commit/c7c73e37930284a4e78c9856fee6e7f22ad56e1b),
branch `feat/rust-agent-runtime`, [PR #50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling` ([PR #49](https://github.com/karanagg166/automated-apply/pull/49)).
**Whole-project acceptance is IN PROGRESS.** This checkpoint is engineering evidence, not
the owner's requested final completion report.

The existing missing-answer API now has Rust persistence for create, list, read, edit,
history and approval. All writes use a consistent profile/evidence snapshot; CAS edits,
history, invalidation of old drafts and signed owner-intent nonce claims share one
transaction. Approval requires the existing separate dashboard signing key and exact
route/body/time signature. A bearer alone cannot approve. Expired proofs are rechecked
when claimed, and changed facts require editing and a fresh review. Sensitive declarations
and credential answers are rejected. Saved drafts remain text, with no application authority.

| Check | Result | Evidence |
| --- | --- | --- |
| Standard Rust suites | PASS | 114 tests; zero failed; integration cases are ignored by this command |
| Dedicated native PostgreSQL suite | PASS | 94 tests; zero failed/ignored; 33.22 seconds; eight new missing-answer cases |
| Combined distinct count | PASS | 208 tests; differential comparisons remain within their containing tests |
| HTTP owner lifecycle and independent-connection persistence | PASS | Actual localhost HTTP/SQL using fictional data; create201, edit200, approval200; duplicate create retains record; no application packet or provider usage created |
| Staleness, concurrent edits, identity and ownership | PASS | Evidence changes invalidate approvals, profile changes report review_required, one concurrent CAS winner, foreign requests hidden, key collisions rejected |
| Signature and replay fences | PASS | Wrong path/body/time refused; signing key absent503; delegated client403; nonce persists through restart; expired proof rejected again before claim |
| Atomic failure recovery | PASS | Deferred commit and invalid inserted draft roll back answer state, draft, audit and nonce together; retry after confirmed rollback can use the same unconsumed nonce |
| Format / Clippy / diff | PASS | Format and diff clean; workspace/all-targets Clippy with warnings denied |
| Full Rust API/services, browser/application/Gmail adapters and Python removal | NOT TESTED | Still being migrated; full answer generation and reusable-answer storage remain next |
| Live owner DB, browser focus, Telegram delivery, installed cutover and new receipt | NOT TESTED | These tests do not use owner data or installed services |
| Whole-project CPU/RSS/GPU comparison | NOT TESTED | No new comparison; suite duration is not a performance gain claim |
| Hosted Actions / merge | NOT TESTED | No dispatch or merge performed |

Sanitized rejection codes include `missing_input_version_conflict`,
`missing_input_context_changed_edit_before_approval`, `sensitive_answer_not_retained`,
`missing_input_identity_collision`, `owner_approval_required`,
`owner_approval_operation_mismatch` and `owner_approval_already_used`.
Private logs, candidate information and secrets are excluded.

Reproduce from the canonical repository:

```sh
CARGO_INCREMENTAL=0 cargo test --locked --workspace
CARGO_INCREMENTAL=0 uv run --no-project python rust/scripts/run_postgres_tests.py
CARGO_INCREMENTAL=0 cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all --check
git diff --check
```

The initial validation ran in the previously registered linked worktree on this Mac.
The owner then requested canonical-directory-only development. The clean canonical
checkout at `78c291c` was a verified ancestor; a local temporary integration branch
fast-forwarded the existing Rust history, preserving the original branch. The canonical
checkout now uses `feat/rust-agent-runtime`; the former worktree is detached. No source
was overwritten or discarded. Subsequent development belongs in the canonical checkout.
Storage cleanup and any remaining old runtime references require separate actual evidence;
this report does not assert that the Library folder is safe to clear.

Remaining work: complete answer generation/reuse, other REST/service/provider/browser/
application/Gmail/full Telegram ports, then validate combined contracts, installation,
rollback, focus, policy/history/identity/PDF integrity, resource use and real receipts.
