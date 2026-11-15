use automated_apply_agents::packet_contract;
use serde_json::Value;
#[test]
fn packet_preparation_request_contracts_match_python_without_accepting_trust_metadata() {
    let cases: Value =
        serde_json::from_str(include_str!("fixtures/packet-contract-corpus.json")).unwrap();
    let mut failures = vec![];
    for (i, case) in cases.as_array().unwrap().iter().enumerate() {
        let actual = packet_contract::normalize(case["input"].clone(), case["kind"] == "create")
            .map(|v| serde_json::to_value(v).unwrap());
        if actual.is_ok() != (case["accepted"] == true)
            || actual.as_ref().is_ok_and(|v| v != &case["output"])
        {
            failures.push(format!("{i}: actual{actual:?} expected{case}"));
        }
    }
    assert!(
        failures.is_empty(),
        "{} differences:\n{}",
        failures.len(),
        failures.into_iter().take(6).collect::<Vec<_>>().join("\n")
    );
}
