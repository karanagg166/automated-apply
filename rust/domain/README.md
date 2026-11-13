# Deterministic matching domain

Rust ports of `ApplicationAssistant.calculate_match`, `skill_key`, `title_key` and
`JobDiscoveryMatcher.match`, used by the new saved-evidence PostgreSQL tools. Matching
requires verified skills and explicit preferences; it does not infer experience or grant
application authority. Unknown stage/headcount/salary/experience stay explicit. A match
score is not job eligibility, permission to apply or evidence of a receipt.

This library has no Python runtime, HTTP client, AI SDK or database dependency. Compiled
regular expressions and a bounded skill-pattern cache are reused by the persistent worker.
Frozen public HTML5/Unicode tables preserve the existing Python3.11 text contract, including
entity references, equivalent published skill spellings and contextual lowercase behavior.
Their provenance and notices are under `data/`.

```sh
cargo test --locked -p automated-apply-domain
cargo build --locked --release -p automated-apply-domain --example match_contract
uv run --no-project --python .venv/bin/python python -m rust.scripts.matching_parity
uv run --no-project --python .venv/bin/python python -m rust.scripts.export_html_contract --check
uv run --no-project --python .venv/bin/python python -m rust.scripts.benchmark_matching
```

The differential corpus has1,300fictional cases and checks both scoring layers, all skill
lists/factors/unknowns/exclusions and explanation strings. It is not exhaustive over every
possible source input or Unicode context. The benchmark separates warm calculation from
one-shot parsing/validation/startup, which have different costs. No live accounts, providers,
browsers, owner data or production database are used.
