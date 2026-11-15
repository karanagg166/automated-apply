use automated_apply_agents::notification_preferences;
use serde_json::Value;
#[test]
fn notification_settings_match_actual_python_model_and_current_system_iana_keys() {
    let corpus: Value = serde_json::from_str(include_str!(
        "fixtures/notification-preferences-corpus.json"
    ))
    .unwrap();
    let mut failures = vec![];
    for case in corpus["cases"].as_array().unwrap() {
        let actual = notification_preferences::normalize(case["input"].clone());
        if actual.is_ok() != (case["accepted"] == true)
            || actual.as_ref().is_ok_and(|v| v != &case["output"])
        {
            failures.push(format!(
                "input{} actual{actual:?} expected{}",
                case["input"], case["output"]
            ));
        }
    }
    assert!(
        failures.is_empty(),
        "{} differences:\n{}",
        failures.len(),
        failures.into_iter().take(10).collect::<Vec<_>>().join("\n")
    );
}
