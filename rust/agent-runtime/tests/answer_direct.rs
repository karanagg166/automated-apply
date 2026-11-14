use automated_apply_agents::{answer_contract, answer_direct, resources::Resource};
use serde_json::Value;
use std::collections::BTreeMap;
#[test]
fn direct_service_answers_match_original_branches_without_inference_or_database() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/direct-answer-corpus.json")).unwrap();
    let defaults: BTreeMap<String, String> =
        serde_json::from_value(corpus["defaults"].clone()).unwrap();
    let groups: Vec<Vec<Resource>> = serde_json::from_value(corpus["resources"].clone()).unwrap();
    let mut errors = vec![];
    for (index, case) in corpus["cases"].as_array().unwrap().iter().enumerate() {
        let request = answer_contract::normalize(case["request"].clone()).unwrap();
        let result = answer_direct::resolve(
            &corpus["profiles"][case["profile"].as_u64().unwrap() as usize],
            &groups[case["resources"].as_u64().unwrap() as usize],
            &defaults,
            &request,
        );
        if !result
            .as_ref()
            .is_ok_and(|v| serde_json::to_value(v).unwrap() == case["output"])
        {
            errors.push(format!(
                "case{index} {} expected{} actual{}",
                request.question,
                case["output"],
                result
                    .as_ref()
                    .map(|v| serde_json::to_value(v).unwrap())
                    .unwrap_or_else(|e| serde_json::json!(e.0))
            ));
        }
    }
    assert!(
        errors.is_empty(),
        "{} differences:\n{}",
        errors.len(),
        errors.into_iter().take(8).collect::<Vec<_>>().join("\n")
    );
}
