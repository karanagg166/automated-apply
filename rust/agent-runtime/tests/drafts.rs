use automated_apply_agents::answer_store::{Review, record};
use serde_json::Value;
#[test]
fn postgres_shaped_saved_draft_and_owner_review_differential_corpus() {
    let corpus: Value = serde_json::from_str(include_str!("fixtures/draft-corpus.json")).unwrap();
    for (i, case) in corpus["records"].as_array().unwrap().iter().enumerate() {
        let result = record(
            case["row"].clone(),
            case["profile_version"].as_i64().unwrap() as i32,
        );
        assert_eq!(result.is_ok(), case["accepted"], "record{i}");
        if let Ok(value) = result {
            assert_eq!(value, case["output"], "record{i}");
        }
    }
    for (i, case) in corpus["reviews"].as_array().unwrap().iter().enumerate() {
        let result = serde_json::from_value::<Review>(case["input"].clone());
        assert_eq!(result.is_ok(), case["accepted"], "review{i}");
    }
}
