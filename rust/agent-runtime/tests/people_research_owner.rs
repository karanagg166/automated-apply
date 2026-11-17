//! Deferred closed native owner routes. These paths never alias an unkeyed paid search.
use automated_apply_agents::people_research::owner::{self, Route};
#[test]
fn professional_research_owner_methods_and_uuid_paths_are_closed() {
    let id = "00000000-0000-0000-0000-000000000001";
    let request =
        owner::route(&format!("/api/v1/rust-agent/research/people/requests/{id}")).unwrap();
    assert!(request.accepts("GET"));
    assert!(request.accepts("PUT"));
    assert!(!request.accepts("POST"));
    assert_eq!(request.allow(), "GET, PUT");
    assert_eq!(
        owner::route("/api/v1/rust-agent/research/people/status"),
        Some(Route::Status)
    );
    assert_eq!(
        owner::route("/api/v1/discovery/people/search"),
        Some(Route::Legacy)
    );
    for path in [
        "/api/v1/rust-agent/research/people/requests/",
        "/api/v1/rust-agent/research/people/requests/private",
        "/api/v1/rust-agent/research/people/status/reset",
        "/api/v1/rust-agent/research/people/requests/00000000-0000-0000-0000-000000000001/retry",
    ] {
        assert_eq!(owner::route(path), None);
    }
}
