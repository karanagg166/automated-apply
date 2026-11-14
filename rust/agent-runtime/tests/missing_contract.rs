use automated_apply_agents::{answer_contract::Generate, missing_contract as missing};
use serde_json::{Value, json};
use uuid::Uuid;
fn corpus() -> Value {
    serde_json::from_str(include_str!("fixtures/missing-input-corpus.json")).unwrap()
}
fn request(case: &Value) -> Generate {
    serde_json::from_value(json!({"question":case["question"],"job_id":case["job_id"],"company_name":case["company_name"],"job_description":case["job_description"],"writing_style":"professional","max_characters":1500,"max_words":null,"save_draft":false,"rewrite":false})).unwrap()
}
#[test]
fn missing_fact_requests_match_python_and_keep_confirmation_strict() {
    let mut errors = vec![];
    for (i, case) in corpus()["contracts"].as_array().unwrap().iter().enumerate() {
        let actual = match case["kind"].as_str().unwrap() {
            "create" => missing::normalize_create(case["input"].clone())
                .map(|v| serde_json::to_value(v).unwrap()),
            "edit" => missing::normalize_edit(case["input"].clone())
                .map(|v| serde_json::to_value(v).unwrap()),
            "approve" => missing::normalize_approve(case["input"].clone())
                .map(|v| serde_json::to_value(v).unwrap()),
            _ => panic!("fixture kind"),
        };
        if actual.is_ok() != (case["accepted"] == true)
            || actual.as_ref().is_ok_and(|v| v != &case["output"])
        {
            errors.push(format!("{i}: actual{actual:?} expected{case}"));
        }
    }
    assert!(
        errors.is_empty(),
        "{} differences:\n{}",
        errors.len(),
        errors.into_iter().take(6).collect::<Vec<_>>().join("\n")
    );
}
#[test]
fn sensitive_question_and_credential_answer_retention_matches_python() {
    for (i, case) in corpus()["retention"].as_array().unwrap().iter().enumerate() {
        let actual = missing::permitted(
            case["question"].as_str().unwrap(),
            case["answer"].as_str().unwrap(),
        );
        assert_eq!(actual.is_ok(), case["accepted"] == true, "{i}: {case}");
    }
}
#[test]
fn legacy_question_keys_match_but_cannot_alone_bind_an_approval() {
    let corpus = corpus();
    for (i, case) in corpus["keys"].as_array().unwrap().iter().enumerate() {
        let profile = case["profile_id"]
            .as_str()
            .unwrap()
            .parse::<Uuid>()
            .unwrap();
        let packet = case["packet_id"]
            .as_str()
            .map(|s| s.parse::<Uuid>().unwrap());
        let request = request(case);
        assert_eq!(
            missing::key_for(profile, &request, packet),
            case["key"].as_str().unwrap(),
            "{i}"
        );
        let saved = json!({"candidate_profile_id":profile,"question":request.question,"job_id":request.job_id,"packet_id":packet,"company_name":request.company_name,"job_description":request.job_description});
        assert!(missing::matches_context(&saved, profile, &request, packet));
        for field in [
            "candidate_profile_id",
            "question",
            "job_id",
            "packet_id",
            "company_name",
            "job_description",
        ] {
            let mut changed = saved.clone();
            changed[field] = json!("different");
            assert!(
                !missing::matches_context(&changed, profile, &request, packet),
                "{i} {field}"
            );
            changed.as_object_mut().unwrap().remove(field);
            assert!(
                !missing::matches_context(&changed, profile, &request, packet),
                "{i} missing {field}"
            );
        }
    }
    for (a, b) in [(0, 1), (3, 4)] {
        let a = &corpus["keys"][a];
        let b = &corpus["keys"][b];
        assert_eq!(a["key"], b["key"], "legacy ambiguous fixture");
        let profile = a["profile_id"].as_str().unwrap().parse().unwrap();
        let stored = json!({"candidate_profile_id":profile,"question":a["question"],"job_id":a["job_id"],"packet_id":a["packet_id"],"company_name":a["company_name"],"job_description":a["job_description"]});
        assert!(!missing::matches_context(
            &stored,
            profile,
            &request(b),
            None
        ));
    }
}
