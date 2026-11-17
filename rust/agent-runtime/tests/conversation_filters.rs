use automated_apply_agents::conversation::{filters, intent, preferences};
use chrono::{DateTime, Utc};
use serde_json::{Value, json};

fn corpus() -> Value {
    serde_json::from_str(include_str!("fixtures/conversation-filters.json")).unwrap()
}

#[test]
fn cached_filters_match_frozen_legacy_results() {
    let data = corpus();
    let now: DateTime<Utc> = data["now"].as_str().unwrap().parse().unwrap();
    let intents: Vec<_> = data["intents"]
        .as_array()
        .unwrap()
        .iter()
        .map(|raw| {
            let mut raw = raw.clone();
            raw["category"] = json!("FIND_JOBS");
            intent::normalize(raw).unwrap()
        })
        .collect();
    let cases = data["cases"].as_array().unwrap();
    assert_eq!(cases.len(), 1620);
    for (index, row) in cases.iter().enumerate() {
        let job = &data["jobs"][row["job"].as_u64().unwrap() as usize];
        let preferences = &data["preferences"][row["preferences"].as_u64().unwrap() as usize];
        let intent = &intents[row["intent"].as_u64().unwrap() as usize];
        assert_eq!(
            filters::matches(job, &data["company"], intent, preferences, now),
            row["output"].as_bool().unwrap(),
            "fixture case {index}: {row}"
        );
    }
}

#[test]
fn preferences_preserve_validation_and_defaults() {
    let data = corpus();
    for row in data["preference_cases"].as_array().unwrap() {
        let result = preferences::normalize(row["input"].clone());
        assert_eq!(result.is_ok(), row["accepted"].as_bool().unwrap(), "{row}");
        if let Ok(value) = result {
            assert_eq!(value, row["output"]);
        }
    }
}
