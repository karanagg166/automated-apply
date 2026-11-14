use automated_apply_agents::resources::{Resource, assess_profile, public_https, select_resume};
use serde_json::{Value, json};
#[test]
fn fictional_resource_questions_keep_upload_narrative_and_confirmation_boundaries() {
    use automated_apply_agents::link_resolver::{question, resolve};
    let cases: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/link-corpus.json")).unwrap();
    for (i, case) in cases.iter().enumerate() {
        let resources: Vec<Resource> = serde_json::from_value(case["resources"].clone()).unwrap();
        let defaults = serde_json::from_value(case["defaults"].clone()).unwrap();
        for input in case["questions"].as_array().unwrap() {
            assert_eq!(
                resolve(
                    &case["profile"],
                    &resources,
                    &defaults,
                    input["question"].as_str().unwrap()
                ),
                input["output"],
                "case{i} question{}",
                input["question"]
            );
        }
    }
    assert_eq!(
        question(json!({"question":"  Github URL?  "})).unwrap(),
        "Github URL?"
    );
    for invalid in [
        json!({"question":" "}),
        json!({"question":4}),
        json!({"question":"github","approve":true}),
        json!({"question":"a".repeat(2001)}),
    ] {
        assert!(question(invalid).is_err());
    }
    let resource: Resource = serde_json::from_value(cases[2]["resources"][0].clone()).unwrap();
    let mut inventory = Vec::new();
    for _ in 0..101 {
        inventory.push(resource.clone());
    }
    let upload = resolve(
        &cases[2]["profile"],
        &inventory,
        &std::collections::BTreeMap::new(),
        "upload CV",
    );
    assert_eq!(upload["resources"].as_array().unwrap().len(), 100);
    assert!(upload["answer"].is_null());
}
#[test]
fn fictional_saved_link_provenance_corpus_and_private_defaults() {
    use automated_apply_agents::resources::{LINK_KINDS, link_defaults, resolved_link};
    use std::collections::BTreeMap;
    let cases: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/link-corpus.json")).unwrap();
    for (i, case) in cases.iter().enumerate() {
        let resources: Vec<Resource> = serde_json::from_value(case["resources"].clone()).unwrap();
        let defaults: BTreeMap<String, String> =
            serde_json::from_value(case["defaults"].clone()).unwrap();
        let links: Vec<_> = LINK_KINDS
            .iter()
            .map(|kind| resolved_link(&case["profile"], &resources, &defaults, kind))
            .collect();
        assert_eq!(json!(links), case["output"], "case{i}");
    }
    assert!(
        link_defaults(&BTreeMap::from([(
            "CANDIDATE_RESUME_DRIVE_URL".into(),
            "http://127.0.0.1/private".into()
        )]))
        .is_err()
    );
    assert_eq!(
        link_defaults(&BTreeMap::from([(
            "CANDIDATE_GITHUB_URL".into(),
            "https://github.com/fictional".into()
        )]))
        .unwrap()["github"],
        "https://github.com/fictional"
    );
}
#[test]
fn fictional_resource_and_evidence_contract_corpus() {
    use automated_apply_agents::resource_contract::{Operation, normalize};
    let cases: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/resource-contract-corpus.json")).unwrap();
    let mut errors = Vec::new();
    for (i, case) in cases.iter().enumerate() {
        let operation = match case["operation"].as_str().unwrap() {
            "resource" => Operation::Resource,
            "evidence" => Operation::Evidence,
            _ => Operation::Patch,
        };
        let result = normalize(operation, case["input"].clone());
        if result.is_ok() != case["accepted"].as_bool().unwrap()
            || result.as_ref().is_ok_and(|v| v != &case["value"])
        {
            errors.push(format!(
                "case{i}: input {} result{result:?} expected{}",
                case["input"], case["value"]
            ));
        }
    }
    assert!(
        errors.is_empty(),
        "{} differences:\n{}",
        errors.len(),
        errors.join("\n")
    );
}
#[test]
fn fictional_public_url_resume_and_readiness_differential_corpus() {
    let corpus: Value = serde_json::from_str(include_str!("fixtures/resume-corpus.json")).unwrap();
    let mut errors = Vec::new();
    for (i, case) in corpus["urls"].as_array().unwrap().iter().enumerate() {
        let actual = case["input"].as_str().and_then(public_https);
        if json!(actual) != case["output"] {
            errors.push(format!("url {i}: {} != {}", json!(actual), case["output"]));
        }
    }
    for (i, case) in corpus["selections"].as_array().unwrap().iter().enumerate() {
        let resources: Vec<Resource> = serde_json::from_value(case["resources"].clone()).unwrap();
        let selected = case["selected_id"].as_str().map(|s| s.parse().unwrap());
        let actual = serde_json::to_value(select_resume(&resources, selected).unwrap()).unwrap();
        if actual != case["output"] {
            errors.push(format!("selection {i}: different response fields"));
        }
    }
    for (i, case) in corpus["readiness"].as_array().unwrap().iter().enumerate() {
        let resources: Vec<Resource> = serde_json::from_value(case["resources"].clone()).unwrap();
        let actual = assess_profile(
            (!case["profile"].is_null()).then(|| case["profile"].clone()),
            &resources,
            case["live"].as_bool().unwrap(),
        );
        if let Some(expected) = case.get("output") {
            if actual.as_ref().ok() != Some(expected) {
                errors.push(format!("readiness {i}: {actual:?} != {expected}"));
            }
        } else if actual.is_ok() {
            errors.push(format!("readiness {i}: unexpected acceptance"));
        }
    }
    assert!(
        errors.is_empty(),
        "{} differences:\n{}",
        errors.len(),
        errors.join("\n")
    );
}
