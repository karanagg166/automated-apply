use automated_apply_agents::job_context::{self, Reviewed};
use serde_json::{Value, json};
#[test]
fn saved_listing_corrections_preserve_employer_identity_and_legacy_digests() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/job-context-corpus.json")).unwrap();
    for (i, case) in corpus["listings"].as_array().unwrap().iter().enumerate() {
        let reviewed = Reviewed::new(
            case["job"].clone(),
            (!case["company"].is_null()).then(|| case["company"].clone()),
        )
        .unwrap();
        for key in case["view"].as_object().unwrap().keys() {
            assert_eq!(reviewed.job_view()[key], case["view"][key], "{i} {key}");
        }
        assert_eq!(json!(reviewed.employer()), case["employer"], "{i} employer");
        assert_eq!(
            reviewed.digest().unwrap(),
            case["job_digest"].as_str().unwrap(),
            "{i} digest"
        );
        assert_eq!(
            reviewed.binding().unwrap(),
            case["binding"].as_str().unwrap(),
            "{i} binding"
        );
    }
}
#[test]
fn only_current_bound_safe_employer_excerpts_are_selected() {
    let corpus: Value =
        serde_json::from_str(include_str!("fixtures/job-context-corpus.json")).unwrap();
    for (i, case) in corpus["excerpts"].as_array().unwrap().iter().enumerate() {
        let result = job_context::reviewed_opportunity(
            &case["view"],
            (!case["employer"].is_null()).then_some(&case["employer"]),
            case["now"].as_f64().unwrap(),
        )
        .unwrap();
        assert_eq!(json!(result), case["output"], "{i}");
        for projected in job_context::prompt_opportunity(&result) {
            assert_eq!(projected.as_object().unwrap().len(), 2);
            assert!(projected.get("source_url").is_none());
        }
    }
}
