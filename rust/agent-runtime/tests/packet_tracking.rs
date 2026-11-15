use automated_apply_agents::packet_tracking_contract;
use serde_json::{Value, json};

#[test]
fn manual_reports_and_tracking_match_actual_closed_owner_contracts() {
    let cases: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/packet-tracking-corpus.json")).unwrap();
    for case in cases {
        let result = match case["kind"].as_str().unwrap() {
            "submission" => {
                packet_tracking_contract::submission(case["input"].clone()).map(|v| json!(v))
            }
            "tracking" => {
                packet_tracking_contract::tracking(case["input"].clone()).map(|v| json!(v))
            }
            _ => unreachable!(),
        };
        assert_eq!(result.is_ok(), case["accepted"] == true, "{case}");
        if let Ok(result) = result {
            assert_eq!(result, case["output"], "{case}");
        }
    }
}
