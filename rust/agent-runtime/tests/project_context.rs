use automated_apply_agents::{
    context_contract::{self, Kind},
    project_context::Snapshot,
};
use serde_json::Value;
#[test]
fn public_project_records_match_fictional_python_contracts() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/project-context-corpus.json")).unwrap();
    let mut errors = vec![];
    for (i, case) in corpus["contracts"].as_array().unwrap().iter().enumerate() {
        let kind = if case["kind"] == "configuration" {
            Kind::Configuration
        } else {
            Kind::Knowledge
        };
        let actual = context_contract::normalize(kind, case["input"].clone());
        if actual.is_ok() != (case["accepted"] == true)
            || actual.as_ref().is_ok_and(|v| v != &case["output"])
        {
            errors.push(format!("{i}: actual{actual:?} expected{case}"));
        }
    }
    assert!(
        errors.is_empty(),
        "{} differences:\n{}",
        errors.len(),
        errors.into_iter().take(6).collect::<Vec<_>>().join("\n")
    );
}
#[test]
fn current_approved_project_evidence_matches_python() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/project-context-corpus.json")).unwrap();
    let snapshots: Vec<_> = corpus["records"]
        .as_array()
        .unwrap()
        .iter()
        .map(|r| Snapshot::from_records(r.as_object().unwrap()).unwrap())
        .collect();
    let mut errors = vec![];
    for (i, case) in corpus["cases"].as_array().unwrap().iter().enumerate() {
        let actual = snapshots[case["records"].as_u64().unwrap() as usize]
            .answer_evidence(
                case["question"].as_str().unwrap(),
                case["category"].as_str().unwrap(),
            )
            .unwrap();
        if serde_json::to_value(actual).unwrap() != case["output"] {
            errors.push(format!("{i}: {case}"));
        }
    }
    assert!(
        errors.is_empty(),
        "{} differences:\n{}",
        errors.len(),
        errors.into_iter().take(6).collect::<Vec<_>>().join("\n")
    );
}
