use automated_apply_agents::{packet_notice, packet_review};
use serde_json::{Value, json};
#[test]
fn owner_review_inputs_match_actual_closed_python_contract() {
    let data: Value =
        serde_json::from_str(include_str!("fixtures/packet-review-corpus.json")).unwrap();
    for case in data["contracts"].as_array().unwrap() {
        let result = packet_review::request(case["input"].clone());
        assert_eq!(result.is_ok(), case["accepted"] == true, "{case}");
        if let Ok(result) = result {
            assert_eq!(json!(result), case["output"], "{case}");
        }
    }
}
#[test]
fn packet_notice_gates_content_dedup_keys_and_legacy_telegram_identity_match_actual_function() {
    let data: Value =
        serde_json::from_str(include_str!("fixtures/packet-review-corpus.json")).unwrap();
    let now = chrono::DateTime::parse_from_rfc3339(data["notices"]["now"].as_str().unwrap())
        .unwrap()
        .with_timezone(&chrono::Utc);
    for case in data["notices"]["cases"].as_array().unwrap() {
        let input = &case["input"];
        let fallback = json!({"revision":0,"state":"STOPPED"});
        let automation = if input["automation"].is_null() {
            &fallback
        } else {
            &input["automation"]
        };
        let actual = packet_notice::propose(
            &input["packet"],
            (!input["execution"].is_null()).then_some(&input["execution"]),
            automation,
            (!input["configuration"].is_null()).then_some(&input["configuration"]),
            &input["preferences"],
            input["telegram_available"] == true,
            now,
        )
        .unwrap();
        assert_eq!(json!(actual), case["output"], "{input}");
    }
}
