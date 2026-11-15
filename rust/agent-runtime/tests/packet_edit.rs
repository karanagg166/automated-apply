use automated_apply_agents::{
    packet_archive,
    packet_mutation_contract::{self, Kind},
};
use serde_json::{Value, json};
#[test]
fn owner_mutation_inputs_match_actual_closed_python_dtos() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/packet-edit-corpus.json")).unwrap();
    for case in corpus["contracts"].as_array().unwrap() {
        let kind = match case["kind"].as_str().unwrap() {
            "refresh" => Kind::Refresh,
            "questions" => Kind::Questions,
            "answer" => Kind::Answer,
            _ => panic!("kind"),
        };
        let actual = packet_mutation_contract::normalize(kind, case["input"].clone());
        assert_eq!(actual.is_ok(), case["accepted"] == true, "{case}");
        if let Ok(actual) = actual {
            assert_eq!(json!(actual), case["output"], "{case}");
            assert_eq!(
                actual.explicit_resume(),
                case["explicit_resume"] == true,
                "{case}"
            );
        }
    }
}
#[test]
fn revision_archives_match_actual_python_expression_and_compact_keys() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/packet-edit-corpus.json")).unwrap();
    let now = chrono::DateTime::parse_from_rfc3339(corpus["archive"]["now"].as_str().unwrap())
        .unwrap()
        .with_timezone(&chrono::Utc);
    for case in corpus["archive"]["cases"].as_array().unwrap() {
        assert_eq!(
            packet_archive::record(&case["packet"], case["fields"].as_array().unwrap(), now)
                .unwrap(),
            case["output"]
        );
        let key = packet_archive::key(
            case["packet"]["id"].as_str().unwrap().parse().unwrap(),
            case["packet"]["revision"].as_i64().unwrap() as i32,
        )
        .unwrap();
        assert_eq!(json!(key), case["key"]);
        assert!(key.len() <= 50);
    }
}
