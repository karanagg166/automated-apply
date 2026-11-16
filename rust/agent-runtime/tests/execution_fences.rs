//! Final-gate regression: an interrupted write cannot regain authority through Start.
use automated_apply_agents::execution::{fences, filters};
use serde_json::json;

#[test]
fn execution_stop_unknown_admissions_and_fresh_resume_paths_are_distinct() {
    for operation in filters::WRITES {
        let before = json!({"id":"fictional-work","stage":"APPLYING","status":"executing","operation":operation,"reason":null,"revision":8,"lease_token":"old-lease","lease_until":"2099-01-01T00:00:00Z","admitted_actions":[{"fingerprint":"apply:spent"}]});
        let unknown = fences::work(&before, "global_stop").unwrap().unwrap();
        assert_eq!(unknown["stage"], "SUBMISSION_UNKNOWN");
        assert_eq!(unknown["status"], "unknown");
        assert_eq!(unknown["revision"], 9);
        assert_eq!(unknown["admitted_actions"], before["admitted_actions"]);
        assert!(unknown["lease_token"].is_null());
        assert!(fences::work(&unknown, "owner_pause").unwrap().is_none());
        assert!(fences::resume(&unknown).unwrap().is_none());
        let mut queued = before.clone();
        queued["status"] = json!("queued");
        let paused = fences::work(&queued, "global_stop").unwrap().unwrap();
        let resumed = fences::resume(&paused).unwrap().unwrap();
        assert_eq!(resumed["operation"], "inspect_application");
        assert_eq!(resumed["stage"], "VERIFYING");
        assert_eq!(resumed["admitted_actions"], before["admitted_actions"]);
        let mut pending = queued.clone();
        pending["form_pending"] = json!(true);
        let pending = fences::resume(&fences::work(&pending, "owner_pause").unwrap().unwrap())
            .unwrap()
            .unwrap();
        if *operation == "answer_questionnaire" {
            assert_eq!(pending["operation"], "refresh_questionnaire_profile");
            assert_eq!(pending["stage"], "QUESTIONS");
        }
    }
    for stage in filters::TERMINAL {
        assert!(
            fences::work(&json!({"stage":stage,"status":"complete"}), "global_stop")
                .unwrap()
                .is_none()
        );
    }
    let corrupt = json!({"stage":"PAUSED","status":"unknown","reason":"global_stop","revision":10,"paused_context":{"operation":"apply","stage":"APPLYING"}});
    assert!(fences::resume(&corrupt).unwrap().is_none());
}
