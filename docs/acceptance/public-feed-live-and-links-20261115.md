# Public feed links and actual response validation — 2026-11-15

Implementation [`70a18eeb31c475aafaf11bcf415f5445d1a2b20d`](https://github.com/karanagg166/automated-apply/commit/70a18eeb31c475aafaf11bcf415f5445d1a2b20d),
branch `feat/rust-agent-runtime`, [draft PR50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling`. This follows the
[complete runtime boundary checkpoint](runtime-review-and-boundaries-20261115.md).

The [official Himalayas API documentation](https://himalayas.app/api) requires preserving
`applicationLink` unchanged and describes `pubDate` as last updated. Public jobs now
retain an exact validated `application_url`, independently of normalized `source_url`
used for attribution/deduplication. Query/fragment tracking variations cannot duplicate
the source identity, and URL whitespace/control normalization is rejected. Himalayas
sets `source_updated_at`; `published_at` stays unknown. An updated listing therefore
cannot establish that the original posting satisfies an age filter.

The [official WWR feed documentation](https://weworkremotely.com/remote-job-rss-feed)
identifies the fixed public RSS endpoint and requires attribution. A real native
request exposed a valid unusually large description that exceeded the parser's
per-field limit. The RSS parser now retains at most2,048 Unicode characters per
description and explicitly marks `description_truncated`, while continuing to parse
all XML and retaining the complete4MiB response limit. Other fields, item/depth limits,
doctype refusal, fixed HTTPS hosts, no redirects/retries/proxies and durable runtime
cooldowns remain. Previews are untrusted source excerpts, not complete eligibility
evidence. Himalayas previews use the same explicit truncation marker.

| Check | Result | Actual evidence and qualification |
| --- | --- | --- |
| Full standard Rust workspace | PASS | **156 passed,0 failed**,181 PG cases ignored here |
| Dedicated native PostgreSQL suite | PASS | **181 passed,0 failed,0 ignored**,47.38s; fictional isolated database |
| Distinct Rust tests | PASS | **337** across disjoint suites; four additional public-feed regressions |
| Final parser boundary rerun | PASS | **9 passed**,0.02s; includes extra mixed XML entity/CDATA and4MiB assertions after the full run; overlaps156 |
| All-target Clippy/format/diff | PASS | Warnings denied; Clippy11.20s; no new dependency |
| Actual Himalayas native HTTPS + parse | PASS | One request,20 jobs,0 invalid/duplicate rows,163ms; before final preview-marker correction, same transport and link/date parsing |
| Original actual WWR native HTTPS + parse | FAIL | One request,1,662ms,`public_feed_response_invalid`; do not erase this failure |
| Bounded WWR diagnostic retrieval | PASS | One further explicit diagnostic GET, HTTP200, RSS content type,2,288,206bytes,1,684ms; no retry |
| Final Rust parser on that saved actual response | PASS | Zero further requests,20 returned previews,0 invalid/duplicate rows,`has_more=true`,20 marked truncated,58ms |
| Fresh final WWR native network + parse | NOT TESTED | Saved-response replay validates the correction; no third native/diagnostic retrieval performed |
| API-backed public-tool durable cache | PASS | Existing fictional PG suite includes reservation/cache/failure durability and suppressed-admission cases; not exercised against owner DB |
| Public-feed ingestion / automatic application | NOT TESTED | Both probes report `saved_to_job_queue=false`, `application_dispatch=false`; no ingestion implemented |
| Existing Mac Brave/API check | PASS | Earlier fresh native health and API health/readiness200, STOPPED162; no new installation here |
| Live signed-in Naukri identity | BLOCKED | Fresh owned Brave tab inventory found0 `www.naukri.com` tabs; no navigation/login attempted |
| Codex history backup integrity | PASS | Private snapshot saved6 available transcripts; verify checked569 retained transcript references;98 indexed source transcripts missing |
| Entire project operational / strict worker receipt | FAIL | Remaining runtime/account/browser/platform acceptance remains incomplete |

The diagnostic RSS contained100 items. Structural inspection found one description
with1,448,559 characters; no doctype, foreign item-link hosts or invalid publication
dates were observed in that response. Only counts/lengths are published. Raw public
response evidence is retained privately and is not copied into Git. The correction
passes a fictional500,000-character Unicode description, a second complete item,
split text/entity/CDATA at the preview boundary, and rejection above4MiB.

The native probe example deliberately requires `--live-public-feed PLATFORM`, selects
only the two closed public platforms and makes one bounded request without loading
runtime configuration, database credentials, candidate text or API keys. `--saved-rss`
reads a bounded saved response and makes no request. It is a diagnostic command, not
the recurring runtime scheduler or a replacement for its durable reservations. Do not
loop this command to evade runtime/provider cooldowns. Documentation requests through
the research browser were separate from these native/diagnostic requests; its RSS
open returned an unsupported-content-type error and was not successful parser evidence.

No database, account/profile/resume/history/policy write, browser navigation, message,
model generation, Apply, application receipt, production installation, hosted Actions,
merge or cleanup occurred in this correction. The fresh owned-tab inventory preserved
selected tabs and does not establish browser sign-in. The owner's Desktop permission
confirmation is distinct from the pending account step. Backup verification does not
restore missing Codex sidebar ownership or recover the98 absent source transcripts.

```sh
cargo test --locked --workspace
uv run --no-project --python .venv/bin/python python -m rust.scripts.run_postgres_tests
cargo test --locked --workspace --test public_discovery
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
cargo build --locked --workspace --examples
# Each following live probe performs one public request; run deliberately, not in a loop.
target/debug/examples/public_feed_probe --live-public-feed himalayas
target/debug/examples/public_feed_probe --live-public-feed we_work_remotely
target/debug/examples/public_feed_probe --saved-rss PATH_TO_PRIVATE_SAVED_RESPONSE
git diff --check
```

Timings are transport/parse observations, not a paired Python/Rust performance test.
The58ms saved parse excludes network IO. Backend3,364 passes/64 skips, frontend305
passes/build/typecheck and extension399 passes remain the earlier unchanged checkpoint;
they were not rerun for this Rust-only correction. Next implement conservative durable
ingestion without promoting previews/update times/unknown applicant counts to verified
facts, then finish the remaining browser/execution/account/service ports and actual
per-platform/install/rollback/resource/receipt acceptance. Preserve STOPPED162,
supervised4/hourly1 and every historical uncertain admission.
