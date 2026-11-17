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
fn acknowledged_read_routes_bind_distinct_nonzero_owner_and_read_uuids_with_no_provider_target_paths()
 {
    let parent = Uuid::from_u128(1);
    let read = Uuid::from_u128(2);
    let path = format!("/api/v1/discovery/runs/{parent}/reads/{read}");
    assert_eq!(owner::route(&path), Some(Route::Read(parent, read)));
    assert_eq!(
        owner::route(&format!("{path}/complete")),
        Some(Route::CompleteRead(parent, read))
    );
    assert!(Route::Read(parent, read).accepts("GET"));
    assert!(Route::Read(parent, read).accepts("PUT"));
    assert!(!Route::Read(parent, read).accepts("POST"));
    assert_eq!(Route::Read(parent, read).allow(), "GET, PUT");
    assert!(Route::CompleteRead(parent, read).accepts("POST"));
    assert!(!Route::CompleteRead(parent, read).accepts("PUT"));
    for bad in [
        format!("{path}/retry"),
        format!("{path}/complete/extra"),
        format!("/api/v1/discovery/runs/{parent}/reads/{parent}"),
        format!("/api/v1/discovery/runs/{parent}/reads/{}", Uuid::nil()),
        format!("/api/v1/discovery/runs/{parent}/reads/originalRun"),
    ] {
        assert!(owner::route(&bad).is_none(), "{bad}");
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
    for source in ["manual", "apify", "himalayas"] {
        assert_eq!(
            owner::execution_request(json!({"source":source})).unwrap_err(),
            Failure("discovery_source_execution_not_implemented")
        );
    }
}
#[test]
fn paid_owner_requests_use_separate_compatibility_namespace_without_granting_paid_authority() {
    let input =
        owner::execution_request(json!({"source":"naukri","idempotency_key":"fictional_original"}))
            .unwrap();
    assert_eq!(input["allow_paid"], false);
    assert_eq!(
        owner::compatibility_id(&input).unwrap(),
        Uuid::new_v5(
            &Uuid::NAMESPACE_URL,
            b"automated-apply:apify-discovery:fictional_original"
        )
    );
    let mut public = input.clone();
    public["source"] = json!("arbeitnow");
    assert_ne!(
        owner::compatibility_id(&input).unwrap(),
        owner::compatibility_id(&public).unwrap()
    );
    assert!(owner::execution_request(json!({"source":"naukri","manual_jobs":[{}]})).is_err());
    let row = Settings::from_values(&BTreeMap::new())
        .unwrap()
        .job("naukri", chrono::Utc::now())
        .unwrap();
    assert_eq!(row["owner_run_supported"], true);
    assert_eq!(row["native_execution_implemented"], true);
    assert_eq!(row["configuration"]["native_execution"]["ready"], false);
    assert_eq!(row["live_verified"], false);
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
