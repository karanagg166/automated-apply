use automated_apply_agents::{
    packet_readiness::Flags,
    packet_record::{self, Kind},
    packet_service,
};
use serde_json::{Value, json};
#[test]
fn legacy_service_readiness_overrides_preserve_closed_unknown_verified_and_expired_precedence() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/packet-read-corpus.json")).unwrap();
    let snapshot = packet_record::normalize(Kind::Snapshot, corpus["snapshot"].clone()).unwrap();
    let fields = corpus["fields"]
        .as_array()
        .unwrap()
        .iter()
        .map(|f| packet_record::normalize(Kind::Field, f.clone()).unwrap())
        .collect::<Vec<_>>();
    let now = chrono::DateTime::parse_from_rfc3339(corpus["now"].as_str().unwrap())
        .unwrap()
        .with_timezone(&chrono::Utc);
    for case in corpus["cases"].as_array().unwrap() {
        let bits = case["flags"].as_u64().unwrap();
        let actual = packet_service::readiness(
            &snapshot,
            &[fields[case["field"].as_u64().unwrap() as usize].clone()],
            Flags {
                stale: bits & 1 != 0,
                approved: bits & 2 != 0,
                submitted: bits & 4 != 0,
            },
            case["lifecycle"].as_str().unwrap(),
            now,
        )
        .unwrap();
        assert_eq!(json!(actual), case["readiness"], "{case}");
    }
}
