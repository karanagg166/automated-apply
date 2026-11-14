use automated_apply_agents::question_classifier::{canonical, classify};
use serde_json::{Value, json};
#[test]
fn conservative_question_routing_and_closed_paraphrase_differential_corpus() {
    let cases: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/question-corpus.json")).unwrap();
    let mut errors = Vec::new();
    for (i, case) in cases.iter().enumerate() {
        let question = case["question"].as_str().unwrap();
        let output = serde_json::to_value(classify(question)).unwrap();
        if output != case["output"] || json!(canonical(question)) != case["canonical"] {
            errors.push(format!(
                "case{i} question{question:?} actual{output} expected{}",
                case["output"]
            ));
        }
    }
    assert!(
        errors.is_empty(),
        "{} differences:\n{}",
        errors.len(),
        errors.join("\n")
    );
}
