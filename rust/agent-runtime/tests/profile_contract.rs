use automated_apply_agents::profile_contract::{Operation, normalize, parse_version};
use serde_json::Value;
#[test]
fn fictional_profile_differential_corpus() {
    let cases: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/profile-corpus.json")).unwrap();
    let mut errors = Vec::new();
    for (index, case) in cases.iter().enumerate() {
        let operation = if case["operation"] == "create" {
            Operation::Create
        } else {
            Operation::Update
        };
        let result = if case["operation"] == "record" {
            automated_apply_agents::profile_contract::normalize_record(case["input"].clone())
        } else {
            normalize(operation, case["input"].clone())
        };
        if result.is_ok() != case["accepted"].as_bool().unwrap()
            || result.as_ref().is_ok_and(|value| value != &case["value"])
        {
            errors.push(format!(
                "case {index}: expected accepted {} got {:?} input {}",
                case["accepted"],
                result.is_ok(),
                case["input"]
            ));
        }
    }
    assert!(
        errors.is_empty(),
        "{} of {} fictional comparisons failed:\n{}",
        errors.len(),
        cases.len(),
        errors.join("\n")
    );
}
#[test]
fn strong_etags_never_accept_wildcards_weak_tags_or_overflow() {
    assert_eq!(parse_version(Some("\"001\""), true).unwrap(), Some(1));
    assert_eq!(
        parse_version(Some("\"2147483646\""), true).unwrap(),
        Some(2147483646)
    );
    assert_eq!(parse_version(None, false).unwrap(), None);
    for input in [
        "*",
        "1",
        "W/\"1\"",
        "\"0\"",
        "\"-1\"",
        "\"2147483647\"",
        "\"１\"",
        "\"1\",\"2\"",
    ] {
        assert!(parse_version(Some(input), false).is_err());
    }
    assert!(parse_version(None, true).is_err());
}

#[test]
fn complete_serialized_bound_includes_defaults_and_nested_project_fields() {
    use serde_json::json;
    let make = |count| json!({"full_name":"Fictional Person","email":"fictional@example.com","projects":(0..count).map(|i|json!({"name":format!("Fictional project {i}"),"description":"x".repeat(4000)})).collect::<Vec<_>>()});
    let accepted = normalize(Operation::Create, make(15)).unwrap();
    // Public Python DTO oracle: same compact UTF-8 serialized length, including defaults.
    assert_eq!(serde_json::to_vec(&accepted).unwrap().len(), 64366);
    assert!(normalize(Operation::Create, make(16)).is_err());
    assert!(normalize(Operation::Update, json!({"projects":make(16)["projects"]})).is_err());
}
#[test]
fn merged_partial_updates_preserve_facts_and_validate_the_complete_result() {
    use automated_apply_agents::profile_contract::merge_update;
    use serde_json::json;
    let current = json!({"full_name":"Fictional Person","email":"fictional@example.com","verified_skills":["Rust"],"preferences":{"target_titles":["Engineer"],"remote_preference":"remote","notice_period_days":30}});
    let result = merge_update(
        current.clone(),
        json!({"preferences":{"notice_period_days":0}}),
    )
    .unwrap();
    assert_eq!(result["verified_skills"], json!(["Rust"]));
    assert_eq!(result["preferences"]["target_titles"], json!(["Engineer"]));
    assert_eq!(result["preferences"]["remote_preference"], "remote");
    assert_eq!(result["preferences"]["notice_period_days"], 0);
    let country = json!({"country_code":"IN","country_name":"India","authorized_to_work":true});
    let patch = json!({"preferences":{"work_authorizations":[country.clone(),country]}});
    // The legacy partial DTO permits this; complete repository validation rejects it.
    assert!(normalize(Operation::Update, patch.clone()).is_ok());
    assert!(merge_update(current.clone(), patch).is_err());
    assert!(merge_update(current, json!({"verified_skills":null})).is_err());
}
#[test]
fn live_placeholder_fence_does_not_invent_replacement_facts() {
    use automated_apply_agents::profile_contract::reject_placeholders;
    use serde_json::json;
    for value in [
        "fictional",
        "PLACEHOLDER",
        "YOUR_name",
        "a@example.com",
        "x.example",
        "Alex Example",
        "test@somewhere.dev",
        "TODO",
    ] {
        assert!(reject_placeholders(&json!({"summary":value})).is_err());
    }
    assert!(
        reject_placeholders(
            &json!({"verified_skills":["Rust"],"summary":"Evidence supplied by the owner"})
        )
        .is_ok()
    );
    for value in [
        "fİctİonal",
        "fıctıonal",
        "TODO\u{301}",
        "TODO\u{11f02}",
        "x.example\u{301}",
    ] {
        assert!(reject_placeholders(&json!({"summary":value})).is_err());
    }
    for value in ["TODOα", "TODO²", "TODO_", "x.example_"] {
        assert!(reject_placeholders(&json!({"summary":value})).is_ok());
    }
}
