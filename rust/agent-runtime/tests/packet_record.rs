use automated_apply_agents::packet_record::{self, Kind};
use serde_json::Value;
#[test]
fn expiry_requires_an_explicit_timezone_and_keeps_the_exact_microsecond() {
    use serde_json::json;
    assert_eq!(packet_record::expiry(&Value::Null).unwrap(), None);
    assert!(packet_record::expiry(&json!("2026-11-15T12:00:00")).is_err());
    assert!(packet_record::expiry(&json!("2026-11-15")).is_err());
    let deadline = packet_record::expiry(&json!("2026-11-15T17:30:00.000001+05:30"))
        .unwrap()
        .unwrap();
    assert_eq!(deadline.to_rfc3339(), "2026-11-15T12:00:00.000001+00:00");
}
#[test]
fn stored_packet_dto_projection_matches_actual_python_models_and_effective_answer_rules() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/packet-record-corpus.json")).unwrap();
    let mut failures = vec![];
    for (i, case) in corpus.as_array().unwrap().iter().enumerate() {
        let kind = match case["kind"].as_str().unwrap() {
            "snapshot" => Kind::Snapshot,
            "field" => Kind::Field,
            "event" => Kind::Event,
            _ => panic!("fixture kind"),
        };
        let actual = packet_record::normalize(kind, case["input"].clone());
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
