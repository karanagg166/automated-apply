//! Deferred original parent-to-child mapping invariants. No SQL or network.
use automated_apply_agents::{
    research_contract::{self, Kind},
    startup_catalog::job_led,
};
use serde_json::json;
use uuid::Uuid;
#[test]
fn startup_child_keeps_original_query_separate_from_company_filters_and_preserves_profile_choice() {
    let request=research_contract::normalize(Kind::StartupRun,json!({"source":"arbeitnow","mode":"job_led","idempotency_key":"fictional_scope","query":{"keywords":["Rust"],"locations":["Remote"]},"filters":{"roles":["Python"],"locations":["India"],"use_profile":false}}),chrono::Utc::now()).unwrap();
    let parent = job_led::request_id(&request).unwrap();
    let child = job_led::child_input(&request, parent).unwrap();
    assert_eq!(child["query"], request["query"]);
    assert_eq!(child["use_profile"], false);
    assert_eq!(child["idempotency_key"], format!("startup_child_{parent}"));
    assert_eq!(child["manual_jobs"], json!([]));
    assert_ne!(job_led::child_id(parent), parent);
    assert_ne!(
        job_led::child_id(parent),
        job_led::child_id(Uuid::from_u128(1))
    );
    assert_eq!(job_led::child_id(parent), job_led::child_id(parent));
}
#[test]
fn paid_startup_child_preserves_explicit_paid_optin_and_deterministic_job_scope() {
    for source in ["wellfound", "work_at_a_startup"] {
        let raw = json!({"source":source,"mode":"job_led","allow_paid":true,"idempotency_key":"fictional_paid_startup","filters":{"use_profile":false},"query":{"limit":20}});
        let request =
            research_contract::normalize(Kind::StartupRun, raw, chrono::Utc::now()).unwrap();
        let id = job_led::request_id(&request).unwrap();
        let child = job_led::child_input(&request, id).unwrap();
        assert_eq!(child["source"], source);
        assert_eq!(child["allow_paid"], true);
        assert_eq!(child["query"], request["query"]);
        assert_eq!(child["use_profile"], false);
        assert_eq!(child["manual_jobs"], json!([]));
        assert_eq!(child["idempotency_key"], format!("startup_child_{id}"));
    }
}
#[test]
fn startup_uuid_owner_routes_separate_saved_get_original_put_and_local_complete_post() {
    use automated_apply_agents::startup_catalog::owner::{self, Route};
    let id = Uuid::from_u128(1);
    let root = format!("/api/v1/startups/discovery/runs/{id}");
    assert_eq!(owner::route(&root), Some(Route::Run(id)));
    assert!(Route::Run(id).accepts("GET"));
    assert!(Route::Run(id).accepts("PUT"));
    assert!(!Route::Run(id).accepts("POST"));
    assert_eq!(
        owner::route(&format!("{root}/complete")),
        Some(Route::Complete(id))
    );
    assert!(Route::Complete(id).accepts("POST"));
    assert!(!Route::Complete(id).accepts("GET"));
    for bad in [
        format!("{root}/retry"),
        format!("{root}/complete/extra"),
        format!("/api/v1/startups/discovery/runs/{}", Uuid::nil()),
    ] {
        assert!(owner::route(&bad).is_none());
    }
}
