use automated_apply_agents::resources::{Resource, assess_profile, public_https, select_resume};
use serde_json::{Value, json};
#[test]
fn fictional_public_url_resume_and_readiness_differential_corpus() {
    let corpus: Value = serde_json::from_str(include_str!("fixtures/resume-corpus.json")).unwrap();
    let mut errors = Vec::new();
    for (i, case) in corpus["urls"].as_array().unwrap().iter().enumerate() {
        let actual = case["input"].as_str().and_then(public_https);
        if json!(actual) != case["output"] {
            errors.push(format!("url {i}: {} != {}", json!(actual), case["output"]));
        }
    }
    for (i, case) in corpus["selections"].as_array().unwrap().iter().enumerate() {
        let resources: Vec<Resource> = serde_json::from_value(case["resources"].clone()).unwrap();
        let selected = case["selected_id"].as_str().map(|s| s.parse().unwrap());
        let actual = serde_json::to_value(select_resume(&resources, selected).unwrap()).unwrap();
        if actual != case["output"] {
            errors.push(format!("selection {i}: different response fields"));
        }
    }
    for (i, case) in corpus["readiness"].as_array().unwrap().iter().enumerate() {
        let resources: Vec<Resource> = serde_json::from_value(case["resources"].clone()).unwrap();
        let actual = assess_profile(
            (!case["profile"].is_null()).then(|| case["profile"].clone()),
            &resources,
            case["live"].as_bool().unwrap(),
        );
        if let Some(expected) = case.get("output") {
            if actual.as_ref().ok() != Some(expected) {
                errors.push(format!("readiness {i}: {actual:?} != {expected}"));
            }
        } else if actual.is_ok() {
            errors.push(format!("readiness {i}: unexpected acceptance"));
        }
    }
    assert!(
        errors.is_empty(),
        "{} differences:\n{}",
        errors.len(),
        errors.join("\n")
    );
}
