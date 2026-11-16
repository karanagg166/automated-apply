# Native command serialization source — NOT TESTED

Branch `feat/rust-agent-runtime`. Main implementation
[`91cc44a7d011fc12009c7e2fcbefb6fa9c9a3aef`](https://github.com/karanagg166/automated-apply/commit/91cc44a7d011fc12009c7e2fcbefb6fa9c9a3aef),
ordering follow-up
[`4c2d2826500a4eeb7268bdfb3d44f6c9c87830c0`](https://github.com/karanagg166/automated-apply/commit/4c2d2826500a4eeb7268bdfb3d44f6c9c87830c0).
[PR50](https://github.com/karanagg166/automated-apply/pull/50), base `chore/uv-python-tooling`.

Source review found that hashing the generic JSON value omitted legacy defaults, reordered
model properties and hashed the real secret string rather than Pydantic's masked value.
That would misidentify a saved legacy nonce after handover. The new parser fills frozen
DTO defaults, normalizes UUID/public URL/date/number values and uses declaration order
for11 actual source model layouts. An independent key-order tree retains opaque nested
dictionary order from the original request bytes without changing global serde behavior.
Audit storage receives only the resulting digest; authentication still uses the actual
secret. No command identity, Codex account identity or historical saved nonce is rewritten.

The source includes the corresponding model checks for bounded provider facts/options,
profile observation keys and coherent intent fields. Existing frozen JSON-schema wire
restrictions remain; this is not a claim to accept every coercion Python might permit.
The shape exporter reads source AST only and is scheduled as a final-gate drift check.
One source fixture correction replaces invalid short semantic keys with valid64-character
keys. No admission, quota, browser or provider capability is added.

| Gate | Status | Exact evidence / limitation |
| --- | --- | --- |
| Source/layout files recorded | PASS | Commits above;11 frozen model layouts read from actual Python declarations |
| Current compilation/Clippy | NOT TESTED | Intentionally deferred under the owner's final-test instruction |
| New serialization comparison | NOT TESTED | 1 new standard test contains18 positive actual-Python hash cases;0 executed |
| New rejection scenarios | NOT TESTED | 1 new standard test contains8 rejection cases;0 executed |
| Current complete suites | NOT TESTED | No current source test counts; historical455 Rust passes at9c4ace5 remain historical only |
| Actual installed/native browser | NOT TESTED | No installed file, browser/tab/window, account or profile change |
| Live application/receipt | NOT TESTED | No real employer action or strict worker receipt |
| Timing/RSS comparison | NOT TESTED | No new measurement; no speed claim |
| Full project completion | NOT TESTED | Execution/kernel, remaining ports, final gate, cutover and live acceptance remain |

The Python oracle file reads actual class bodies and runs them in an isolated namespace
when eventually invoked. It is written but has not been executed here. Expected hashes,
compilation and runtime parity must therefore be established by the final gate, not inferred
from this source report. Only source inspection, AST layout extraction and formatting
occurred. There are no new runtime logs/failure codes to publish.

After all remaining source is complete, run `uv run --no-project python
scripts/run_acceptance.py --run`. The new layout-only stage is
`uv run --no-project python -m rust.scripts.export_native_field_order --check`; the new
standard test joins `cargo test --locked --workspace`. These commands were not run at this
checkpoint. Current rough engineering estimate remains58% complete/42% remaining.
