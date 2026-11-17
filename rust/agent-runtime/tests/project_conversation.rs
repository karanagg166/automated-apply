use automated_apply_agents::project_context::Snapshot;
use serde_json::Value;
fn corpus() -> Value {
    serde_json::from_str(include_str!("fixtures/project-conversation.json")).unwrap()
}
#[test]
fn approved_project_conversation_matches_192_fictional_legacy_answers() {
    let corpus = corpus();
    let records = corpus["records"].as_array().unwrap();
    assert_eq!(corpus["cases"].as_array().unwrap().len(), 192);
    let snapshots = records
        .iter()
        .map(|v| Snapshot::from_records(v.as_object().unwrap()).unwrap())
        .collect::<Vec<_>>();
    for (n, case) in corpus["cases"].as_array().unwrap().iter().enumerate() {
        let result = snapshots[case["records"].as_u64().unwrap() as usize]
            .conversation_answer(
                case["question"].as_str().unwrap(),
                case["rank"].as_u64().map(|n| n as usize),
                case["max_words"].as_u64().unwrap() as usize,
                case["max_characters"].as_u64().unwrap() as usize,
            )
            .unwrap();
        assert_eq!(result, case["output"], "case{n}:{case}");
    }
}
#[test]
fn project_conversation_refuses_foreign_approval_ids_and_unsupported_personal_claims() {
    for unsupported in [false, true] {
        let mut records = corpus()["records"][0].as_object().unwrap().clone();
        if unsupported {
            records.get_mut("candidate_project-01").unwrap()["approved"]["facts"][0]["verification"] =
                serde_json::json!("inferred");
        } else {
            records.get_mut("candidate_project-01").unwrap()["approved"]["project_id"] =
                serde_json::json!("project-foreign");
        }
        let result = Snapshot::from_records(&records)
            .and_then(|s| s.conversation_answer("Describe Queue", None, 100, 2000));
        assert!(result.is_err());
    }
}
#[test]
fn invalid_rank_limits_and_empty_question_never_invent_a_project_answer() {
    let corpus = corpus();
    let snapshot = Snapshot::from_records(corpus["records"][0].as_object().unwrap()).unwrap();
    for (question, rank, words, characters) in [
        ("", None, 100, 2000),
        ("Describe Queue", Some(0), 100, 2000),
        ("Describe Queue", Some(31), 100, 2000),
        ("Describe Queue", None, 0, 2000),
        ("Describe Queue", None, 100, 0),
    ] {
        assert!(
            snapshot
                .conversation_answer(question, rank, words, characters)
                .is_err()
        );
    }
    let missing = snapshot
        .conversation_answer("Describe Queue", Some(30), 100, 2000)
        .unwrap();
    assert_eq!(missing["status"], "missing_approved_context");
    assert_eq!(missing["sources"], serde_json::json!([]));
}
