# Packet readiness core and worker history — 2026-11-15

Implementation [`367a70dce545b215d1197008bb44f18eadc51fe2`](https://github.com/karanagg166/automated-apply/commit/367a70dce545b215d1197008bb44f18eadc51fe2),
branch `feat/rust-agent-runtime`, [PR #50](https://github.com/karanagg166/automated-apply/pull/50),
base `chore/uv-python-tooling`.

The pure legacy packet-readiness calculation is now implemented in Rust over typed,
validated internal projections. It preserves state precedence, warning/blocker ordering,
missing facts, destination consistency, stale evidence, resume selection, expiry boundaries,
file-upload handling and exact owner review requirements. Calculation time is injected;
eventual callers must sample a fresh cutoff. Its result conveys no action authority.
Full packet DTO/context/persistence/API integration is the next slice, not completed here.

An independent source audit also found a real history-reader defect: PostgreSQL workers
write `local_worker` events, but the existing API DTO permitted only owner_rest/system.
The DTO and regenerated TypeScript contract now explicitly include local_worker. A full
HTTP regression creates a fictional packet, records system/worker events, reads all three
origins and confirms arbitrary origins remain invalid. This source fix is not installed
in the immutable legacy runtime yet.

| Check | Result | Evidence and limits |
| --- | --- | --- |
| Rust workspace | PASS | Fresh 130 passed,0 failed;140 PG tests ignored here |
| Pure readiness parity | PASS | 3,584 comparisons against actual frozen-clock Python function, within one Rust test; 29 deduplicated results in a 51,833-byte fixture |
| Expiry/precedence | PASS | All eight flags, 14 field sets, exact/future/past expiry, multiple blockers and review-exempt answers; manual upload remains a separate step |
| Independent read-only review | PASS | No discrepancy in pure readiness scope; fresh-time requirement recorded |
| Oracle reproducibility | PASS | Exporter `--check`; fictional data only; temporary module clock restored; no owner config/DB/network |
| Existing PostgreSQL baseline | PASS / retained | 140 previously passed at 2195b4c in 34.92s; no DB/runtime path changed by this pure module, so not rerun |
| Combined Rust evidence | PASS / qualified | 270 = 130 fresh standard + 140 unchanged prior PG; not 270 newly executed tests |
| Worker-history API regression | PASS | Fresh 30 Python API tests passed in 2.55s, including one new in-process ASGI/SQLite fixture test |
| OpenAPI/frontend | PASS | Regenerated API declaration differs only by the specific origin union; TypeScript typecheck and full frontend format check pass |
| Ruff/Clippy/format/diff | PASS | E9,F,I; workspace all-target warnings denied; Cargo formatting/whitespace |
| Production history fix | NOT TESTED | Source only; immutable legacy 8e985c9 unchanged |
| Packet endpoints/persistence/approvals | NOT TESTED | Pure core is not wired into the Rust packet service yet; no full packet-API parity claim |
| Live accounts/applications | BLOCKED / incomplete | Approved Chrome profile remains offline; physical browser step and strict receipts remain outstanding |

Standard Rust test-body times sum to 5.00s; Clippy took 6.61s. These are unpaired component
fixture measurements, not whole-project performance/resource acceptance. No new library,
pool, production schema/data change, browser action, model request, release install or
hosted Actions. Raw logs remain ignored/private under canonical `.local/`.

```sh
uv run --no-project --python .venv/bin/python python -m rust.scripts.export_packet_readiness --check
cargo test --locked --workspace
cargo clippy --locked --workspace --all-targets -- -D warnings
uv run --no-project --python .venv/bin/python python -m pytest backend/tests/test_application_packet_api.py -q
uv run --no-project ruff check --isolated --select E9,F,I backend/app/schemas/applications.py backend/tests/test_application_packet_api.py rust/scripts/export_packet_readiness.py
uv run --no-project --python .venv/bin/python python backend/scripts/export_openapi.py
pnpm -C frontend api:types
pnpm -C frontend typecheck
pnpm -C frontend format:check
cargo fmt --all -- --check
git diff --check
```

The [next seven-route slice](../plans/application-packet-rust-slice.md) records exact
creation/replay, material context digests, shared locks, immutable history and transaction
requirements. Reuse existing Rust resume selection and matching. Do not substitute an
answer-generation stamp for packet freshness or partially commit packet work through the
public answer generator. Full Rust migration, installed/live/resource/receipt acceptance
and owner review remain required before completion or merge.
