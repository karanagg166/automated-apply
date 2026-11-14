use automated_apply_agents::evidence_retrieval::{Evidence, retrieve};
use serde_json::{Value, json};
#[test]
fn verified_work_evidence_differential_corpus() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/evidence-corpus.json")).unwrap();
    let evidence: Vec<Vec<Evidence>> =
        serde_json::from_value(corpus["evidence_sets"].clone()).unwrap();
    let mut errors = Vec::new();
    for (i, case) in corpus["cases"].as_array().unwrap().iter().enumerate() {
        let p = case["profile"].as_u64().unwrap() as usize;
        let e = case["evidence"].as_u64().unwrap() as usize;
        let result = retrieve(
            &corpus["profiles"][p],
            &evidence[e],
            case["question"].as_str().unwrap(),
            case["category"].as_str().unwrap(),
        )
        .unwrap();
        let result = serde_json::to_value(result).unwrap();
        if result != case["output"] {
            errors.push(format!(
                "case{i} profile{p} evidence{e} category{} question{} actual{result} expected{}",
                case["category"], case["question"], case["output"]
            ));
        }
    }
    assert!(
        errors.is_empty(),
        "{} differences:\n{}",
        errors.len(),
        errors
            .iter()
            .take(8)
            .cloned()
            .collect::<Vec<_>>()
            .join("\n")
    );
    let mut profile = corpus["profiles"][0].clone();
    profile["id"] = json!("bad");
    assert!(retrieve(&profile, &[], "question", "short_text").is_err());
    assert!(retrieve(&corpus["profiles"][0], &[], &"x".repeat(2001), "short_text").is_err());
}
