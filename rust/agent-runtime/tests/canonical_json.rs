use automated_apply_agents::python_json::{digest, serialize};
use serde_json::Value;
#[test]
fn canonical_unicode_float_and_approval_digest_differential_corpus() {
    let cases: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/canonical-json-corpus.json")).unwrap();
    let mut errors = Vec::new();
    for (i, case) in cases.iter().enumerate() {
        let input = &case["input"];
        let compact = serialize(input, true, true);
        if compact != case["compact"]
            || serialize(input, false, true) != case["spaced"]
            || serialize(input, false, false) != case["utf8"]
            || digest(input) != case["sha256"]
        {
            errors.push(format!("case{i}: got{compact} expected{}", case["compact"]));
        }
    }
    assert!(
        errors.is_empty(),
        "{} differences:\n{}",
        errors.len(),
        errors
            .iter()
            .take(12)
            .cloned()
            .collect::<Vec<_>>()
            .join("\n")
    );
}
