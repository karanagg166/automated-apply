//! Deferred pure owner route/identity/metadata guards. No HTTP or database.
use automated_apply_agents::{
    Failure,
    job_sources::owner::{self, Route},
    source_registry::Settings,
};
use serde_json::json;
use std::collections::BTreeMap;
use uuid::Uuid;
#[test]
fn owner_discovery_routes_are_closed_and_method_specific() {
    let id = Uuid::from_u128(1);
    let root = format!("/api/v1/discovery/runs/{id}");
    assert_eq!(owner::route(&root), Some(Route::Run(id)));
    assert!(Route::Run(id).accepts("PUT"));
    assert!(Route::Run(id).accepts("GET"));
    assert!(!Route::Run(id).accepts("POST"));
    assert_eq!(
        owner::route(&format!("{root}/complete")),
        Some(Route::Complete(id))
    );
    assert!(!Route::Complete(id).accepts("PUT"));
    for path in [
        "/api/v1/discovery/runs/",
        "/api/v1/discovery/runs/private",
        &format!("{root}/retry"),
        &format!("{root}/complete/extra"),
    ] {
        assert!(owner::route(path).is_none());
    }
}
#[test]
fn compatibility_post_requires_stable_key_and_execution_does_not_grant_unsupported_sources() {
    assert_eq!(
        owner::compatibility_id(&json!({})).unwrap_err(),
        Failure("discovery_run_idempotency_key_required")
    );
    let a = owner::execution_request(
        json!({"source":"arbeitnow","idempotency_key":"fictional_original"}),
    )
    .unwrap();
    let mut b = a.clone();
    b["query"]["limit"] = json!(10);
    assert_eq!(
        owner::compatibility_id(&a).unwrap(),
        owner::compatibility_id(&b).unwrap()
    );
    b["idempotency_key"] = json!("different_original");
    assert_ne!(
        owner::compatibility_id(&a).unwrap(),
        owner::compatibility_id(&b).unwrap()
    );
    for source in ["manual", "naukri", "apify", "himalayas"] {
        assert_eq!(
            owner::execution_request(json!({"source":source})).unwrap_err(),
            Failure("discovery_source_execution_not_implemented")
        );
    }
}
#[test]
fn metadata_distinguishes_native_public_owner_runs_from_existing_feed_and_startup_paths() {
    let settings = Settings::from_values(&BTreeMap::new()).unwrap();
    let now = chrono::Utc::now();
    for source in [
        "greenhouse",
        "lever",
        "ashby",
        "smartrecruiters",
        "remotive",
        "arbeitnow",
        "hacker_news",
    ] {
        let row = settings.job(source, now).unwrap();
        assert_eq!(row["owner_run_supported"], true);
        assert_eq!(row["native_execution_implemented"], true);
        assert_eq!(row["live_verified"], false);
        assert_eq!(row["dispatch_authorized"], false);
    }
    assert_eq!(
        settings.job("himalayas", now).unwrap()["owner_run_supported"],
        false
    );
    assert_eq!(
        settings.startup("arbeitnow", now).unwrap()["native_execution_implemented"],
        true
    );
}
