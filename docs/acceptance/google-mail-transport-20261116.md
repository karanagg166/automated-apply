# Google/Gmail protocol transport foundation — 2026-11-16

Implementation [7921916747991bbab69968edfa9c7b84648b51b1](https://github.com/karanagg166/automated-apply/commit/7921916747991bbab69968edfa9c7b84648b51b1),
branch `feat/rust-agent-runtime`, base `chore/uv-python-tooling`, [PR50](https://github.com/karanagg166/automated-apply/pull/50).
Continued implementation checkpoint only; the complete plan remains ACTIVE.

The native Gmail reader has only fixed GET message-list/message operations, encoded
query parameters, the existing25-message client cap and metadata-header selection.
Invalid IDs and reserved write-operation names are refused before dispatch. Response
bodies are bounded to1MiB; statuses/errors have fixed categories. Tokens have no Debug
representation, authorization headers are sensitive, and requests do not use proxies,
redirects or automatic retries. No mailbox send/modify/delete operation exists here.
The higher account service must still enforce consent, scope, selection and retention;
these leaf clients are not exposed as working account endpoints.

The fixed Google client implements authorization-code PKCE parameters, refresh,
userinfo plus Gmail-profile identity matching and explicit credential revocation for a
future owner disconnect action. Grant modes exclude SEND; the application will retain
READ + CREATE DRAFT ONLY even though Google's compose OAuth scope is broader. Token
DTO validation and alias-normalized scopes preserve existing contracts. Callback URI
validation checks the exact raw approved path, including rejecting dot-segment aliases.
The client adds a1MiB response bound to the legacy Google transport. Production hosts
are fixed HTTPS; alternate endpoints require explicit fixture mode and exact numeric
loopback. Keyring/state/account generation/refresh lease wiring remains a separate port.

Primary protocol references: [Gmail list](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list),
[Gmail get](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/get),
[Google OAuth PKCE](https://developers.google.com/identity/protocols/oauth2/native-app),
[Google OpenID/userinfo](https://developers.google.com/identity/openid-connect/openid-connect).
No real grant, mailbox read, credential refresh, revocation or Google account request
was performed. Documentation retrieval is not account/provider acceptance.

| Check | Result | Exact scope |
| --- | --- | --- |
| Gmail native client | PASS |3 tests,0.01s; real loopback HTTP, fictional tokens/data |
| Google OAuth native client | PASS |5 tests,0.23s; real loopback protocol fixtures |
| Actual isolated Python builder | PASS |Four authorization query maps across permitted modes; inside one native test |
| Actual Python token DTO | PASS |20 accepted/rejected cases; inside one native test |
| Clippy/format/diff | PASS |All targets with warnings denied; latest Clippy11.61s |
| Added dependency | PASS |Pinned base640.22.1 already existed in lockfile; no existing version upgrade |
| Active account routes/callback/storage lifecycle | NOT TESTED |Not wired by this foundation; implementation continues |
| Live OAuth consent and mailbox | NOT TESTED |No real token/account configuration loaded |
| Production installation or whole-plan completion | NOT TESTED |Existing installed runtime unchanged |

Tests include encoded queries, message page bounds, metadata/body format selection,
401/403/429, redirects, malformed/non-object/oversized bodies, no-dispatch invalid IDs,
production endpoint override refusal, strict token bounds/types, scope aliases, PKCE
query equivalence, cross-mailbox identity failure and sanitized invalid-grant errors.
Component comparisons inside tests are not additional test counts. Earlier358 Rust,
309 frontend and other suite results remain prior qualified evidence, not rerun here.
No paired CPU/RSS/latency comparison is claimed from these short fixture timings.

```sh
cargo test --locked --workspace --test google_oauth --test gmail_read
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
git diff --check
```

Raw fixtures/logs remain ignored. No production DB/schema, owner browser/profile,
application quota/history, installed release, hosted Actions, merge or cleanup changed.
Next complete private authenticated local transport for the production MCP/native API,
then consent/state/account generation/refresh fencing and remaining mail/Drive/browser/
execution/platform ports. Do not equate a passing protocol client with an operational
mailbox or a completed autonomous project. Continue without a partial final report.
