use automated_apply_agents::{answer_contract, personal_facts};
use serde_json::{Value, json};
#[test]
fn exact_saved_facts_and_bounded_generation_request_differential_corpus() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/factual-answer-corpus.json")).unwrap();
    let mut errors = Vec::new();
    for (i, case) in corpus["facts"].as_array().unwrap().iter().enumerate() {
        let index = case["preferences"].as_u64().unwrap() as usize;
        let profile = json!({"preferences":corpus["preferences"][index]});
        let result = personal_facts::resolve(
            &profile,
            case["question"].as_str().unwrap(),
            case["category"].as_str().unwrap(),
        );
        if !result.as_ref().is_ok_and(|r| json!(r) == case["output"]) {
            errors.push(format!(
                "fact{i} question{} result{result:?} expected{}",
                case["question"], case["output"]
            ));
        }
    }
    for (i, case) in corpus["requests"].as_array().unwrap().iter().enumerate() {
        let result = answer_contract::normalize(case["input"].clone());
        if result.is_ok() != case["accepted"].as_bool().unwrap()
            || result.as_ref().is_ok_and(|v| json!(v) != case["output"])
        {
            errors.push(format!(
                "request{i} input{} expected{}",
                case["input"], case["output"]
            ));
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
