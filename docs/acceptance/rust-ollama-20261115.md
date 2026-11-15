# Rust local structured drafts — 2026-11-15

Implementation: [`06f9b4c7abe2e10fb6198886747ac5e1d2efcfb6`](https://github.com/karanagg166/automated-apply/commit/06f9b4c7abe2e10fb6198886747ac5e1d2efcfb6),
branch `feat/rust-agent-runtime`, [PR #50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling`. This is a migration milestone, not whole-project completion.

`LLM_PROVIDER=ollama` and `OLLAMA_ENABLED=true` explicitly select the local structured
draft path. Rust uses the existing `owner_preferences` key `ai:ollama:YYYY-MM`, preserving
consumed requests, cooldowns and unknown JSON fields. Row locks prevent concurrent clients
from exceeding the configured monthly allowance (maximum 1,000). Rejected reservations
finish rollback explicitly. A failed transport consumes its committed reservation.
Other provider ledgers and application authority are unaffected.

The production destination is fixed to numeric loopback port 11434, with no proxy,
redirect, hidden retry, model install/pull or remote fallback. Only metadata is sent until
`/api/status` reports cloud disabled and `/api/show` proves a nonempty local model without
remote routing. The shared generation permit rejects overlapping runtime calls before
quota reservation. Metadata and generation share one transport deadline; ledger COMMIT
is not cancelled by that deadline. Existing grounding and fact-version rechecks precede
saving a reviewable draft. No draft is an application approval.

Requests cap the serialized body at 5,000 bytes and ask for two threads, 2,048 context
tokens, at most 256 output tokens, deterministic sampling and immediate unload after use.
Responses are bounded to 128KiB, identity encoding and one complete, exact-model result.
The schema permits grounded answer data only. These are requested daemon limits, not
measured CPU/RSS/GPU guarantees; incomplete structured answers fail rather than continue.
Other daemon clients require their own single-concurrency configuration.

| Check | Result | Evidence and limits |
| --- | --- | --- |
| Standard Rust workspace | PASS | Fresh 129 passed,0 failed;131 PG tests intentionally ignored here |
| Full disposable PostgreSQL suite | PASS | Fresh 131 passed,0 failed,32.97s; includes ten new Ollama tests |
| Total distinct Rust tests | PASS | 260 = 129 standard + 131 PG; focused reruns are not counted again |
| Quota preservation and concurrency | PASS | Existing counter/custom field retained; independent clients cannot overspend; shared runtime permit blocks overlap |
| Locality and bounded transport | PASS | Fictional HTTP server rejects cloud/missing metadata, remote routing, redirects, encoding, oversize and timeout; no private prompt before locality |
| Grounding/context/output gates | PASS | Tool/incomplete/wrong-model/bad-usage/unsupported claims and stale profile cannot save drafts |
| Cooldown/failure accounting | PASS |429 persists 60-second cooldown; transport failures retain consumed request |
| Clippy and formatting | PASS | Workspace/all-target warnings denied; Cargo formatting and diff checks |
| Actual Mac/browser state | PASS / limited | Separately verified inactive Brave permission readback: Naukri allowed, unrelated site denied; authenticated queue STOP162. This is not provider/application acceptance |
| Real Ollama generation | NOT TESTED | No daemon launched, model downloaded, candidate prompt sent or real inference benchmark |
| Production Rust installation/cutover | NOT TESTED | Legacy API/execution remain installed; this provider is development source |
| Complete Rust migration and application automation | BLOCKED / incomplete | Remaining service/API/browser/application/Gmail/Telegram/CLI ports, account/receipt/resource acceptance and owner review remain |

Initial focused validation passed 7/8: the rejected accomplishment used the existing
specific code `unsupported_accomplishment`, while the new test expected
`unsupported_claim`. The expectation was corrected; ten focused tests then passed in 3.31s.
Clippy caught one collapsible conditional, corrected before the final passing run.
No unresolved failure remains in this milestone's tested scope.

Standard test-body times sum to 4.93s across binaries; full PG test-body time is 32.97s.
These are unpaired fixture timings, not a Rust-versus-Python speed comparison.
No dependency or lockfile addition was needed. New provider/test source totals 30,238 bytes;
all development artifacts stay in the canonical repository. No installed release or
private runtime data was removed. Raw logs remain ignored and private.

Reproduce from the canonical checkout:

```sh
cargo test --locked --workspace
uv run --no-project python rust/scripts/run_postgres_tests.py
uv run --no-project python rust/scripts/run_postgres_tests.py --filter ollama_
cargo clippy --locked --workspace --all-targets -- -D warnings
cargo fmt --all -- --check
git diff --check
```

No hosted Actions were dispatched. The actual model/library contract was checked against
[Ollama's generation API](https://docs.ollama.com/api/generate),
[the official local FAQ](https://docs.ollama.com/faq) and
[the server's status/local-routing implementation](https://github.com/ollama/ollama/blob/main/server/routes.go).
Real-daemon compatibility remains unaccepted. Older daemons without locality proof fail
closed. The separate legacy authorized rearranger, local-only fallback and AGY provider
still need ports; this milestone implements the existing optional structured draft path.

Next: continue inactive Brave account setup and Naukri supervised acceptance under the
existing caps/quarantines, finish the remaining Rust ports, then validate STOP installation,
rollback, whole-system resources and actual worker receipts before removing Python or merging.
