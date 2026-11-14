use automated_apply_agents::answer_reuse;
use serde_json::{Value, json};
#[test]
fn supported_reuse_intents_raw_draft_hashes_and_strict_owner_review_match_legacy() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/answer-reuse-corpus.json")).unwrap();
    let mut errors = vec![];
    for (i, case) in corpus["intents"].as_array().unwrap().iter().enumerate() {
        let result = answer_reuse::semantic_intent(
            case["question"].as_str().unwrap(),
            case["category"].as_str().unwrap(),
            &corpus["profiles"][case["profile"].as_u64().unwrap() as usize],
        )
        .unwrap();
        if json!(result) != case["output"] {
            errors.push(format!(
                "intent{i} {} expected{} actual{}",
                case["question"],
                case["output"],
                json!(result)
            ));
        }
    }
    for (i, case) in corpus["drafts"].as_array().unwrap().iter().enumerate() {
        if answer_reuse::draft_digest(&case["draft"]).unwrap() != case["digest"].as_str().unwrap() {
            errors.push(format!("draft{i}"));
        }
    }
    for (i, case) in corpus["approvals"].as_array().unwrap().iter().enumerate() {
        let result = answer_reuse::approval_input(case["input"].clone());
        if result.is_ok()!=case["accepted"].as_bool().unwrap() || result.as_ref().is_ok_and(|r|json!({"expected_profile_version":r.expected_profile_version,"scope":r.scope,"confirm_reviewed_answer":r.confirmed})!=case["output"]) {errors.push(format!("approval{i} {}",case["input"]));}
    }
    assert!(
        errors.is_empty(),
        "{} differences:\n{}",
        errors.len(),
        errors.into_iter().take(10).collect::<Vec<_>>().join("\n")
    );
}
