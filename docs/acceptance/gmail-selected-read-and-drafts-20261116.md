# Selected Gmail reads and reviewed drafts — qualified source acceptance

Branch `feat/rust-agent-runtime`; implementation
[`10f4bc62d39c57dcf557a22c995d705515602e5a`](https://github.com/karanagg166/automated-apply/commit/10f4bc62d39c57dcf557a22c995d705515602e5a),
[PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`.
The full approved plan remains active/incomplete. No source test implies an installed
mailbox workflow, owner consent, real draft or application receipt.

The two local-account APIs now support bounded INBOX metadata search, recent selected-body
review, draft listing, exact owner-reviewed draft creation and explicit self-test drafts.
Search retains only a15-minute slot/generation/message selection, at most5 results.
Body reading requires the existing reviewed-body setting and exact recent selection;
account changes during IO prevent publication. Bounded MIME parsing skips attachments,
script/style/head/template contents and unsafe links, removes URL queries/fragments,
and returns unverified keyword signals. Raw message bodies are not stored or returned,
and links are never opened. Those signals never confirm applications or account origin.

Drafts require the reviewed content hash and current account generation. The service
commits a durable dispatch intent before a single fixed `/drafts` POST. Replays and unknown
outcomes reconcile by RFC message ID and verify exact saved From/To/subject/body, no extra
recipients and DRAFT without SENT. Readback failures retain the admission/receipt rather
than repeating POST. Self-test drafts additionally search SENT using both original and
provider message IDs. Disconnect after admission preserves an unknown dispatch record;
it cannot publish a stale result or reopen an account. All account IO still shares the
one transient permit, with control/Stop on its separate existing connection.

MIME construction/header/address parsing use pinned `mail-builder`1.0.0 and
`mail-parser`0.11.9; `html5gum`0.9.1 tokenizes bounded HTML without a DOM. Default hostname
discovery is disabled. Four packages were added including build-time `hashify`0.2.9;
a parsed lockfile comparison confirms existing external versions/checksums/edges unchanged.
The parser's newer1.0.1 requires Rust1.98, above the declared workspace minimum1.94;
it was not adopted. This checkpoint compiles on the current host toolchain; a fresh
minimum-toolchain build was not run. Library source/API was inspected locally; see the
[builder](https://github.com/stalwartlabs/mail-builder),
[parser](https://github.com/stalwartlabs/mail-parser) and
[tokenizer](https://github.com/untitaker/html5gum) primary repositories.

| Check | Result | Exact evidence / limits |
| --- | --- | --- |
| Full standard Rust workspace | PASS |186 passed;216 PG cases ignored, not counted as passes |
| Complete targeted local-account PG group | PASS |19 passed,0.74s;11 lifecycle +8 new read/draft cases, real disposable PostgreSQL/loopback HTTP |
| New read/draft PG group | PASS |8 passed,0.38s in preceding focused run; overlaps19, not additional |
| MIME/DTO/content oracle and roundtrip tests | PASS |5 tests within186;42 actual Python MIME cases,34 reviewed DTO cases,4 hashes;4 native MIME roundtrips including maximum-length Unicode subject, plus edited-content/recipient checks |
| All-target Clippy / Rust formatting / diff check | PASS |Clippy8.58s with warnings denied; formatting and diff clean |
| Existing frontend / legacy Python | NOT TESTED |No frontend or Python source changed in this checkpoint; previous317 UI and17 Python module results remain separate prior evidence |
| Entire PG suite / final combined acceptance | NOT TESTED |Only the19 related PG cases ran; final sequential cycle waits for remaining source integration |
| Actual owner Gmail/provider draft | NOT TESTED |All HTTP used numeric-loopback fixtures and fictional credentials/messages; no Google account or mailbox operation |
| CPU/RSS/resource comparison | NOT TESTED |Test durations are not speed/resource comparisons |
| Alert poller / Drive / legacy account variants | NOT TESTED |Separate ports remain; monitoring availability stays explicitly false without changing its saved policy |
| Full Rust cutover / browser/live application | BLOCKED |Remaining service/platform source and migration/account/focus/receipt gates still apply |

The address parser initially saw a bare header value without its RFC line terminator and
missed a trailing second address. A regression exposed it; the corrected bounded header
input rejects multiple/group recipients. The generic draft path initially failed Rust's
borrow check while adding a receipt; an owned ID corrected it. Native roundtrips now also
decode complete bounded RFC2047/folded subjects before exact content comparison, rather
than comparing the shortened UI preview. This supports Unicode subjects while refusing
header injection. One Clippy collapsible-branch finding was corrected. Final checks pass.

The8 new PostgreSQL cases cover actual API route/auth/review validation, selected INBOX
read/no body at rest, changed labels, disabled consent, expired selection, suppressed
pre-POST admission, one-write replay, changed saved content, ambiguous POST reconciliation,
failed readback/SENT rejection, and disconnect during body fetch or after POST admission.
They create only fictional local fixture drafts; they do not exercise Gmail production.
No sending/modify/delete transport endpoint exists.

Reproduction:

```sh
cargo test --locked --workspace
uv run --no-project python -m rust.scripts.run_postgres_tests --filter mailbox_
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all --check
```

Private fixture logs stay under ignored `.local/mail-*`. No environment, token, candidate
record, resume, real message or private screenshot was published. Continue Drive, legacy
account/history/alert variants, browser/execution/provider/CLI/Telegram/platform ports and
complete source integration. Then run the final combined cycle and reviewed STOP-mode
whole-family migration/rollback, actual account/PDF/focus/restart/resource and receipt
acceptance. Supervised4/hourly1, three quarantined admissions and the first strict worker
receipt prerequisite remain. No real message/draft, Apply, installed change, hosted Action,
merge or cleanup occurred.
